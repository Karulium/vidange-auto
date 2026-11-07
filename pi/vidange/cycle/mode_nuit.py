"""La nuit UV-ozone du programme principal (tâche 45 bis) : peut-elle partir, ou pourquoi pas.

    nuit = ModeNuit(reglages, pieces, nettoyage)   # branche son refus au Nettoyage
    nuit.etats                                     # enceinte, ozone, purge : prêt, ou pas lancé
    nuit.refus_poste()                             # None : la nuit peut partir ; sinon pourquoi
    nuit.constats()                                # check-list : postes, nuit en cours ou reprise

La nuit elle-même est le Nettoyage (tâche 38) : conditions de départ (mode « UV-ozone », store
fermé, verrous remis, porte du spray fermée, capteur d'ozone du dedans vivant), génération,
contact, retour sous le seuil, reprise après une coupure. On ne la réécrit pas : on lui ajoute une
raison de refuser (`Nettoyage.refus_nuit_en_plus`), la même règle que pour les autres postes.

Une nuit n'est pas lancée, et l'écran, la check-list et le bouton « NUIT » le disent, quand :
- le Nettoyage n'est pas construit (partie « nettoyage » absente de machine.yaml, entrées/sorties
  en panne) ;
- sur la vraie machine, sa partie de machine.yaml est en EXEMPLE (durées de la nuit, seuils) ;
- un signal de la nuit manque dans la liste des entrées/sorties (ozone, générateur, lampe UV).

Les capteurs de la purge ne bloquent pas la nuit : sans eux, chaque purge finit en alerte et
Karulium passe outre (tâche 38).

Sécurité : la chaîne UV-ozone (reeds du bas du store, porte du spray) est câblée devant le
générateur et la lampe. Ici le Pi informe et attend. Après une coupure en pleine nuit, le Nettoyage
coupe le générateur et attend le retour sous le seuil : il ne le relance JAMAIS seul. Ce programme
ne commande rien.
"""

from vidange.cycle.ordre import ORDRE_NUIT
from vidange.cycle.postes import EtatPoste, PiecesDuPoste, etat_du_poste
from vidange.fiabilite.constats import Constat
from vidange.journal import donner_journal
from vidange.nettoyage.nettoyage import Nettoyage
from vidange.reglages import Reglages

journal = donner_journal("mode_nuit")

SUJET = "nuit UV-ozone"
QUOI_FAIRE = (
    "Régler la partie « nettoyage » de machine.yaml aux essais (procédure "
    "pi/systeme/essai-nettoyage.md), puis passer « exemple » à false ; vérifier les signaux de "
    "l'ozone dans docs/entrees-sorties.yaml."
)
PARTIES: dict[str, tuple[str, ...]] = {
    "enceinte": ("nettoyage",),
    "ozone": ("nettoyage",),
    "purge": ("nettoyage",),
}


class ModeNuit:
    def __init__(
        self, reglages: Reglages, pieces: PiecesDuPoste, nettoyage: Nettoyage | None
    ) -> None:
        self.reglages = reglages
        self.pieces = pieces
        self.nettoyage = nettoyage
        self.etats: dict[str, EtatPoste] = {}
        for poste in ORDRE_NUIT:
            self.etats[poste.nom] = etat_du_poste(poste, reglages, pieces, PARTIES, self.etats)
        for etat in self.etats.values():
            journal.info("Nuit UV-ozone, %s : %s", etat.poste.nom, etat.en_texte())
        if nettoyage is not None:
            nettoyage.refus_nuit_en_plus.append(self.refus_poste)

    def pret(self, nom: str) -> bool:
        return self.etats[nom].pret

    @property
    def postes_lances(self) -> list[str]:
        return [nom for nom, etat in self.etats.items() if etat.pret]

    def manquant(self) -> EtatPoste | None:
        """Le premier poste qui empêche la nuit de partir (le cœur : enceinte, ozone), ou None."""
        for etat in self.etats.values():
            if not etat.pret and etat.poste.coeur:
                return etat
        return None

    def refus_poste(self) -> str | None:
        """None : les postes de la nuit sont prêts ; sinon pourquoi pas. Ne regarde que les
        postes (réglages, matériel) : les conditions du moment (store, ozone...) sont celles du
        Nettoyage."""
        etat = self.manquant()
        if etat is None:
            return None
        return f"poste « {etat.poste.nom} » pas lancé : {etat.raison}"

    def constats(self) -> list[Constat]:
        """Pour la check-list : chaque poste qui manque, la nuit, et sa reprise après une coupure.
        Jamais bloquant : la production n'en dépend pas."""
        constats = [
            Constat(f"{SUJET}, {etat.poste.nom}", "attention", etat.en_texte(), QUOI_FAIRE)
            for etat in self.etats.values()
            if not etat.pret
        ]
        refus = self.refus_poste()
        if refus is None:
            constats.append(Constat(SUJET, "ok", "la nuit UV-ozone peut partir"))
        else:
            constats.append(
                Constat(SUJET, "attention", f"la nuit UV-ozone ne peut pas partir : {refus}")
            )
        if self.nettoyage is not None:
            etat = self.nettoyage.etat()
            if etat.nuit is not None:
                suite = (
                    " (après une coupure, le générateur n'est jamais relancé seul)"
                    if etat.nuit in ("retour", "erreur")
                    else ""
                )
                constats.append(
                    Constat(
                        SUJET,
                        "attention" if etat.nuit == "erreur" else "ok",
                        f"{etat.nuit_libelle.lower()}{suite}",
                    )
                )
        return constats

    def texte_ecran(self) -> tuple[str, str]:
        """Pour l'écran de l'armoire en mode UV-ozone : quel poste manque, et pourquoi."""
        etat = self.manquant()
        if etat is None:
            return "Nuit UV-ozone : prête", ""
        return f"Nuit UV-ozone : {etat.poste.nom} pas prêt", etat.raison

    def en_texte(self) -> str:
        lignes = ["Nuit UV-ozone (le Nettoyage la mène, le Pi informe et attend) :"]
        for etat in self.etats.values():
            lignes.append(f"  {etat.poste.nom:<9} {etat.poste.texte} : {etat.en_texte()}")
        refus = self.refus_poste()
        lignes.append("  nuit : " + ("peut partir" if refus is None else f"impossible ({refus})"))
        return "\n".join(lignes)
