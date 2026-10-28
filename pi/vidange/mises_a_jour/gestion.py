"""Les mises à jour lancées depuis la page web : une à la fois, seulement machine à l'arrêt.

    maj = MisesAJour(reglages.programme.mises_a_jour, dossier, cartes, pi, chef, liaisons,
                     dossier_fluidnc, registre, pilote, redemarrer)
    maj.refus()                                  # pourquoi pas maintenant, ou None
    maj.recevoir_programme("fluidnc-3.9.5.bin", donnees)   # fichier envoyé par la page
    maj.ecrire_programme("portique", "fluidnc-3.9.5.bin", qui)
    maj.envoyer_reglages("portique", qui)        # fluidnc/portique.yaml
    maj.revenir_carte("portique", None, qui)     # la dernière copie de sa mémoire
    maj.chercher_pi(qui) / maj.installer_pi(qui) / maj.revenir_pi(qui)
    maj.etat()                                   # pour la page web

« Machine à l'arrêt » : aucun module en plein cycle ni en alarme (un module qui attend le Go de
sa toute première étape n'a encore rien bougé : il ne gêne pas), pas de pilotage à distance,
aucun axe en mouvement. Au départ d'une mise à jour, la machine est mise en pause, et elle y
reste après (Reprendre quand on veut). Pendant la mise à jour, l'API refuse Go, Reprise et
pilotage à distance.

Chaque travail tourne dans un fil à part ; la page suit ses étapes. Chaque changement est noté
au journal et dans le registre (réglages appliqués : qui, quand, ancien, nouveau). Après une
mise à jour réussie du programme du Pi, le programme redémarre (systemd le relance).
"""

import os
import re
import threading
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any

from vidange.chef import Chef
from vidange.fluidnc import Liaison
from vidange.fluidnc.ports import ouvrir_port_usb, trouver_port
from vidange.journal import donner_journal
from vidange.mises_a_jour.cartes import CarteEsp32, Resultat, verifier_contenu_programme
from vidange.mises_a_jour.commun import ErreurMiseAJour
from vidange.mises_a_jour.pi import ProgrammePi
from vidange.registre import ErreurRegistre, Registre
from vidange.reglages import Reglages, ReglagesMisesAJour

journal = donner_journal("mises_a_jour")

# Dossier des mises à jour dans celui des données, et ses dossiers.
DOSSIER = "mises-a-jour"
DOSSIER_COPIES = "copies"
DOSSIER_PROGRAMMES = "programmes"
# États de FluidNC où un axe bouge. « Hold:1 » : pause en train de ralentir ; « Hold:0 » (pause
# finie, axes arrêtés) ne gêne pas : la pause du chef y met aussi les cartes au repos.
EN_MOUVEMENT = ("Run", "Jog", "Home", "Hold:1")
NOM_PROGRAMME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}\.bin$")


@dataclass
class Travail:
    """Une mise à jour : en cours, ou la dernière finie."""

    quoi: str
    qui: str
    debut: str
    etapes: list[str] = field(default_factory=list)
    fin: str | None = None
    reussi: bool | None = None
    message: str = ""


def _maintenant() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def preparer_cartes(reglages: Reglages, dossier: Path) -> dict[str, CarteEsp32]:
    """Les cartes FluidNC de fluidnc.yaml, reconnues par le numéro de série de leur USB.

    `dossier` : celui des mises à jour (les copies de la mémoire vont dans « copies »).
    """
    liaison = reglages.fluidnc.liaison
    return {
        nom: CarteEsp32(
            nom,
            reglages.programme.mises_a_jour.cartes,
            dossier / DOSSIER_COPIES,
            trouver_port=partial(trouver_port, carte.numero_serie_usb),
            ouvrir_console=partial(
                ouvrir_port_usb,
                carte.numero_serie_usb,
                liaison.vitesse_bauds,
                liaison.periode_etat_s,
            ),
        )
        for nom, carte in reglages.fluidnc.cartes.items()
    }


class MisesAJour:
    def __init__(
        self,
        reglages: ReglagesMisesAJour,
        dossier: Path,
        cartes: Mapping[str, CarteEsp32],
        pi: ProgrammePi | None,
        chef: Chef | None,
        liaisons: Mapping[str, Liaison],
        dossier_fluidnc: Path,
        registre: Registre | None = None,
        pilote: Any = None,
        redemarrer: Callable[[], object] | None = None,
    ) -> None:
        self.reglages = reglages
        self.dossier = dossier
        self.cartes = cartes
        self.pi = pi
        self.chef = chef
        self.liaisons = liaisons
        self.dossier_fluidnc = dossier_fluidnc
        self.registre = registre
        # Le pilote à distance (PiloteDistance) : seul « actif » sert ici.
        self.pilote = pilote
        self._redemarrer = redemarrer
        self._verrou = threading.Lock()
        self._travail: Travail | None = None
        self._dernier: Travail | None = None
        self._nouvelles: list[dict[str, str]] | None = None
        self._fil: threading.Thread | None = None

    # ------------------------------------------------------------ ce qu'on sait

    @property
    def en_cours(self) -> bool:
        return self._travail is not None

    def _refus_machine(self) -> str | None:
        if self.pilote is not None and self.pilote.actif:
            return "pilotage à distance en cours"
        if self.chef is not None:
            occupes = []
            for module in self.chef.etat().modules:
                if module.statut == "alarme":
                    occupes.append(f"« {module.module} » en alarme")
                elif module.statut == "en_cours" and not (
                    module.numero == 1 and module.phase == "go"
                ):
                    occupes.append(f"« {module.module} » (étape « {module.etape} »)")
            if occupes:
                return f"cycle en cours : {', '.join(occupes)}"
        bougent = [
            nom
            for nom, liaison in self.liaisons.items()
            if (liaison.etat.etat or "").startswith(EN_MOUVEMENT)
        ]
        if bougent:
            return f"axes en mouvement (cartes {', '.join(bougent)})"
        return None

    def refus(self) -> str | None:
        """Pourquoi une mise à jour ne peut pas partir maintenant (None : elle peut)."""
        travail = self._travail
        if travail is not None:
            return f"une mise à jour est en cours ({travail.quoi})"
        return self._refus_machine()

    def fichier_reglages(self, carte: str) -> Path:
        return self.dossier_fluidnc / f"{carte}.yaml"

    def programmes(self) -> list[dict[str, Any]]:
        """Les fichiers de programme envoyés par la page, le plus récent d'abord."""
        dossier = self.dossier / DOSSIER_PROGRAMMES
        fichiers = sorted(
            (f for f in dossier.glob("*.bin") if f.is_file()),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        return [
            {
                "nom": f.name,
                "taille": f.stat().st_size,
                "quand": datetime.fromtimestamp(f.stat().st_mtime)
                .astimezone()
                .isoformat(timespec="seconds"),
            }
            for f in fichiers
        ]

    def etat(self) -> dict[str, Any]:
        travail, dernier = self._travail, self._dernier
        pi: dict[str, Any] | None = None
        if self.pi is not None:
            try:
                version = self.pi.version()
            except ErreurMiseAJour as erreur:
                version = {"erreur": str(erreur)}
            pi = {"version": version, "avant": self.pi.avant(), "nouvelles": self._nouvelles}
        return {
            "en_cours": None if travail is None else asdict(travail),
            "dernier": None if dernier is None else asdict(dernier),
            "refus": self.refus(),
            "cartes": [
                {
                    "nom": nom,
                    "reglages": self.fichier_reglages(nom).is_file(),
                    "fichier_reglages": f"fluidnc/{nom}.yaml",
                    "copies": [asdict(copie) for copie in carte.copies()],
                }
                for nom, carte in self.cartes.items()
            ],
            "programmes": self.programmes(),
            "pi": pi,
        }

    # ------------------------------------------------------------ fichiers de programme

    def recevoir_programme(self, nom: str, contenu: bytes) -> dict[str, Any]:
        """Garde un fichier de programme (.bin) envoyé par la page web."""
        if not NOM_PROGRAMME.match(nom):
            raise ErreurMiseAJour(
                f"nom de fichier refusé « {nom} » : lettres, chiffres, « . », « - », « _ », "
                "et finir par « .bin »"
            )
        verifier_contenu_programme(nom, contenu, self.reglages.cartes)
        dossier = self.dossier / DOSSIER_PROGRAMMES
        dossier.mkdir(parents=True, exist_ok=True)
        provisoire = dossier / f"{nom}.provisoire"
        provisoire.write_bytes(contenu)
        os.replace(provisoire, dossier / nom)
        journal.info("Programme reçu : %s (%d octets)", nom, len(contenu))
        for vieux in self.programmes()[self.reglages.cartes.programmes_gardes :]:
            (dossier / vieux["nom"]).unlink(missing_ok=True)
        return {"nom": nom, "taille": len(contenu)}

    # ------------------------------------------------------------ travaux

    def _carte(self, nom: str) -> CarteEsp32:
        if nom not in self.cartes:
            raise ErreurMiseAJour(f"carte « {nom} » inconnue (cartes : {', '.join(self.cartes)})")
        return self.cartes[nom]

    def _noter(self, qui: str, fichier: str, reglage: str, ancien: Any, nouveau: Any, raison: str):
        if self.registre is None:
            return
        try:
            self.registre.noter_reglage(qui, fichier, reglage, ancien, nouveau, raison)
        except ErreurRegistre as erreur:
            journal.error("Mise à jour pas notée dans le registre : %s", erreur)

    def _lancer(
        self,
        quoi: str,
        qui: str,
        faire: Callable[[Callable[[str], None]], str],
        machine_arretee: bool = True,
        carte: str | None = None,
        apres: Callable[[], object] | None = None,
    ) -> None:
        with self._verrou:
            if self._travail is not None:
                raise ErreurMiseAJour(f"une mise à jour est déjà en cours ({self._travail.quoi})")
            if machine_arretee:
                refus = self._refus_machine()
                if refus is not None:
                    journal.warning("Mise à jour refusée (%s) : %s", quoi, refus)
                    raise ErreurMiseAJour(f"Mise à jour refusée : {refus}.")
            travail = Travail(quoi, qui, _maintenant())
            self._travail = travail
        journal.warning("Mise à jour : %s (%s)", quoi, qui)
        if machine_arretee and self.chef is not None and not self.chef.en_pause:
            self.chef.pause()
            travail.etapes.append("Machine mise en pause")
        self._fil = threading.Thread(
            target=self._faire,
            args=(travail, faire, carte, apres),
            name="mise-a-jour",
            daemon=True,
        )
        self._fil.start()

    def _faire(
        self,
        travail: Travail,
        faire: Callable[[Callable[[str], None]], str],
        carte: str | None,
        apres: Callable[[], object] | None,
    ) -> None:
        def etape(texte: str) -> None:
            journal.info("Mise à jour (%s) : %s", travail.quoi, texte)
            travail.etapes.append(texte)

        liaison = self.liaisons.get(carte) if carte is not None else None
        try:
            if liaison is not None:
                etape("Liaison ordinaire avec la carte arrêtée")
                liaison.arreter()
            travail.message = faire(etape)
            travail.reussi = True
        except ErreurMiseAJour as erreur:
            travail.message, travail.reussi = str(erreur), False
        except Exception as erreur:
            journal.exception("Erreur imprévue pendant la mise à jour")
            travail.message, travail.reussi = f"erreur imprévue : {erreur!r}", False
        finally:
            if liaison is not None:
                liaison.demarrer()
            travail.fin = _maintenant()
        if travail.reussi:
            journal.warning("Mise à jour réussie (%s) : %s", travail.quoi, travail.message)
        else:
            journal.error("Mise à jour ratée (%s) : %s", travail.quoi, travail.message)
        relancer = travail.reussi and apres is not None
        if relancer:
            travail.etapes.append("Le programme redémarre (la page revient toute seule)")
        with self._verrou:
            self._dernier = travail
            self._travail = None
        if relancer:
            assert apres is not None
            apres()

    def attendre(self, delai_s: float | None = None) -> None:
        """Attend la fin du travail en cours (pour les essais et l'outil vidange-maj)."""
        fil = self._fil
        if fil is not None:
            fil.join(delai_s)

    # ------------------------------------------------------------ cartes

    def _changer_carte(
        self,
        nom: str,
        qui: str,
        quoi: str,
        reglage: str,
        nouveau: str,
        changer: Callable[[Callable[[str], None]], Resultat],
    ) -> None:
        def faire(etape: Callable[[str], None]) -> str:
            resultat = changer(etape)
            self._noter(qui, f"carte {nom}", reglage, resultat.avant, nouveau, resultat.message)
            return resultat.message

        self._lancer(quoi, qui, faire, carte=nom)

    def ecrire_programme(self, carte: str, fichier: str, qui: str) -> None:
        esp32 = self._carte(carte)
        chemin = self.dossier / DOSSIER_PROGRAMMES / fichier
        if not NOM_PROGRAMME.match(fichier) or not chemin.is_file():
            raise ErreurMiseAJour(f"pas de fichier de programme « {fichier} » sur le Pi")
        self._changer_carte(
            carte,
            qui,
            f"programme « {fichier} » → carte « {carte} »",
            "programme",
            fichier,
            lambda etape: esp32.ecrire_programme(chemin, etape),
        )

    def envoyer_reglages(self, carte: str, qui: str) -> None:
        esp32 = self._carte(carte)
        chemin = self.fichier_reglages(carte)
        if not chemin.is_file():
            raise ErreurMiseAJour(f"pas encore de fichier de réglages « fluidnc/{carte}.yaml »")
        self._changer_carte(
            carte,
            qui,
            f"réglages « {chemin.name} » → carte « {carte} »",
            "réglages FluidNC",
            chemin.name,
            lambda etape: esp32.envoyer_reglages(chemin, etape),
        )

    def revenir_carte(self, carte: str, copie: str | None, qui: str) -> None:
        esp32 = self._carte(carte)
        copies = [c.nom for c in esp32.copies()]
        if not copies or (copie is not None and copie not in copies):
            raise ErreurMiseAJour(f"pas de copie « {copie or 'récente'} » de la carte « {carte} »")
        nom_copie = copie or copies[0]
        self._changer_carte(
            carte,
            qui,
            f"carte « {carte} » : retour à la copie {nom_copie}",
            "retour à une copie",
            nom_copie,
            lambda etape: esp32.revenir(nom_copie, etape),
        )

    # ------------------------------------------------------------ programme du Pi

    def _le_pi(self) -> ProgrammePi:
        if self.pi is None:
            raise ErreurMiseAJour("pas de mise à jour du programme du Pi ici")
        return self.pi

    def chercher_pi(self, qui: str) -> None:
        pi = self._le_pi()

        def faire(etape: Callable[[str], None]) -> str:
            etape(f"Téléchargement de « {pi.distante} »")
            self._nouvelles = pi.chercher()
            if not self._nouvelles:
                return "le programme du Pi est à jour"
            return f"{len(self._nouvelles)} changement(s) à installer"

        self._lancer("recherche d'une nouvelle version du programme du Pi", qui, faire, False)

    def _changer_pi(self, qui: str, quoi: str, changer: Callable[[], str]) -> None:
        pi = self._le_pi()

        def faire(etape: Callable[[str], None]) -> str:
            ancien = pi.version()
            etape("Téléchargement, installation et vérification des réglages (quelques minutes)")
            message = changer()
            nouveau = pi.version()
            self._nouvelles = None
            self._noter(
                qui, "programme du Pi", "version", ancien["court"], nouveau["court"], message
            )
            return message

        self._lancer(quoi, qui, faire, apres=self._redemarrer)

    def installer_pi(self, qui: str) -> None:
        self._changer_pi(
            qui, "mise à jour du programme du Pi", lambda: self._le_pi().installer(qui)
        )

    def revenir_pi(self, qui: str) -> None:
        self._changer_pi(
            qui,
            "retour à la version d'avant du programme du Pi",
            lambda: self._le_pi().revenir(qui),
        )
