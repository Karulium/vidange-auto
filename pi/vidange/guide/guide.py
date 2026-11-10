"""Mode guidé (fonction 84, tâche 32) : la machine explique un travail pas à pas à une personne.

    guide = Guide(reglages.guide, lire_signal, registre)
    guide.demarrer("changer_pot", "page web (Paul, 192.168.1.5)")
    guide.fait("page web (Paul, ...)")      # étape faite : passe à la suivante
    guide.precedent(qui)                    # revenir d'une étape
    guide.arreter(qui)                      # abandonner

Un seul travail guidé à la fois, partagé par la page web et l'écran de l'armoire (la personne
peut commencer sur le téléphone et finir devant la machine). Le guide **ne commande rien** : il
montre des phrases ; la personne fait les gestes à la main et dit « Fait ». Si une étape cite un
signal d'entrée (guide.yaml), la machine dit si elle voit l'étape faite, mais cela informe
seulement : la personne peut dire « Fait » quand même, et le désaccord est noté. La sécurité des
personnes reste câblée (règle n° 1) : le guide ne la remplace pas et ne la lit pas.

Les droits sont ceux de la page web : voir et suivre = « regarder » et « produire » (donc
l'employé), le visiteur regarde seulement. À la fin d'un travail, une note est écrite au carnet
de bord (qui, quoi, quand). Rien n'est gardé après un redémarrage : un travail guidé interrompu
par une coupure se recommence (il ne coûte que des phrases).
"""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from vidange.journal import donner_journal
from vidange.registre import ErreurRegistre, Registre
from vidange.reglages import ReglagesGuide, TravailGuide

journal = donner_journal("guide")


class ErreurGuide(Exception):
    """Un ordre du guide qu'on ne peut pas exécuter ; le message dit pourquoi, en français."""


@dataclass(frozen=True)
class EtatGuide:
    actif: bool = False
    # Fini : toutes les étapes sont faites ; le travail reste affiché jusqu'à « arreter ».
    termine: bool = False
    travail: str = ""
    titre: str = ""
    qui: str = ""
    # Numéro de l'étape en cours, à partir de 1, et nombre d'étapes.
    numero: int = 0
    total: int = 0
    texte: str = ""
    signal: str | None = None
    # Ce que la machine voit pour le signal de l'étape : vrai, faux ou None (inconnu).
    vu: bool | None = None
    # Vrai si la machine voit l'étape comme faite (None : pas de signal ou signal inconnu).
    machine_d_accord: bool | None = None
    messages: tuple[str, ...] = field(default=())

    def en_dict(self) -> dict[str, Any]:
        return {
            "actif": self.actif,
            "termine": self.termine,
            "travail": self.travail,
            "titre": self.titre,
            "qui": self.qui,
            "numero": self.numero,
            "total": self.total,
            "texte": self.texte,
            "signal": self.signal,
            "vu": self.vu,
            "machine_d_accord": self.machine_d_accord,
            "messages": list(self.messages),
        }


class Guide:
    def __init__(
        self,
        reglages: ReglagesGuide,
        lire_signal: Callable[[str], bool | None] | None = None,
        registre: Registre | None = None,
        horloge: Callable[[], float] = time.monotonic,
    ) -> None:
        """`lire_signal(nom)` rend ce que la machine voit (vrai, faux) ou None si elle ne sait
        pas ; sans lui (essais, pas de matériel), le guide marche sans la lecture des signaux."""
        self.reglages = reglages
        self._lire_signal = lire_signal
        self._registre = registre
        self._horloge = horloge
        self._verrou = threading.Lock()
        self._travail: str | None = None
        self._etape = 0
        self._qui = ""
        self._depuis = 0.0
        self._termine = False
        self._desaccords: list[str] = []

    # ------------------------------------------------------------ lecture

    def liste(self) -> list[dict[str, Any]]:
        """Les travaux qu'on peut commencer, dans l'ordre du fichier de réglages."""
        return [
            {
                "travail": nom,
                "titre": travail.titre,
                "quand": travail.quand,
                "etapes": len(travail.etapes),
                "exemple": travail.exemple,
            }
            for nom, travail in self.reglages.travaux.items()
        ]

    def _travail_en_cours(self) -> TravailGuide | None:
        if self._travail is None:
            return None
        return self.reglages.travaux[self._travail]

    def _oublie(self) -> bool:
        return (
            self._travail is not None
            and self._horloge() - self._depuis > self.reglages.oubli_min * 60
        )

    def _effacer(self) -> None:
        self._travail = None
        self._etape = 0
        self._qui = ""
        self._termine = False
        self._desaccords = []

    def _voir(self, signal: str | None) -> bool | None:
        if signal is None or self._lire_signal is None:
            return None
        try:
            return self._lire_signal(signal)
        except Exception as erreur:
            # Une lecture qui échoue ne gêne pas le guide : il montre « ? ».
            journal.warning("Guide : le signal « %s » n'a pas pu être lu : %s", signal, erreur)
            return None

    def etat(self) -> EtatGuide:
        with self._verrou:
            if self._oublie():
                journal.info(
                    "Guide : travail « %s » oublié par %s, effacé", self._travail, self._qui
                )
                self._effacer()
            travail = self._travail_en_cours()
            if travail is None or self._travail is None:
                return EtatGuide()
            total = len(travail.etapes)
            if self._termine:
                return EtatGuide(
                    actif=True,
                    termine=True,
                    travail=self._travail,
                    titre=travail.titre,
                    qui=self._qui,
                    numero=total,
                    total=total,
                    texte="Travail terminé : merci.",
                    messages=tuple(self._desaccords),
                )
            etape = travail.etapes[self._etape]
            vu = self._voir(etape.signal)
            return EtatGuide(
                actif=True,
                travail=self._travail,
                titre=travail.titre,
                qui=self._qui,
                numero=self._etape + 1,
                total=total,
                texte=etape.texte,
                signal=etape.signal,
                vu=vu,
                machine_d_accord=None if vu is None else vu == etape.attendu,
                messages=tuple(self._desaccords),
            )

    # ------------------------------------------------------------ ordres

    def demarrer(self, travail: str, qui: str) -> EtatGuide:
        with self._verrou:
            if self._oublie():
                self._effacer()
            if travail not in self.reglages.travaux:
                raise ErreurGuide(f"travail « {travail} » inconnu (guide.yaml → travaux)")
            if self._travail is not None:
                raise ErreurGuide(
                    f"un travail guidé est déjà en cours (« {self._travail} », par {self._qui}) : "
                    "le finir ou l'arrêter d'abord"
                )
            self._travail = travail
            self._etape = 0
            self._qui = qui
            self._depuis = self._horloge()
            self._termine = False
            self._desaccords = []
            journal.info("Guide : travail « %s » commencé par %s", travail, qui)
        return self.etat()

    def fait(self, qui: str) -> EtatGuide:
        """L'étape est faite : on passe à la suivante (ou on termine)."""
        etat = self.etat()
        with self._verrou:
            travail = self._travail_en_cours()
            if travail is None or self._travail is None:
                raise ErreurGuide("aucun travail guidé en cours")
            if self._termine:
                raise ErreurGuide(
                    "le travail est déjà terminé : l'arrêter pour en commencer un autre"
                )
            if etat.machine_d_accord is False:
                self._desaccords.append(
                    f"étape {etat.numero} : « Fait » dit par {qui} alors que la machine "
                    f"ne voit pas « {etat.signal} » comme attendu"
                )
                journal.warning("Guide : %s", self._desaccords[-1])
            self._depuis = self._horloge()
            if self._etape + 1 >= len(travail.etapes):
                self._termine = True
                self._noter_fin(self._travail, travail, qui)
            else:
                self._etape += 1
        return self.etat()

    def precedent(self, qui: str) -> EtatGuide:
        """Revenir à l'étape d'avant (ou rouvrir la dernière si le travail est terminé)."""
        self.etat()
        with self._verrou:
            if self._travail is None:
                raise ErreurGuide("aucun travail guidé en cours")
            if self._termine:
                self._termine = False
            elif self._etape == 0:
                raise ErreurGuide("c'est déjà la première étape")
            else:
                self._etape -= 1
            self._depuis = self._horloge()
        return self.etat()

    def arreter(self, qui: str) -> EtatGuide:
        """Abandonner le travail, ou fermer l'écran de fin. Sans travail : rien à faire."""
        with self._verrou:
            if self._travail is not None:
                if not self._termine:
                    journal.info(
                        "Guide : travail « %s » arrêté par %s à l'étape %d",
                        self._travail,
                        qui,
                        self._etape + 1,
                    )
                self._effacer()
        return self.etat()

    # ------------------------------------------------------------ mémoire

    def _noter_fin(self, nom: str, travail: TravailGuide, qui: str) -> None:
        journal.info("Guide : travail « %s » terminé par %s", nom, qui)
        if self._registre is None:
            return
        texte = f"Travail guidé « {travail.titre} » terminé ({len(travail.etapes)} étapes)."
        if self._desaccords:
            texte += " La machine n'a pas vu : " + " ; ".join(self._desaccords) + "."
        try:
            self._registre.noter_carnet(qui, texte)
        except ErreurRegistre as erreur:
            journal.error("Guide : fin de travail pas notée au carnet : %s", erreur)
