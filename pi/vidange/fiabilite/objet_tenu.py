"""Reprise après une coupure avec un objet encore tenu à la ventouse (tâches 45 nonies et 45
decies).

    vannes = VannesAuDemarrage(fluidnc, liaisons, liste, presence, vraie_machine, attente_s)
    objet_tenu = ObjetTenu(vide, lire=lambda: materiel.mesurer("vide_venturi"))
    vannes.fermer()                     # au démarrage, liaisons lancées, AVANT tout mouvement
    objet_tenu.regarder()               # puis le vide est lu
    chef.empecher_go(objet_tenu.refus_go)
    objet_tenu.demarrer(arret)          # relu jusqu'à ce que l'objet soit enlevé à la main
    objet_tenu.constats()               # pour la check-list

Réponse du fil Préhension (07/11/2026) : les électrovannes « aspirer » et « souffler » sont
normalement fermées et un clapet anti-retour garde le vide. À une coupure, l'objet tenu à la
ventouse (seau, couvercle, Pétri) reste d'abord tenu, puis peut tomber au bout d'un temps inconnu
(sous la face 0,545, un couvercle C tomberait de travers sur le seau). Un objet tenu par les
électroaimants (capsule, bocal par son couvercle percé) tombe tout de suite.

Au démarrage, avant tout mouvement, le Pi lit le capteur de vide de la préhension : la moyenne de
`zero_lectures` lectures brutes (le zéro n'est pas encore recalé : il ne l'est qu'au départ d'un
lot, vanne fermée, et il est à ± `zero_ecart_max_kpa` de 0). Plus bas que
`prehension → vide → tenu_au_demarrage_kpa` (−20 kPa), quelque chose est encore tenu : l'écran et
la page disent « objet encore tenu », et le chef refuse TOUT Go (retour en lieu sûr, reprise du
cycle, lot) ainsi que le pilotage à distance, tant que c'est le cas. Le capteur est relu tous les
`fiabilite → objet_tenu → periode_s` ; dès que le vide est remonté au-dessus du seuil (Karulium a
enlevé l'objet à la main), l'attente est finie pour toute cette marche du programme : ensuite, la
ventouse tient des objets en travail, ce n'est plus une reprise.

Les vannes au démarrage (fil Préhension, 07/11/2026, tâche 45 decies) : après un plantage du Pi,
« aspirer » peut rester ouverte (rien de matériel ne la coupe ; pas dangereux : le venturi souffle,
l'objet reste tenu). Au démarrage, le Pi FERME donc les deux vannes, « aspirer » et « souffler »
(sans risque : le clapet anti-retour garde le vide), puis il lit le vide. C'est la seule exception
écrite à la règle « rien n'est commandé au démarrage » : seulement ces deux fermetures (« M65 »),
une fois, avant tout mouvement. JAMAIS ouvrir « souffler », jamais de mouvement automatique. Une
vanne qui ne peut pas être fermée (carte absente, muette, en alarme, ligne en EXEMPLE sur la vraie
machine) : rien n'attend, la check-list le dit (elle est refermée au premier départ de la tête de
préhension, avec le lot). Sans capteur de vide (signal absent de la liste, ligne en EXEMPLE sur la
vraie machine, entrées/sorties pas ouvertes) ou s'il ne répond pas, le Pi ne peut pas savoir : il
n'attend pas, mais la check-list le dit (« vérifier la tête à la main avant le Go »).

Cette attente protège la machine et le seau, jamais les personnes : la sécurité est câblée.
"""

import threading
from collections.abc import Callable, Mapping
from statistics import fmean

from vidange.entrees_sorties import EntreesSorties
from vidange.fiabilite.constats import Constat, lancer_boucle
from vidange.fluidnc import ErreurFluidnc, Liaison
from vidange.journal import donner_journal
from vidange.reglages import CarteFluidnc, Fluidnc, VidePrehension

journal = donner_journal("fiabilite.objet_tenu")

SUJET = "objet tenu à la ventouse"
QUOI_FAIRE = (
    "Vérifier la tête de préhension et le seau : enlever à la main l'objet encore tenu ou tombé "
    "(décoller un bord de la ventouse pour laisser entrer l'air). Le Go revient seul dès que le "
    "vide est remonté."
)
QUOI_FAIRE_INCONNU = (
    "Le Pi ne sait pas si la ventouse tient encore quelque chose : vérifier la tête de préhension "
    "et le seau, et enlever à la main l'objet tenu ou tombé avant le Go."
)


class ObjetTenu:
    def __init__(
        self,
        reglages: VidePrehension,
        lire: Callable[[], float] | None,
        periode_s: float,
        absent: str | None = None,
    ) -> None:
        """`lire` : une lecture brute du capteur de vide (kPa) ; None avec `absent` (pourquoi il
        n'est pas lu)."""
        self.seuil_kpa = reglages.tenu_au_demarrage_kpa
        self.lectures = reglages.zero_lectures
        self.periode_s = periode_s
        self._lire = lire
        self._verrou = threading.Lock()
        # Pourquoi le capteur n'est pas lu (None : il l'est).
        self.inconnu: str | None = None if lire is not None else (absent or "pas de capteur")
        # Dernière moyenne lue (kPa, brute), ou None.
        self.vide_kpa: float | None = None
        # Plus rien à attendre : vide remonté au-dessus du seuil, ou capteur pas lisible.
        self.libere = lire is None

    @property
    def tenu(self) -> bool:
        """Un objet est encore tenu (vu au redémarrage, pas encore enlevé)."""
        return not self.libere and self.vide_kpa is not None and self.vide_kpa < self.seuil_kpa

    def regarder(self) -> None:
        """Une mesure (moyenne de `lectures` lectures brutes). Ne commande rien."""
        if self.libere or self._lire is None:
            return
        try:
            vide = fmean(self._lire() for _ in range(self.lectures))
        except Exception as erreur:
            with self._verrou:
                self.inconnu = f"capteur de vide illisible ({erreur})"
                self.libere = True
            journal.error(
                "Reprise : capteur de vide illisible (%s) ; vérifier la tête à la main", erreur
            )
            return
        with self._verrou:
            avant = self.vide_kpa
            self.vide_kpa = vide
            if vide < self.seuil_kpa:
                if avant is None:
                    journal.warning(
                        "Reprise : objet encore tenu à la ventouse (vide %.1f kPa, plus bas que "
                        "%g) : pas de Go tant qu'il n'est pas enlevé à la main",
                        vide,
                        self.seuil_kpa,
                    )
                return
            self.libere = True
        if avant is not None:
            journal.info(
                "Reprise : la ventouse ne tient plus rien (vide %.1f kPa) : Go permis", vide
            )

    def demarrer(self, arret: threading.Event) -> threading.Thread:
        return lancer_boucle("objet_tenu", self.periode_s, self._tour, arret)

    def _tour(self) -> None:
        if not self.libere:
            self.regarder()

    def refus_go(self) -> str | None:
        """Pourquoi aucun Go n'est accepté (objet encore tenu), ou None. Rapide : la dernière
        mesure, sans lire le capteur."""
        with self._verrou:
            if not self.tenu:
                return None
            vide = self.vide_kpa
        assert vide is not None
        return f"objet encore tenu à la ventouse (vide {vide:.0f} kPa) : l'enlever à la main"

    def constats(self) -> list[Constat]:
        refus = self.refus_go()
        if refus is not None:
            return [Constat(SUJET, "bloquant", refus, QUOI_FAIRE)]
        if self.inconnu is not None:
            return [Constat(SUJET, "attention", self.inconnu, QUOI_FAIRE_INCONNU)]
        return [Constat(SUJET, "ok", "rien de tenu au redémarrage (ou enlevé à la main)")]


# Les vannes de la ventouse (fil Préhension, 07/11/2026), par leur nom dans fluidnc.yaml et
# docs/entrees-sorties.yaml : « aspirer » (vanne_vide) et « souffler » (vanne_souffler, qui n'est
# pas encore dans le câblage du dépôt : elle sera fermée elle aussi le jour où elle y sera).
VANNES = ("vanne_vide", "vanne_souffler")
SUJET_VANNES = "vannes de la ventouse"
QUOI_FAIRE_VANNES = (
    "La vanne « aspirer » a pu rester ouverte après un plantage du Pi (pas dangereux : le venturi "
    "souffle, l'objet reste tenu). Le Pi la referme au premier départ de la tête de préhension. "
    "Vérifier la carte de la préhension (câble USB, alarme) ; ne jamais ouvrir « souffler » "
    "pour lâcher un objet à la reprise : l'enlever à la main."
)


class VannesAuDemarrage:
    """La seule commande permise au démarrage (tâche 45 decies) : FERMER les vannes de la
    ventouse (« M65 » sur la carte FluidNC qui les porte), une fois, liaisons lancées, avant la
    lecture du vide et tout mouvement. Rien n'est jamais ouvert. Ne lève jamais : ce qui n'a pas
    pu être fermé, et pourquoi, va dans la check-list."""

    def __init__(
        self,
        fluidnc: Fluidnc,
        liaisons: Mapping[str, Liaison],
        liste: EntreesSorties,
        presence: Callable[[str], str | None],
        vraie_machine: bool,
        attente_s: float,
    ) -> None:
        self.fluidnc = fluidnc
        self.liaisons = liaisons
        self.liste = liste
        self.presence = presence
        self.vraie_machine = vraie_machine
        self.attente_s = attente_s
        # Les vannes fermées, et ce qui n'a pas pu l'être (une ligne par carte ou par vanne).
        self.fermees: list[str] = []
        self.problemes: list[str] = []
        self.faite = False

    def fermer(self) -> None:
        """Ferme chaque vanne de la ventouse déclarée dans fluidnc.yaml. Une seule fois : elle
        attend au plus `attente_s` que la carte se connecte, puis sa réponse à chaque ordre."""
        if self.faite:
            return
        self.faite = True
        for nom, carte in self.fluidnc.cartes.items():
            vannes = [vanne for vanne in VANNES if vanne in carte.sorties]
            if not vannes:
                continue
            raison = self._pourquoi_pas(nom, vannes)
            if raison is not None:
                self._noter(f"{', '.join(vannes)} pas fermée(s) : {raison}")
                continue
            self._fermer_sur(nom, carte, vannes)
        if self.fermees:
            journal.info(
                "Démarrage : vannes de la ventouse fermées (%s) ; rien d'autre n'est commandé",
                ", ".join(self.fermees),
            )

    def _pourquoi_pas(self, nom: str, vannes: list[str]) -> str | None:
        if nom not in self.liaisons:
            return f"carte FluidNC « {nom} » sans liaison"
        if self.vraie_machine and self.fluidnc.exemple:
            return f"fluidnc.yaml en EXEMPLE (carte « {nom} ») : interdit sur la vraie machine"
        if self.vraie_machine:
            for vanne in vannes:
                signal = self.liste.signaux.get(vanne)
                lignes = [signal, self.liste.cartes.get(signal.carte) if signal else None]
                if signal is None or any(ligne is not None and ligne.exemple for ligne in lignes):
                    return (
                        f"« {vanne} » absente ou en EXEMPLE dans docs/entrees-sorties.yaml : "
                        "interdit sur la vraie machine"
                    )
        return self.presence(nom)

    def _fermer_sur(self, nom: str, carte: CarteFluidnc, vannes: list[str]) -> None:
        liaison = self.liaisons[nom]
        try:
            liaison.attendre(lambda etat: etat.connectee, self.attente_s)
        except ErreurFluidnc:
            self._noter(
                f"{', '.join(vannes)} pas fermée(s) : carte « {nom} » pas connectée en "
                f"{self.attente_s:g} s"
            )
            return
        for vanne in vannes:
            # Fermer seulement (M65 = sortie coupée) : jamais M64 ici.
            commande = liaison.envoyer(f"M65 P{carte.sorties[vanne]}")
            try:
                commande.attendre(self.attente_s)
            except ErreurFluidnc as erreur:
                self._noter(f"{vanne} pas fermée (carte « {nom} ») : {erreur}")
                continue
            self.fermees.append(vanne)

    def _noter(self, probleme: str) -> None:
        self.problemes.append(probleme)
        journal.warning("Démarrage : %s", probleme)

    def constats(self) -> list[Constat]:
        if self.problemes:
            return [
                Constat(SUJET_VANNES, "attention", " ; ".join(self.problemes), QUOI_FAIRE_VANNES)
            ]
        if self.fermees:
            texte = f"fermées au démarrage ({', '.join(self.fermees)})"
            return [Constat(SUJET_VANNES, "ok", texte)]
        if not self.faite:
            return [Constat(SUJET_VANNES, "inconnu", "pas encore fermées (démarrage en cours)")]
        return [Constat(SUJET_VANNES, "inconnu", "aucune vanne de la ventouse dans fluidnc.yaml")]
