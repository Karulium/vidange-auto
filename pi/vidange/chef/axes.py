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
from vidange.reglages import Machine

journal = donner_journal("chef.axes")

# machine.yaml est en mètres, FluidNC en millimètres.
MM_PAR_M = 1000


class Axes:
    def __init__(self, machine: Machine, liaisons: Mapping[str, Liaison]) -> None:
        self._machine = machine
        self._liaisons = dict(liaisons)
        self._commandes: list[tuple[str, Commande]] = []
        noms = ", ".join(f"« {nom} »" for nom in self._liaisons)
        self.pretes = Condition(f"cartes {noms} connectées et sans alarme", self._cartes_pretes)
        self.surveillance = Condition(
            f"cartes {noms} connectées et sans alarme",
            self._cartes_pretes,
            quoi_faire=(
                "Lire l'alarme de la carte (journal ou vidange-fluidnc), en trouver la cause "
                "sur la machine, débloquer la carte, puis acquitter et donner le Go."
            ),
        )
        self.arrives = Condition("axes arrivés", self.arrive)

    def _cartes_pretes(self) -> bool:
        return all(
            etat.connectee and etat.etat is not None and not etat.en_alarme
            for etat in (liaison.etat for liaison in self._liaisons.values())
        )

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
                raise ErreurEtape(f"carte « {carte} », « {commande.ligne} » : {commande.erreur}")
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
