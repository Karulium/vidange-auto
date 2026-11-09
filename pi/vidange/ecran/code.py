"""Le code des fonctions sensibles de l'écran (tâche 29, fonction 50).

CE CODE ÉVITE LES FAUSSES MANOEUVRES, IL NE PROTÈGE PAS LES PERSONNES : l'arrêt d'urgence, les
portes et les fins de course de sécurité sont câblés en dur. Le logiciel peut planter sans danger.

Le code (4 à 6 chiffres, `programme.yaml → ecran → code → longueur`) est gardé HACHÉ (scrypt, la
même méthode que les mots de passe de la page web) dans `code_ecran.yaml`, à côté de secrets.yaml,
hors de Git (le dépôt n'a que le modèle vide `code_ecran.exemple.yaml`). On le change avec
`vidange code-ecran`. Sans code réglé, les fonctions sensibles sont refusées.

Trop d'essais ratés de suite : plus d'essai pendant `attente_s`. Un code juste ouvre les fonctions
sensibles pendant `valable_s`, puis il faut le retaper.
"""

import os
import re
import threading
import time
from collections.abc import Callable
from pathlib import Path

import yaml

from vidange.comptes.comptes import hacher, mot_de_passe_juste
from vidange.fiabilite.constats import Constat
from vidange.journal import donner_journal
from vidange.reglages import ErreurReglages, ReglagesCodeEcran

journal = donner_journal("code écran")

_FORME_HACHAGE = re.compile(r"^scrypt\$\d+\$\d+\$\d+\$[0-9a-f]{32}\$[0-9a-f]{64}$")
QUOI_FAIRE = "Sur le Pi : « vidange code-ecran » (voir pi/systeme/essai-ecran.md)."


def lire_hachage(chemin: Path) -> str | None:
    """Le hachage du fichier, ou None s'il n'y a pas de code. Fichier faux : ErreurReglages."""
    if not chemin.exists():
        return None
    try:
        brut = yaml.safe_load(chemin.read_text(encoding="utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError) as erreur:
        raise ErreurReglages(f"{chemin.name} : fichier mal écrit ({erreur})") from None
    if brut is None:
        return None
    if not isinstance(brut, dict) or set(brut) != {"code"}:
        raise ErreurReglages(f"{chemin.name} : seule la ligne « code » est permise")
    if brut["code"] in (None, ""):
        return None
    if not isinstance(brut["code"], str) or not _FORME_HACHAGE.match(brut["code"]):
        raise ErreurReglages(
            f"{chemin.name} → code : pas un code haché par « vidange code-ecran » "
            "(ne jamais écrire le code à la main dans ce fichier)"
        )
    return brut["code"]


def verifier_chiffres(code: str, longueur: int) -> None:
    if not (code.isascii() and code.isdigit()) or len(code) != longueur:
        raise ErreurReglages(
            f"le code doit avoir exactement {longueur} chiffres (programme.yaml → ecran → code → "
            "longueur), rien d'autre que des chiffres"
        )


def ecrire_code(chemin: Path, code: str, longueur: int) -> None:
    """Écrit le code haché d'un coup (jamais à moitié), lisible par son seul propriétaire."""
    verifier_chiffres(code, longueur)
    texte = (
        "# Code des fonctions sensibles de l'écran. Fichier fabriqué par « vidange code-ecran » :\n"
        "# ne pas le modifier à la main. HORS de Git. Code haché seulement.\n"
        + yaml.safe_dump({"code": hacher(code)})
    )
    temporaire = chemin.with_name(chemin.name + ".tmp")
    descripteur = os.open(temporaire, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descripteur, "w", encoding="utf-8") as fichier:
        fichier.write(texte)
        fichier.flush()
        os.fsync(fichier.fileno())
    os.replace(temporaire, chemin)


class CodeEcran:
    """Vérifie les codes tapés sur l'écran. Le fichier est relu quand il change."""

    def __init__(
        self,
        chemin: Path,
        reglages: ReglagesCodeEcran,
        horloge: Callable[[], float] = time.monotonic,
    ) -> None:
        self.chemin = chemin
        self.reglages = reglages
        self._horloge = horloge
        self._verrou = threading.Lock()
        self._signature: tuple[int, int] | None = None
        self._hachage: str | None = None
        self._ratees = 0
        self._bloque_jusqu_a = 0.0
        self._valable_jusqu_a = 0.0
        self._lire_si_change()

    def _lire_si_change(self) -> None:
        try:
            etat = self.chemin.stat()
            signature = (etat.st_mtime_ns, etat.st_size)
        except FileNotFoundError:
            signature = None
        if signature == self._signature and (signature is not None or self._hachage is None):
            return
        try:
            hachage = lire_hachage(self.chemin)
        except ErreurReglages as erreur:
            journal.error("%s", erreur)
            hachage = None
        self._signature, self._hachage = signature, hachage
        # Un nouveau code annule tout ce qui était ouvert.
        self._ratees, self._bloque_jusqu_a, self._valable_jusqu_a = 0, 0.0, 0.0

    @property
    def regle(self) -> bool:
        with self._verrou:
            self._lire_si_change()
            return self._hachage is not None

    def refus(self) -> str | None:
        """Pourquoi on ne peut pas taper un code maintenant (None : on peut)."""
        with self._verrou:
            self._lire_si_change()
            if self._hachage is None:
                return "Code de l'écran pas réglé : lancer « vidange code-ecran » sur le Pi."
            reste = self._bloque_jusqu_a - self._horloge()
            if reste > 0:
                return f"Trop de codes faux : attendre {reste:.0f} s."
            return None

    def encore_valable(self) -> bool:
        with self._verrou:
            self._lire_si_change()
            return self._horloge() < self._valable_jusqu_a

    @property
    def essais_restants(self) -> int:
        return max(0, self.reglages.essais_max - self._ratees)

    def verifier(self, saisie: str) -> bool:
        """Le code tapé est-il juste ? Compte les échecs ; un code juste ouvre `valable_s`."""
        if self.refus() is not None:
            return False
        with self._verrou:
            assert self._hachage is not None
            if mot_de_passe_juste(saisie, self._hachage):
                self._ratees = 0
                self._valable_jusqu_a = self._horloge() + self.reglages.valable_s
                return True
            self._ratees += 1
            if self._ratees >= self.reglages.essais_max:
                self._bloque_jusqu_a = self._horloge() + self.reglages.attente_s
                self._ratees = 0
                journal.warning(
                    "Code de l'écran faux %d fois de suite : attente de %g s",
                    self.reglages.essais_max,
                    self.reglages.attente_s,
                )
            return False

    def constats(self) -> list[Constat]:
        """Pour la check-list : jamais bloquant (la machine tourne ; seules les fonctions
        sensibles de l'écran sont refusées)."""
        if self.regle:
            return [Constat("code de l'écran", "ok", "réglé")]
        return [
            Constat(
                "code de l'écran",
                "attention",
                "pas réglé : les fonctions sensibles (mode, store, nuit...) sont refusées",
                QUOI_FAIRE,
            )
        ]
