"""Check-list de démarrage (fonction 12) : tout ce qu'il faut avant de lancer la production.

Elle rassemble les constats de chaque vérification (réglages, entrées/sorties, cartes FluidNC,
chef d'orchestre, registre, santé du Pi, onduleur, chien de garde). Un seul constat
« bloquant » et la production ne doit pas être lancée : `prete()` le dit, avec la liste.

Elle est faite au démarrage du programme (écrite au journal), et sera refaite par l'écran et
la page web avant chaque lancement (tâches 8 et 9). Elle ne remplace pas le tour de la machine
par Karulium, ni la sécurité câblée.
"""

from collections.abc import Callable, Iterable, Mapping

from vidange.chef import Chef
from vidange.entrees_sorties import EntreesSorties
from vidange.fiabilite.constats import Constat, pire, rediger
from vidange.journal import donner_journal
from vidange.materiel import ErreurMateriel, Materiel
from vidange.quoi_faire import CAPTEUR_MUET
from vidange.registre import Registre
from vidange.reglages import Reglages

journal = donner_journal("fiabilite.checklist")

Source = Callable[[], Iterable[Constat]]

QUOI_FAIRE_EXEMPLE = (
    "Remplir les vraies valeurs depuis le projet « Vidange automatique », puis passer "
    "« exemple » à false (ne jamais faire bouger la vraie machine avec des exemples)."
)


class CheckList:
    def __init__(self, sources: Mapping[str, Source]) -> None:
        """`sources` : nom de la vérification → fonction qui rend ses constats."""
        self.sources = dict(sources)

    def verifier(self) -> list[Constat]:
        constats: list[Constat] = []
        for nom, source in self.sources.items():
            try:
                constats.extend(source())
            except Exception as erreur:
                journal.exception("Vérification « %s » impossible", nom)
                constats.append(
                    Constat(
                        nom,
                        "bloquant",
                        f"vérification impossible : {erreur}",
                        "Lire le journal et signaler l'erreur.",
                    )
                )
        return constats

    @staticmethod
    def prete(constats: Iterable[Constat]) -> bool:
        """La production peut être lancée : aucun constat bloquant."""
        return pire(constats) != "bloquant"

    def ecrire_au_journal(self, constats: list[Constat]) -> None:
        bloquants = [c for c in constats if c.niveau == "bloquant"]
        attentions = [c for c in constats if c.niveau == "attention"]
        if not bloquants and not attentions:
            journal.info("Check-list de démarrage : tout est prêt.")
            return
        journal.warning(
            "Check-list de démarrage : %d point(s) bloquant(s), %d à surveiller%s",
            len(bloquants),
            len(attentions),
            " : PAS DE PRODUCTION tant qu'ils ne sont pas réglés." if bloquants else ".",
        )
        for constat in [*bloquants, *attentions]:
            journal.warning("  %s", rediger(constat))


# ---------------------------------------------------------------- les vérifications


def constats_reglages(reglages: Reglages, liste: EntreesSorties) -> list[Constat]:
    """Des réglages d'exemple ne doivent jamais faire bouger la vraie machine."""
    constats = []
    if reglages.machine.exemple:
        constats.append(
            Constat("machine.yaml", "bloquant", "valeurs d'exemple", QUOI_FAIRE_EXEMPLE)
        )
    if reglages.fluidnc.exemple:
        constats.append(
            Constat("fluidnc.yaml", "bloquant", "numéros de série d'exemple", QUOI_FAIRE_EXEMPLE)
        )
    exemples = liste.exemples()
    if exemples:
        constats.append(
            Constat(
                "entrees-sorties.yaml",
                "bloquant",
                f"{len(exemples)} ligne(s) d'exemple",
                QUOI_FAIRE_EXEMPLE,
            )
        )
    if not reglages.machine.lieu_sur:
        constats.append(
            Constat(
                "lieu sûr",
                "attention",
                "machine.yaml n'a pas de « lieu_sur » : pas de retour automatique en lieu sûr",
                "Remplir « lieu_sur » dans machine.yaml avec les modules.",
            )
        )
    if not constats:
        constats.append(Constat("réglages", "ok", "vrais réglages"))
    return constats


def constats_materiel(
    materiel: Materiel | None, erreur_ouverture: str | None, liste: EntreesSorties
) -> list[Constat]:
    """Entrées/sorties ouvertes, chaque entrée lisible, et dans son état « au_demarrage »."""
    if materiel is None:
        return [
            Constat(
                "entrées/sorties",
                "bloquant",
                f"impossibles à ouvrir : {erreur_ouverture}",
                "Vérifier le câblage des cartes d'entrées/sorties et la liste "
                "docs/entrees-sorties.yaml (essai : pi/systeme/essai-entrees-sorties.md).",
            )
        ]
    constats = []
    for nom, valeur in materiel.lire_entrees().items():
        if isinstance(valeur, ErreurMateriel):
            constats.append(Constat(nom, "bloquant", f"illisible : {valeur}", CAPTEUR_MUET))
            continue
        attendu = liste.signaux[nom].au_demarrage
        if attendu is not None and valeur != (attendu == "actionne"):
            description = liste.signaux[nom].description or nom
            etat = "actionné" if valeur else "au repos"
            constats.append(
                Constat(
                    nom,
                    "bloquant",
                    f"{description} : {etat} (attendu : {attendu.replace('actionne', 'actionné')})",
                    "Remettre en état (porte, capteur...) ou vérifier le capteur et son câble.",
                )
            )
    if not constats:
        constats.append(Constat("entrées/sorties", "ok", "toutes lisibles, dans leur état"))
    return constats


def constats_chef(chef: Chef, erreur_reprise: str | None = None) -> list[Constat]:
    """Modules en alarme, cycle interrompu à reprendre, carnet illisible."""
    constats = []
    if erreur_reprise is not None:
        constats.append(
            Constat(
                "reprise du cycle",
                "bloquant",
                erreur_reprise,
                "Le carnet de l'état du cycle ne correspond pas au programme : regarder la "
                "machine, finir ou vider le cycle à la main, puis effacer etat-cycle.json.",
            )
        )
    for module in chef.etat().modules:
        if module.alarme is not None:
            constats.append(
                Constat(
                    f"module « {module.module} »",
                    "bloquant",
                    f"en alarme à l'étape « {module.etape} » : {module.alarme.message}",
                    module.alarme.quoi_faire,
                )
            )
        elif module.statut == "en_cours":
            constats.append(
                Constat(
                    f"module « {module.module} »",
                    "attention",
                    f"en cours, étape {module.numero}/{module.nombre_etapes} « {module.etape} », "
                    f"attend : {module.attend or 'rien'}",
                )
            )
    return constats


def constats_registre(registre: Registre) -> list[Constat]:
    ouvertes = registre.alarmes_ouvertes()
    if not ouvertes:
        return [Constat("alarmes", "ok", "aucune alarme à acquitter")]
    derniere = ouvertes[-1]
    return [
        Constat(
            "alarmes",
            "attention",
            f"{len(ouvertes)} alarme(s) pas encore acquittée(s), la dernière : "
            f"« {derniere['module']} », {derniere['message']}",
            "Lire chaque alarme et son bilan, puis l'acquitter.",
        )
    ]
