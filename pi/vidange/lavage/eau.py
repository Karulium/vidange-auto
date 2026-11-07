"""L'eau du fût de lavage : remplir, vider, arroser, rincer, chauffer ; et le jet d'air du col.

    eau = EauLavage(reglages.machine.lavage, signaux, fichier=donnees / "lavage.json")
    eau.flotteur_haut()          # flotteur haut depuis flotteur_stable_s (vagues du brossage)
    eau.surveiller()             # prise du thermoplongeur : seulement flotteur haut, pompe arrêtée
    yield from eau.geste_remplir()   # dans un geste joué par la préhension (vidange.lavage)

Les gestes de l'eau sont des attentes (Attente : flotteur) et des temps (Pas sans mouvement :
vannes motorisées, rinçage), joués par le même déroulé que les gestes de la tête : ils
s'enchaînent avec eux dans le lavage d'un seau.

Remplir : vanne à bille fermée, électrovanne d'eau ouverte jusqu'au flotteur haut. Temps maximal
= premier remplissage mesuré + marge (avant lui : premier_remplissage_max_s) ; au-delà, alerte et
électrovanne fermée (l'arrêt du module coupe tout) : l'eau monterait aux poulies.
Vider : vanne 3 voies vers la bonde, vanne à bille ouverte, pompe ; flotteur retombé, encore
apres_flotteur_s, puis pompe arrêtée et vanne fermée.
Arroser (pendant le brossage) : la pompe envoie le bain dans les rampes. Jamais à sec : fût
rempli pour la série (pas encore vidé) avant de commencer.
Rincer : électrovanne de rinçage (eau propre dans les rampes) duree_s, puis la pompe vide vers
la bonde jusqu'au flotteur bas, pour garder le même niveau ; puis quelques secondes d'eau du
réseau remettent le fût au flotteur haut (au plus remise_max_s), pour que le bain reste chauffé.
Chauffer : le Pi ferme son relais (commande du SSR du thermoplongeur, thermostat à 50 °C sur
l'appareil) que fût rempli pour la série, flotteur haut et pompe arrêtée ; sinon il attend et
informe. Il ne mesure pas la température. Contre le chauffage à sec, la sécurité est CÂBLÉE :
relais_flotteur est en série dans la commande du SSR (flotteur bas ou fil coupé : plus de
commande, quoi que fasse le Pi) ; ce que fait le logiciel n'est pas une protection.

La vanne à bille reste ouverte pendant la série, à condition que la vanne 3 voies revienne sur
« rampes » dès que la pompe s'arrête (pas de siphon vers la bonde). Fût rempli, pompe arrêtée,
si le flotteur retombe sans vidange demandée : alerte « fuite ou siphon », vanne à bille fermée
(`niveau_tenu`, surveillance du chef).

Le premier temps de remplissage et « il y a de l'eau dans le fût » sont gardés dans un fichier
(ils survivent à un redémarrage) : le Pi refuse de finir une série sans vidange.

Rien ici ne protège personne : la sécurité est câblée. Le logiciel peut planter sans danger.
"""

import json
import os
import time
from collections.abc import Callable
from pathlib import Path

from vidange.chef import ErreurEtape
from vidange.journal import donner_journal
from vidange.porte_bocal.signaux import Signaux
from vidange.prehension.prehension import Attente, Geste
from vidange.prehension.tete import Pas
from vidange.reglages import Lavage

journal = donner_journal("lavage.eau")

# Le fichier de l'eau du fût, dans le dossier des données (vidange-lavage, programme principal).
NOM_EAU = "lavage.json"

# Noms des signaux (docs/entrees-sorties.yaml, fluidnc.yaml).
FLOTTEUR = "flotteur_lavage"
EAU = "eau_reseau_lavage"
VIDANGE = "vanne_vidange_lavage"
POMPE = "pompe_lavage"
RAMPES = "vanne_rampes_lavage"
RINCAGE = "rincage_lavage"
AIR = "air_col_lavage"
# Relais du Pi (pas une carte FluidNC) qui alimente la commande du SSR du thermoplongeur.
CHAUFFAGE = "relais_chauffage_lavage"
# Ce qui s'arrête à toute alarme (les vannes motorisées restent où elles sont).
A_COUPER = (EAU, POMPE, RINCAGE, AIR, CHAUFFAGE)

QUOI_FAIRE_REMPLISSAGE = (
    "Le fût de lavage ne s'est pas rempli à temps : l'eau est coupée. Regarder le fût (fuite, "
    "vanne à bille ouverte, flotteur coincé, robinet du réseau fermé ?). Corriger, puis "
    "acquitter et donner le Go."
)
QUOI_FAIRE_VIDANGE = (
    "Le fût de lavage ne s'est pas vidé à temps : la pompe est arrêtée. Regarder la pompe, la "
    "vanne à bille, la vanne 3 voies et la bonde (bouchée ?), et le flotteur. Corriger, puis "
    "acquitter et donner le Go."
)
QUOI_FAIRE_REMISE = (
    "Après le rinçage, l'eau du réseau n'a pas remis le fût de lavage au flotteur haut à temps : "
    "l'eau est coupée. Regarder le fût (fuite, vanne à bille, flotteur coincé, robinet du réseau "
    "fermé ?). Corriger, puis acquitter et donner le Go."
)
QUOI_FAIRE_FUITE = (
    "Le niveau du fût de lavage a baissé sans vidange demandée, pompe arrêtée : fuite ou siphon "
    "vers la bonde. La vanne à bille est fermée. Regarder le fût, la bonde, la vanne 3 voies "
    "(revenue sur « rampes » ?) et les tuyaux. Corriger, puis acquitter et donner le Go."
)
QUOI_FAIRE_A_SEC = (
    "Le fût de lavage n'est pas rempli : on ne brosse jamais à sec. Le remplir (étape "
    "« remplir »), regarder s'il fuit, puis acquitter et donner le Go."
)


class EauLavage:
    def __init__(
        self,
        reglages: Lavage,
        signaux: Signaux,
        horloge: Callable[[], float] = time.monotonic,
        fichier: Path | None = None,
    ) -> None:
        """`signaux` : les entrées et sorties du lavage (vidange.lavage.signaux). `fichier` :
        où garder le premier temps de remplissage et l'eau dans le fût (None : en mémoire)."""
        self.reglages = reglages
        self.signaux = signaux
        self._horloge = horloge
        self.fichier = fichier
        memoire = self._lire()
        # Premier remplissage mesuré (s), et de l'eau dans le fût (rempli, pas encore vidé).
        self.premier_remplissage_s: float | None = memoire.get("premier_remplissage_s")
        self.eau_dans_le_fut: bool = memoire.get("eau_dans_le_fut", False)
        # Vannes motorisées : None tant qu'on ne sait pas (après un démarrage). La vanne 3 voies
        # est commandée depuis _voie_depuis (elle met vanne_rampes_s à tourner).
        self.vidange_ouverte: bool | None = None
        self.voie_rampes: bool | None = None
        self._voie_depuis = 0.0
        self.pompe = False
        # Le fût doit être au flotteur haut (rempli, pas de vidange en cours) : surveillé.
        self._niveau_haut = False
        self._chauffage: bool | None = None
        # Pourquoi le chauffage attend (fût rempli, mais chauffage pas permis), sinon None.
        self.chauffage_attend: str | None = None
        # Flotteur : dernière valeur lue et depuis quand.
        self._flotteur: bool | None = None
        self._flotteur_depuis = 0.0
        # Pause de Karulium : sorties coupées, rallumées à la reprise ; temps passé en pause.
        self._figees: dict[str, bool] = {}
        self._sorties: dict[str, bool] = {}
        self._pause_depuis: float | None = None
        self._pause_cumulee = 0.0

    # ------------------------------------------------------------ fichier

    def _lire(self) -> dict:
        if self.fichier is None or not self.fichier.exists():
            return {}
        try:
            memoire = json.loads(self.fichier.read_text(encoding="utf-8"))
        except (OSError, ValueError) as erreur:
            journal.warning("Lavage : fichier %s illisible (%s)", self.fichier, erreur)
            return {}
        return memoire if isinstance(memoire, dict) else {}

    def _garder(self) -> None:
        if self.fichier is None:
            return
        memoire = {
            "premier_remplissage_s": self.premier_remplissage_s,
            "eau_dans_le_fut": self.eau_dans_le_fut,
        }
        try:
            self.fichier.parent.mkdir(parents=True, exist_ok=True)
            provisoire = self.fichier.with_suffix(".tmp")
            provisoire.write_text(json.dumps(memoire), encoding="utf-8")
            os.replace(provisoire, self.fichier)
        except OSError as erreur:
            journal.error("Lavage : fichier %s pas écrit (%s)", self.fichier, erreur)

    # ------------------------------------------------------------ flotteur et sorties

    def flotteur(self) -> bool | None:
        """Le flotteur, lu maintenant (None : carte pas lue)."""
        return self._lire_flotteur()

    def _lire_flotteur(self) -> bool | None:
        valeur = self.signaux.entree(FLOTTEUR)
        if valeur != self._flotteur:
            self._flotteur, self._flotteur_depuis = valeur, self._horloge()
        return valeur

    def _flotteur_stable(self, voulu: bool) -> bool:
        valeur = self._lire_flotteur()
        stable = self._horloge() - self._flotteur_depuis >= self.reglages.eau.flotteur_stable_s
        return valeur is voulu and stable

    def flotteur_haut(self) -> bool:
        return self._flotteur_stable(True)

    def flotteur_bas(self) -> bool:
        return self._flotteur_stable(False)

    def _sortie(self, nom: str, actif: bool) -> None:
        self.signaux.sortie(nom, actif)
        self._sorties[nom] = actif

    def _pompe(self, marche: bool) -> None:
        if marche:
            # Jamais le thermoplongeur avec la pompe en marche.
            self._regler_chauffage(False)
        self._sortie(POMPE, marche)
        self.pompe = marche
        if not marche:
            # Pompe arrêtée : vanne 3 voies sur « rampes » tout de suite (pas de siphon).
            self._commander_voie(rampes=True)
        self.surveiller()

    def _commander_voie(self, rampes: bool) -> None:
        if self.voie_rampes is rampes:
            return
        self._sortie(RAMPES, rampes)
        self.voie_rampes = rampes
        self._voie_depuis = self._horloge()

    def _regler_chauffage(self, voulu: bool) -> None:
        if voulu != self._chauffage:
            self._sortie(CHAUFFAGE, voulu)
            self._chauffage = voulu
            journal.info("Lavage : thermoplongeur %s", "alimenté" if voulu else "coupé")

    @property
    def chauffage(self) -> bool:
        return bool(self._chauffage)

    def surveiller(self) -> bool:
        """Relais du chauffage : fermé seulement fût rempli pour la série, flotteur haut et pompe
        arrêtée ; sinon il attend et informe (journal, `chauffage_attend`). Ce n'est pas la
        sécurité : le flotteur câblé coupe la commande du SSR quoi que fasse le Pi. Rend toujours
        vrai (surveillance du chef)."""
        raison = None
        if self.eau_dans_le_fut:
            if self.pompe:
                raison = "pompe en marche"
            elif self._pause_depuis is not None:
                raison = "pause de Karulium"
            elif not self.flotteur_haut():
                raison = "flotteur pas haut"
        permis = self.eau_dans_le_fut and raison is None
        self._regler_chauffage(permis)
        if raison != self.chauffage_attend:
            self.chauffage_attend = raison
            if raison is not None:
                journal.info("Lavage : chauffage en attente (%s)", raison)
        return True

    def niveau_tenu(self) -> bool:
        """Surveillance : fût rempli, pompe arrêtée, pas de vidange demandée : le flotteur reste
        haut. Sinon fuite ou siphon : vanne à bille fermée, et faux (alarme du chef)."""
        if not self._niveau_haut or self.pompe or self._pause_depuis is not None:
            return True
        if not self.flotteur_bas():
            return True
        self._niveau_haut = False
        journal.error("Lavage : niveau du fût tombé sans vidange (fuite ou siphon)")
        try:
            self._sortie(VIDANGE, False)
            self.vidange_ouverte = False
        except ErreurEtape as erreur:
            journal.error("Lavage : vanne à bille pas fermée : %s", erreur)
        return False

    def air_col(self, ouvert: bool) -> None:
        self._sortie(AIR, ouvert)

    def arrosage_en_marche(self) -> bool:
        return self.pompe and self.voie_rampes is True and self.vidange_ouverte is True

    def couper(self) -> None:
        """Alarme ou arrêt : eau, pompe, rinçage, air et chauffage coupés. Les vannes motorisées
        restent où elles sont."""
        self.pompe = False
        self._figees.clear()
        for nom in A_COUPER:
            try:
                self.signaux.sortie(nom, False)
                self._sorties[nom] = False
            except ErreurEtape as erreur:
                journal.error("Lavage : %s pas coupé(e) : %s", nom, erreur)
        self._chauffage = False
        # Pompe arrêtée : vanne 3 voies sur « rampes » (pas de siphon vers la bonde).
        try:
            self._commander_voie(rampes=True)
        except ErreurEtape as erreur:
            journal.error("Lavage : vanne 3 voies pas remise sur « rampes » : %s", erreur)

    def pauser(self) -> None:
        """Pause de Karulium : eau, pompe, rinçage et air coupés (rallumés à la reprise)."""
        if self._pause_depuis is not None:
            return
        self._pause_depuis = self._horloge()
        self._figees = {nom: actif for nom, actif in self._sorties.items() if actif}
        for nom in self._figees:
            self.signaux.sortie(nom, False)
        self._chauffage = False if CHAUFFAGE in self._figees else self._chauffage

    def reprendre(self) -> None:
        if self._pause_depuis is None:
            return
        self._pause_cumulee += self._horloge() - self._pause_depuis
        self._pause_depuis = None
        for nom in self._figees:
            if nom != CHAUFFAGE:
                self.signaux.sortie(nom, True)
        self._figees.clear()
        self.surveiller()

    # ------------------------------------------------------------ morceaux de gestes

    def _vanne_vidange(self, ouverte: bool) -> Geste:
        if self.vidange_ouverte is ouverte:
            return
        self._sortie(VIDANGE, ouverte)
        yield Pas(
            f"{'ouvrir' if ouverte else 'fermer'} la vanne à bille",
            attente_s=self.reglages.eau.vanne_vidange_s,
        )
        self.vidange_ouverte = ouverte

    def _voie(self, rampes: bool) -> Geste:
        """La vanne 3 voies commandée, puis le temps qu'il lui reste pour tourner."""
        self._commander_voie(rampes)
        reste = self.reglages.eau.vanne_rampes_s - (self._horloge() - self._voie_depuis)
        if reste > 0:
            yield Pas(
                f"vanne 3 voies vers {'les rampes' if rampes else 'la bonde'}", attente_s=reste
            )

    def remplissage_max_s(self) -> float:
        eau = self.reglages.eau
        if self.premier_remplissage_s is None:
            return eau.premier_remplissage_max_s
        return self.premier_remplissage_s * (1 + eau.marge_remplissage)

    # ------------------------------------------------------------ gestes

    def geste_remplir(self) -> Geste:
        """Eau neuve jusqu'au flotteur haut ; le premier temps de remplissage est gardé."""
        if self.pompe:
            self._pompe(False)
        if self._lire_flotteur():
            # Déjà plein (après un redémarrage, ou eau gardée pour la série suivante).
            journal.info("Lavage : fût de lavage déjà plein, pas de remplissage")
            self.eau_dans_le_fut = True
            self._garder()
            yield from self._attendre_flotteur_haut()
            self._niveau_haut = True
            return
        yield from self._vanne_vidange(False)
        self._sortie(EAU, True)
        debut, pause = self._horloge(), self._pause_cumulee
        yield from self._attendre_flotteur_haut()
        self._sortie(EAU, False)
        duree = self._horloge() - debut - (self._pause_cumulee - pause)
        journal.info("Lavage : fût de lavage rempli en %.0f s", duree)
        if self.premier_remplissage_s is None:
            self.premier_remplissage_s = duree
            journal.warning(
                "Lavage : premier remplissage mesuré (%.0f s) : temps maximal désormais %.0f s",
                duree,
                self.remplissage_max_s(),
            )
        self.eau_dans_le_fut = True
        self._niveau_haut = True
        self._garder()
        self.surveiller()

    def _attendre_flotteur_haut(self) -> Geste:
        maximum = self.remplissage_max_s()
        yield Attente(
            "remplissage jusqu'au flotteur haut",
            self.flotteur_haut,
            maximum,
            f"remplissage trop long : flotteur haut pas atteint en {maximum:.0f} s, eau coupée "
            "(elle monterait aux poulies)",
            QUOI_FAIRE_REMPLISSAGE,
        )

    def geste_vider(self) -> Geste:
        """Vidange par la bonde : jusqu'au flotteur bas, puis encore apres_flotteur_s."""
        eau = self.reglages.eau
        self._niveau_haut = False
        self._regler_chauffage(False)
        yield from self._voie(rampes=False)
        yield from self._vanne_vidange(True)
        self._pompe(True)
        yield Attente(
            "vidange jusqu'au flotteur bas",
            self.flotteur_bas,
            eau.vidange_max_s,
            f"vidange trop longue : flotteur toujours haut après {eau.vidange_max_s:.0f} s",
            QUOI_FAIRE_VIDANGE,
        )
        yield Pas("vidange après le flotteur", attente_s=eau.apres_flotteur_s)
        self._pompe(False)
        yield from self._vanne_vidange(False)
        self.eau_dans_le_fut = False
        self._garder()
        journal.info("Lavage : fût de lavage vidé")

    def geste_arroser(self) -> Geste:
        """Le bain recyclé dans les rampes, pour le brossage (jamais à sec). Après un rinçage,
        le niveau est celui où le flotteur retombe : c'est le fût plein de la série."""
        if not self.eau_dans_le_fut:
            raise ErreurEtape(
                "lavage : fût de lavage pas rempli : on ne brosse jamais à sec", QUOI_FAIRE_A_SEC
            )
        yield from self._voie(rampes=True)
        yield from self._vanne_vidange(True)
        self._pompe(True)
        yield Pas("arrosage avant le brossage", attente_s=self.reglages.arrosage_avant_s)

    def arreter_arrosage(self) -> None:
        self._pompe(False)

    def geste_rincer(self) -> Geste:
        """Eau propre dans les rampes, puis la pompe garde le même niveau (flotteur bas), puis
        l'eau du réseau remet le fût au flotteur haut (le bain reste chauffé)."""
        rincage = self.reglages.rincage
        self._sortie(RINCAGE, True)
        yield Pas("rinçage propre", attente_s=rincage.duree_s)
        self._sortie(RINCAGE, False)
        self._niveau_haut = False
        yield from self._voie(rampes=False)
        yield from self._vanne_vidange(True)
        self._pompe(True)
        yield Attente(
            "pompe jusqu'au flotteur bas (même niveau)",
            self.flotteur_bas,
            rincage.vidange_max_s,
            f"après le rinçage, flotteur toujours haut après {rincage.vidange_max_s:.0f} s de "
            "pompe",
            QUOI_FAIRE_VIDANGE,
        )
        self._pompe(False)
        yield from self.geste_remettre_eau()

    def geste_remettre_eau(self) -> Geste:
        """Quelques secondes d'eau du réseau jusqu'au flotteur haut (au plus remise_max_s),
        vanne 3 voies sur « rampes » (la vanne à bille reste ouverte pendant la série)."""
        maximum = self.reglages.rincage.remise_max_s
        yield from self._voie(rampes=True)
        self._sortie(EAU, True)
        yield Attente(
            "eau du réseau jusqu'au flotteur haut (après le rinçage)",
            self.flotteur_haut,
            maximum,
            f"après le rinçage, flotteur haut pas revenu en {maximum:g} s d'eau du réseau, "
            "eau coupée",
            QUOI_FAIRE_REMISE,
        )
        self._sortie(EAU, False)
        self._niveau_haut = True
        self.surveiller()
