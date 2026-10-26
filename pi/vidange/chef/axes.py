"""Les axes de machine.yaml, envoyés à des positions nommées par leurs cartes FluidNC.

    axes = Axes(reglages.machine, {"portique": liaison_portique})
    Etape("aller_au_repos", quoi_faire, action=lambda: axes.aller("repos"),
          fin=axes.arrives, delai_max="deplacement_max", entree=(axes.pretes,))

Le code ne donne que des noms de positions ; les chiffres sont dans machine.yaml.
Un déplacement va à une position absolue : il est rejouable.
"""

from collections.abc import Mapping

from vidange.chef.etapes import Condition, ErreurEtape
from vidange.fluidnc import Commande, ErreurFluidnc, Liaison, protocole
from vidange.journal import donner_journal
from vidange.quoi_faire import CARTE_REDEMARREE, LIGNE_REFUSEE, pour_carte
from vidange.reglages import Machine

journal = donner_journal("chef.axes")

# machine.yaml est en mètres, FluidNC en millimètres.
MM_PAR_M = 1000


class Axes:
    def __init__(self, machine: Machine, liaisons: Mapping[str, Liaison]) -> None:
        self._machine = machine
        self._liaisons = dict(liaisons)
        self._commandes: list[tuple[str, Commande]] = []
        # Redémarrages de chaque carte au moment du dernier envoi (une carte qui redémarre
        # pendant le geste perd sa position).
        self._redemarrages: dict[str, int] = {}
        noms = ", ".join(f"« {nom} »" for nom in self._liaisons)
        self.pretes = Condition(f"cartes {noms} connectées et sans alarme", self._cartes_pretes)
        # Pendant un geste : une carte coupée ou en alarme lève l'alarme du module, avec le
        # « quoi faire » de sa cause exacte (catalogue vidange/quoi_faire.py).
        self.surveillance = Condition(
            f"cartes {noms} connectées et sans alarme", self._surveiller_cartes
        )
        self.arrives = Condition("axes arrivés", self.arrive)

    def _cartes_pretes(self) -> bool:
        return all(
            etat.connectee and etat.etat is not None and not etat.en_alarme
            for etat in (liaison.etat for liaison in self._liaisons.values())
        )

    def _surveiller_cartes(self) -> bool:
        for nom, liaison in self._liaisons.items():
            probleme = pour_carte(liaison.etat)
            if probleme is not None:
                texte, quoi_faire = probleme
                raise ErreurEtape(f"carte « {nom} » : {texte}", quoi_faire)
        return True

    def aller(self, position: str) -> None:
        """Envoie chaque carte concernée vers la position, sans attendre (voir `arrive`)."""
        if position not in self._machine.positions:
            raise ErreurEtape(f"position « {position} » absente de machine.yaml")
        mots: dict[str, list[str]] = {}
        for nom_axe, valeur in self._machine.positions[position].items():
            axe = self._machine.axes[nom_axe]
            if axe.carte is None:
                raise ErreurEtape(f"axe « {nom_axe} » : pas de carte FluidNC dans machine.yaml")
            if axe.carte not in self._liaisons:
                raise ErreurEtape(f"axe « {nom_axe} » : carte « {axe.carte} » pas reliée")
            mots.setdefault(axe.carte, []).append(f"{axe.lettre}{valeur * MM_PAR_M:.3f}")
        self._commandes = []
        for carte, mots_carte in mots.items():
            liaison = self._liaisons[carte]
            self._redemarrages[carte] = liaison.etat.redemarrages
            if (liaison.etat.etat or "").startswith("Hold"):
                # Carte figée par une pause ou une alarme d'avant : on la relance d'abord.
                # Le reste de l'ancien mouvement part avant le nouveau (positions absolues).
                liaison.reprendre()
            for ligne in (f"G90 G0 {' '.join(mots_carte)}", protocole.SYNCHRONISATION):
                self._commandes.append((carte, liaison.envoyer(ligne)))
        journal.debug("Vers « %s » : %s", position, mots)
        # Lève tout de suite si une ligne est refusée (carte non connectée...).
        self.arrive()

    def arrive(self) -> bool:
        """Vrai quand le dernier déplacement est fini ; lève ErreurEtape s'il a échoué."""
        for carte, commande in self._commandes:
            if commande.erreur is not None:
                # La cause exacte (alarme, câble coupé) dit quoi faire ; sinon, ligne refusée.
                etat = self._liaisons[carte].etat
                probleme = pour_carte(etat)
                if etat.redemarrages != self._redemarrages.get(carte, etat.redemarrages):
                    quoi_faire = CARTE_REDEMARREE
                elif probleme is not None:
                    quoi_faire = probleme[1]
                else:
                    quoi_faire = LIGNE_REFUSEE
                raise ErreurEtape(
                    f"carte « {carte} », « {commande.ligne} » : {commande.erreur}", quoi_faire
                )
        return all(commande.finie for _, commande in self._commandes)

    def pauser(self) -> None:
        """Les axes ralentissent et s'arrêtent, sans rien oublier (« ! » de FluidNC)."""
        self._pour_chaque_carte(Liaison.pause)

    def reprendre(self) -> None:
        self._pour_chaque_carte(Liaison.reprendre)

    def _pour_chaque_carte(self, ordre) -> None:
        for nom, liaison in self._liaisons.items():
            try:
                ordre(liaison)
            except ErreurFluidnc as erreur:
                journal.error("Carte « %s » : %s", nom, erreur)
