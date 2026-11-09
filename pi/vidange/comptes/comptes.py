"""Les comptes de la page web : qui a le droit de faire quoi.

Trois rôles :
  - `karulium` : tous les droits (regarder, produire, régler) ;
  - `employe`  : regarder et produire (Go, lots, boutons de production), pas de réglages ;
  - `visiteur` : regarder seulement.

Chaque route de l'API demande un niveau minimum (`Niveau`) : regarder, produire ou régler.

Le fichier des comptes (`comptes.yaml`) est HORS de Git, à côté du fichier de secrets (sur le Pi :
/etc/vidange/comptes.yaml). Il ne contient que des mots de passe HACHÉS (scrypt, bibliothèque
standard) : jamais un mot de passe lisible. Le dépôt n'a que le modèle vide `comptes.exemple.yaml`.
On le change avec la commande `vidange compte ...` ; le programme relit le fichier dès qu'il change
(pas besoin de redémarrer).

La connexion donne un cookie signé (HMAC-SHA256 avec `cle_session`, du même fichier) qui vaut
quelques heures (programme.yaml → api → session_h). Supprimer un compte ou changer son mot de passe
ou son rôle annule ses cookies tout de suite.
"""

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Any

import yaml

from vidange.journal import donner_journal
from vidange.reglages import ErreurReglages

journal = donner_journal("comptes")

# Un mot de passe plus court se devine trop vite.
LONGUEUR_MIN_MOT_DE_PASSE = 10
_NOM_VALIDE = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")

# Coût du hachage scrypt (mémoire = 128 × N × r octets = 16 Mo ici) : lent pour qui devine, quasi
# invisible pour une connexion. Ces nombres sont écrits dans chaque hachage : on peut les changer
# plus tard sans casser les anciens comptes.
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1
_SCRYPT_MEMOIRE_MAX = 64 * 1024 * 1024
_FORME_HACHAGE = re.compile(r"^scrypt\$(\d+)\$(\d+)\$(\d+)\$([0-9a-f]{32})\$([0-9a-f]{64})$")


class Niveau(IntEnum):
    """Ce qu'une route demande, du plus petit au plus grand."""

    REGARDER = 1
    PRODUIRE = 2
    REGLER = 3


class Role(IntEnum):
    """Le niveau le plus haut que le rôle permet."""

    VISITEUR = int(Niveau.REGARDER)
    EMPLOYE = int(Niveau.PRODUIRE)
    KARULIUM = int(Niveau.REGLER)

    @property
    def nom(self) -> str:
        return self.name.lower()

    @classmethod
    def depuis_nom(cls, nom: str) -> "Role":
        try:
            return cls[str(nom).strip().upper()]
        except KeyError:
            noms = ", ".join(r.nom for r in cls)
            raise ErreurComptes(f"rôle inconnu « {nom} » (choisir parmi : {noms})") from None

    def permet(self, niveau: Niveau) -> bool:
        return int(self) >= int(niveau)


class ErreurComptes(ErreurReglages):
    """Fichier des comptes faux, ou commande de compte impossible (le message dit quoi faire)."""


@dataclass(frozen=True)
class Compte:
    nom: str
    role: Role


def verifier_nom(nom: str) -> str:
    nom = nom.strip().lower()
    if not _NOM_VALIDE.match(nom):
        raise ErreurComptes(
            f"nom de compte « {nom} » refusé : 2 à 32 caractères, des lettres minuscules sans "
            "accent, des chiffres, « - » ou « _ », en commençant par une lettre"
        )
    return nom


def verifier_mot_de_passe_assez_long(mot_de_passe: str) -> None:
    if len(mot_de_passe) < LONGUEUR_MIN_MOT_DE_PASSE:
        raise ErreurComptes(
            f"mot de passe trop court : au moins {LONGUEUR_MIN_MOT_DE_PASSE} caractères "
            "(une phrase facile à retenir est meilleure qu'un mot compliqué)"
        )


def hacher(mot_de_passe: str, sel: bytes | None = None) -> str:
    sel = sel if sel is not None else secrets.token_bytes(16)
    empreinte = hashlib.scrypt(
        mot_de_passe.encode(),
        salt=sel,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        maxmem=_SCRYPT_MEMOIRE_MAX,
        dklen=32,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${sel.hex()}${empreinte.hex()}"


def mot_de_passe_juste(mot_de_passe: str, hachage: str) -> bool:
    forme = _FORME_HACHAGE.match(hachage)
    if forme is None:
        return False
    n, r, p = int(forme[1]), int(forme[2]), int(forme[3])
    if 128 * n * r > _SCRYPT_MEMOIRE_MAX:
        return False
    try:
        calcule = hashlib.scrypt(
            mot_de_passe.encode(),
            salt=bytes.fromhex(forme[4]),
            n=n,
            r=r,
            p=p,
            maxmem=_SCRYPT_MEMOIRE_MAX,
            dklen=32,
        )
    except ValueError:
        return False
    return hmac.compare_digest(calcule.hex(), forme[5])


def _b64(donnees: bytes) -> str:
    return base64.urlsafe_b64encode(donnees).decode().rstrip("=")


def _debase64(texte: str) -> bytes:
    return base64.urlsafe_b64decode(texte + "=" * (-len(texte) % 4))


class Comptes:
    """Le fichier des comptes, relu quand il change. Sûr à utiliser depuis plusieurs fils."""

    def __init__(self, chemin: Path, horloge: Callable[[], float] = time.time) -> None:
        self.chemin = chemin
        self._horloge = horloge
        self._verrou = threading.Lock()
        self._signature: tuple[int, int] | None = None
        self._cle_session = ""
        self._comptes: dict[str, tuple[Role, str]] = {}
        self._lire_si_change()

    # ------------------------------------------------------------ lecture

    def _lire_si_change(self) -> None:
        with self._verrou:
            try:
                etat = self.chemin.stat()
                signature = (etat.st_mtime_ns, etat.st_size)
            except FileNotFoundError:
                self._signature, self._cle_session, self._comptes = None, "", {}
                return
            if signature == self._signature:
                return
            try:
                cle, comptes = lire_fichier(self.chemin)
            except ErreurComptes as erreur:
                # Fichier abîmé en cours de route : on garde ce qu'on savait déjà.
                journal.error("%s", erreur)
                self._signature = signature
                return
            self._signature, self._cle_session, self._comptes = signature, cle, comptes

    @property
    def vide(self) -> bool:
        """Aucun compte : la page refuse tout sauf l'explication du premier compte."""
        self._lire_si_change()
        return not self._comptes

    def noms(self) -> dict[str, Role]:
        self._lire_si_change()
        return {nom: role for nom, (role, _) in sorted(self._comptes.items())}

    # ------------------------------------------------------------ connexion

    def verifier(self, nom: str, mot_de_passe: str) -> Compte | None:
        """Le compte si le nom et le mot de passe sont justes, sinon None (même durée dans les
        deux cas : on ne devine pas quels noms existent)."""
        self._lire_si_change()
        nom = nom.strip().lower()
        connu = self._comptes.get(nom)
        hachage = connu[1] if connu else _HACHAGE_BIDON
        juste = mot_de_passe_juste(mot_de_passe, hachage)
        if connu is None or not juste:
            return None
        return Compte(nom, connu[0])

    def _empreinte(self, nom: str) -> str:
        role, hachage = self._comptes[nom]
        return hashlib.sha256(f"{role.nom}|{hachage}".encode()).hexdigest()[:12]

    def creer_session(self, compte: Compte, duree_s: float) -> str:
        self._lire_si_change()
        if not self._cle_session or compte.nom not in self._comptes:
            raise ErreurComptes("pas de session possible : compte ou « cle_session » absent")
        charge = {
            "n": compte.nom,
            "e": int(self._horloge() + duree_s),
            "f": self._empreinte(compte.nom),
        }
        corps = _b64(json.dumps(charge, separators=(",", ":")).encode())
        return f"{corps}.{self._signer(corps)}"

    def _signer(self, corps: str) -> str:
        return _b64(hmac.new(self._cle_session.encode(), corps.encode(), hashlib.sha256).digest())

    def lire_session(self, jeton: str | None) -> Compte | None:
        """Le compte du cookie, ou None (cookie absent, faux, périmé, compte supprimé ou changé)."""
        if not jeton or "." not in jeton:
            return None
        self._lire_si_change()
        if not self._cle_session:
            return None
        corps, _, signature = jeton.partition(".")
        if not hmac.compare_digest(signature, self._signer(corps)):
            return None
        try:
            charge = json.loads(_debase64(corps))
            nom, fin, empreinte = str(charge["n"]), float(charge["e"]), str(charge["f"])
        except (ValueError, KeyError, TypeError):
            return None
        connu = self._comptes.get(nom)
        if connu is None or fin < self._horloge():
            return None
        if not hmac.compare_digest(empreinte, self._empreinte(nom)):
            return None
        return Compte(nom, connu[0])

    # ------------------------------------------------------------ changements (« vidange compte »)

    def ajouter(self, nom: str, role: Role, mot_de_passe: str) -> None:
        nom = verifier_nom(nom)
        verifier_mot_de_passe_assez_long(mot_de_passe)
        self._modifier(lambda comptes: self._ajouter(comptes, nom, role, mot_de_passe))

    @staticmethod
    def _ajouter(comptes: dict, nom: str, role: Role, mot_de_passe: str) -> None:
        if nom in comptes:
            raise ErreurComptes(f"le compte « {nom} » existe déjà (pour le changer : « changer »)")
        comptes[nom] = (role, hacher(mot_de_passe))

    def changer(self, nom: str, role: Role | None = None, mot_de_passe: str | None = None) -> None:
        nom = nom.strip().lower()
        if mot_de_passe is not None:
            verifier_mot_de_passe_assez_long(mot_de_passe)

        def faire(comptes: dict) -> None:
            if nom not in comptes:
                raise ErreurComptes(f"pas de compte « {nom} »")
            ancien_role, ancien_hachage = comptes[nom]
            nouveau = role if role is not None else ancien_role
            if ancien_role is Role.KARULIUM and nouveau is not Role.KARULIUM:
                _garder_un_karulium(comptes, sauf=nom)
            comptes[nom] = (nouveau, hacher(mot_de_passe) if mot_de_passe else ancien_hachage)

        self._modifier(faire)

    def supprimer(self, nom: str) -> None:
        nom = nom.strip().lower()

        def faire(comptes: dict) -> None:
            if nom not in comptes:
                raise ErreurComptes(f"pas de compte « {nom} »")
            if comptes[nom][0] is Role.KARULIUM:
                _garder_un_karulium(comptes, sauf=nom)
            del comptes[nom]

        self._modifier(faire)

    def _modifier(self, changement: Callable[[dict[str, tuple[Role, str]]], None]) -> None:
        with self._verrou:
            cle, comptes = "", {}
            if self.chemin.exists():
                cle, comptes = lire_fichier(self.chemin)
            changement(comptes)
            cle = cle or secrets.token_urlsafe(32)
            ecrire_fichier(self.chemin, cle, comptes)
            self._signature = None
        self._lire_si_change()


def _garder_un_karulium(comptes: dict, sauf: str) -> None:
    if not any(r is Role.KARULIUM for n, (r, _) in comptes.items() if n != sauf):
        raise ErreurComptes(
            f"« {sauf} » est le dernier compte « karulium » : en créer un autre d'abord "
            "(sinon plus personne ne pourrait régler la machine)"
        )


_HACHAGE_BIDON = hacher("mot de passe pour faire durer pareil", sel=b"\0" * 16)


def lire_fichier(chemin: Path) -> tuple[str, dict[str, tuple[Role, str]]]:
    """Lit et vérifie le fichier des comptes : (cle_session, {nom: (rôle, hachage)})."""
    try:
        brut: Any = yaml.safe_load(chemin.read_text(encoding="utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError) as erreur:
        raise ErreurComptes(f"{chemin.name} : fichier mal écrit ({erreur})") from None
    if brut is None:
        return "", {}
    if not isinstance(brut, dict) or set(brut) - {"cle_session", "comptes"}:
        raise ErreurComptes(f"{chemin.name} : seuls « cle_session » et « comptes » sont permis")
    cle = brut.get("cle_session") or ""
    liste = brut.get("comptes") or {}
    if not isinstance(cle, str) or not isinstance(liste, dict):
        raise ErreurComptes(f"{chemin.name} : « cle_session » et « comptes » mal écrits")
    comptes: dict[str, tuple[Role, str]] = {}
    for nom, fiche in liste.items():
        lieu = f"{chemin.name}, comptes → {nom}"
        if not isinstance(nom, str) or not _NOM_VALIDE.match(nom):
            raise ErreurComptes(f"{lieu} : nom de compte refusé (minuscules sans accent)")
        if not isinstance(fiche, dict) or set(fiche) != {"role", "mot_de_passe"}:
            raise ErreurComptes(f"{lieu} : il faut « role » et « mot_de_passe » (haché)")
        try:
            role = Role.depuis_nom(fiche["role"])
        except ErreurComptes as erreur:
            raise ErreurComptes(f"{lieu} → role : {erreur}") from None
        if not isinstance(fiche["mot_de_passe"], str) or not _FORME_HACHAGE.match(
            fiche["mot_de_passe"]
        ):
            raise ErreurComptes(
                f"{lieu} → mot_de_passe : pas un mot de passe haché par « vidange compte » "
                "(ne jamais écrire un mot de passe à la main dans ce fichier)"
            )
        comptes[nom] = (role, fiche["mot_de_passe"])
    if comptes and len(cle) < 32:
        raise ErreurComptes(
            f"{chemin.name} : « cle_session » absente ou trop courte. Refaire un compte avec "
            "« vidange compte ajouter » ou remettre la clé de la sauvegarde"
        )
    return cle, comptes


def ecrire_fichier(chemin: Path, cle: str, comptes: dict[str, tuple[Role, str]]) -> None:
    """Écrit le fichier d'un coup (jamais à moitié) et lisible par son seul propriétaire."""
    donnees = {
        "cle_session": cle,
        "comptes": {
            nom: {"role": role.nom, "mot_de_passe": hachage}
            for nom, (role, hachage) in sorted(comptes.items())
        },
    }
    texte = (
        "# Comptes de la page web. Fichier fabriqué par « vidange compte » : ne pas le modifier\n"
        "# à la main. HORS de Git. Mots de passe hachés seulement.\n"
        + yaml.safe_dump(donnees, allow_unicode=True, sort_keys=False)
    )
    temporaire = chemin.with_name(chemin.name + ".tmp")
    descripteur = os.open(temporaire, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descripteur, "w", encoding="utf-8") as fichier:
        fichier.write(texte)
        fichier.flush()
        os.fsync(fichier.fileno())
    os.replace(temporaire, chemin)


def charger_comptes(chemin: Path) -> Comptes:
    """Lit les comptes au démarrage. Fichier absent ou sans compte : permis (page « premier
    compte »). Fichier faux : ErreurComptes, le programme ne démarre pas."""
    if chemin.exists():
        if chemin.stat().st_mode & 0o077:
            journal.warning(
                "Le fichier des comptes %s est lisible par d'autres comptes : « chmod 600 %s ».",
                chemin,
                chemin,
            )
        lire_fichier(chemin)
    return Comptes(chemin)
