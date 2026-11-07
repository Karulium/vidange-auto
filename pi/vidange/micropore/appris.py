"""Le fichier des gestes appris du micropore (donnees/micropore-appris.yaml).

    appris = FichierAppris(donnees / "micropore-appris.yaml")
    appris.format("seau_a")                  # FormatAppris, ou None : format pas appris
    appris.noter_escamote(40.0, "karulium")  # l'angle « escamoté » du servo
    appris.noter_format("seau_a", FormatAppris(...), "karulium")
    appris.annuler("karulium")               # défait le dernier changement (rend son numéro)

Les angles des gestes (escamoté ; approche, contact, appui et caméra → rouleau par format) ne
sont jamais dans le code ni dans pi/reglages/ : Karulium les apprend sur la machine
(vidange-micropore, pi/systeme/essai-micropore.md). Chaque changement est noté dans
l'historique du fichier (quand, qui, avant, après) et peut être annulé : l'annulation est
elle-même un changement, notée à la suite. Le fichier est réécrit d'un coup (fichier provisoire,
puis remplacé) : jamais à moitié. Sans fichier (`fichier` None : simulateur, essais), tout reste
en mémoire.
"""

import os
import threading
from datetime import datetime
from pathlib import Path

import yaml
from pydantic import ValidationError

from vidange.journal import donner_journal
from vidange.reglages import (
    ChangementAppris,
    ErreurReglages,
    FormatAppris,
    GestesAppris,
    lire_yaml,
    traduire_erreurs,
)

journal = donner_journal("micropore.appris")

ESCAMOTE = "escamote"
ENTETE = (
    "# Gestes appris du micropore : écrit par le Pi (vidange-micropore), jamais à la main.\n"
    "# Annuler un changement : « vidange-micropore annuler ».\n"
)


class FichierAppris:
    def __init__(self, fichier: Path | None, depart: GestesAppris | None = None) -> None:
        """`depart` : les gestes du départ quand il n'y a pas de fichier (simulateur)."""
        self.fichier = fichier
        self._verrou = threading.Lock()
        self.erreur: str | None = None
        self._gestes = depart or GestesAppris()
        if fichier is not None and fichier.exists():
            try:
                self._gestes = GestesAppris.model_validate(lire_yaml(fichier))
            except ErreurReglages as erreur:
                self.erreur = str(erreur)
            except ValidationError as erreur:
                self.erreur = "\n".join(traduire_erreurs(erreur, fichier.name))
            if self.erreur is not None:
                journal.error("Gestes appris du micropore illisibles : %s", self.erreur)

    @property
    def gestes(self) -> GestesAppris:
        with self._verrou:
            return self._gestes

    @property
    def escamote_deg(self) -> float | None:
        return self.gestes.escamote_deg

    def format(self, nom: str) -> FormatAppris | None:
        return self.gestes.formats.get(nom)

    # ------------------------------------------------------------ changements

    def noter_escamote(self, angle_deg: float, qui: str) -> int:
        return self._changer(ESCAMOTE, angle_deg, qui)

    def noter_format(self, nom: str, valeurs: FormatAppris, qui: str) -> int:
        return self._changer(nom, valeurs, qui)

    def annuler(self, qui: str) -> int | None:
        """Défait le dernier changement pas encore annulé (une annulation ne s'annule pas :
        réapprendre). Rend le numéro du changement défait, ou None s'il n'y a rien à défaire."""
        with self._verrou:
            for changement in reversed(self._gestes.historique):
                if changement.annule is None and changement.annule_par is None:
                    break
            else:
                return None
            numero = len(self._gestes.historique) + 1
            historique = [
                c.model_copy(update={"annule_par": numero}) if c.numero == changement.numero else c
                for c in self._gestes.historique
            ]
            self._appliquer(
                changement.cle,
                changement.avant,
                ChangementAppris(
                    numero=numero,
                    quand=_maintenant(),
                    qui=qui,
                    cle=changement.cle,
                    avant=changement.apres,
                    apres=changement.avant,
                    annule=changement.numero,
                ),
                historique,
            )
            return changement.numero

    def _changer(self, cle: str, valeur: FormatAppris | float, qui: str) -> int:
        with self._verrou:
            avant = self._gestes.escamote_deg if cle == ESCAMOTE else self._gestes.formats.get(cle)
            numero = len(self._gestes.historique) + 1
            changement = ChangementAppris(
                numero=numero, quand=_maintenant(), qui=qui, cle=cle, avant=avant, apres=valeur
            )
            self._appliquer(cle, valeur, changement, list(self._gestes.historique))
            journal.info("Micropore : geste appris n° %d (%s) par %s", numero, cle, qui)
            return numero

    def _appliquer(
        self,
        cle: str,
        valeur: FormatAppris | float | None,
        changement: ChangementAppris,
        historique: list[ChangementAppris],
    ) -> None:
        formats = dict(self._gestes.formats)
        escamote = self._gestes.escamote_deg
        if cle == ESCAMOTE:
            assert valeur is None or isinstance(valeur, (int, float))
            escamote = valeur
        elif valeur is None:
            formats.pop(cle, None)
        else:
            assert isinstance(valeur, FormatAppris)
            formats[cle] = valeur
        gestes = GestesAppris(
            escamote_deg=escamote, formats=formats, historique=[*historique, changement]
        )
        self._sauver(gestes)
        self._gestes = gestes

    def _sauver(self, gestes: GestesAppris) -> None:
        if self.fichier is None:
            return
        texte = ENTETE + yaml.safe_dump(
            gestes.model_dump(exclude_none=True), allow_unicode=True, sort_keys=False
        )
        self.fichier.parent.mkdir(parents=True, exist_ok=True)
        provisoire = self.fichier.with_suffix(".provisoire")
        provisoire.write_text(texte, encoding="utf-8")
        os.replace(provisoire, self.fichier)


def _maintenant() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
