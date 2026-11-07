"""Les modules « spray » et « nettoyage_tubes » du chef d'orchestre (fiche v5.8, gestes a et b).

Un seau (a), au poste (y 0,135), pendant l'aller-retour de la griffe :

    origine_du_bras     carte qui répond ; prise d'origine du bras si elle n'est pas faite
                        (bras vers « rangé » jusqu'au capteur : 0°)
    preparer_la_dose    seau au poste, format connu : emplacement, dose, réserve du flacon ;
                        agitateurs avant la dose (agitateurs → avant_dose_s)
    sortir_le_bras      griffe partie, tête du micropore escamotée, permission du chef (pas de
                        purge), règle 6 (plateau ≤ min(0,50 ; 0,68 − h), barres à plus de 0,50
                        d'entraxe) : le bras pivote à l'angle du format
    pulveriser          air, dose jusqu'au poids perdu, chasse ; le seau tourne (≈ 200°)
    ranger_le_bras      « ranger » ; attendu jusqu'à ce que la carte voie le bras rangé (un seul
                        nouvel essai automatique)
    noter               registre du seau : emplacement, dose, poids perdu, amorce, durée

Nettoyage des tubes (b), en fin de journée, un seau vide au poste :

    attendre            fin de la production, ozone arrêté, seau vide au poste
    sortir_le_bras      mêmes règles que pour un seau
    nettoyer            alcool par la petite pompe, chasse de séchage
    ranger_le_bras      comme pour un seau ; le seau (avec l'alcool) part comme un seau sale
    compter             nettoyages depuis le dernier plein d'alcool (alerte avant qu'il soit vide)

Une erreur avant la sortie du bras (carte muette, balance, flacon, cartouche à confirmer) met le
module en alarme : l'écran propose « Sans spray » (Spray.continuer_sans_spray, puis acquitter et
Go : le seau est noté sans spray) ou d'attendre. Une dose incomplète, trop forte ou interrompue
est notée et alertée sans arrêter. Bras pas rangé : alarme forte, le chariot reste immobile.
"""

from collections.abc import Callable
from dataclasses import replace

from vidange.chef import Condition, Etape, Module
from vidange.spray.spray import GESTE, QUOI_FAIRE, QUOI_FAIRE_BRAS, QUOI_FAIRE_CARTE, Spray

BRAS = "spray_bras_max"
DOSE = "spray_dose_max"
NETTOYAGE = "spray_nettoyage_max"
PREPARATION = "spray_preparation_max"


def _etapes_du_bras(
    spray: Spray,
    format: Callable[[], str | None],
    entree: tuple[Condition, ...],
) -> tuple[Etape, Etape]:
    sortir = Etape(
        "sortir_le_bras",
        QUOI_FAIRE,
        action=lambda: spray.sortir(format()),
        fin=Condition("bras du spray sorti à l'angle du format", spray.bras_sorti),
        delai_max=BRAS,
        entree=(
            *entree,
            Condition(
                "bras du spray : carte prête, bras rangé, porte fermée, pas de purge, plateau "
                "assez bas et barres ouvertes (règle 6)",
                lambda: spray.refus_sortie() is None,
            ),
        ),
    )
    ranger = Etape(
        "ranger_le_bras",
        QUOI_FAIRE_BRAS,
        action=spray.ranger,
        fin=Condition("bras du spray vu rangé par la carte", spray.bras_range),
        delai_max=BRAS,
    )
    return sortir, ranger


def _origine_si_besoin(spray: Spray) -> None:
    """Prise d'origine si elle n'est pas faite, si le bras a une erreur ou s'il n'est pas vu
    rangé (l'origine le ramène au capteur)."""
    if spray.refus_carte() is not None or spray.bras_spray_sorti():
        spray.lancer_origine()


def module_spray(
    spray: Spray,
    seau_au_poste: Callable[[], tuple[str | None, str] | None],
    griffe_partie: Callable[[], bool] = lambda: False,
    micropore_escamote: Callable[[], bool | None] = lambda: None,
    nom: str = "spray",
) -> Module:
    """Un seau. `seau_au_poste()` : (code du seau, format) quand le seau est au poste, QR lu
    (sinon None). `griffe_partie`, `micropore_escamote` : cases vides des modules voisins
    (valeurs prudentes par défaut : le bras ne sort pas)."""
    choisi: dict[str, tuple[str | None, str]] = {}

    def preparer() -> None:
        seau = seau_au_poste()
        assert seau is not None
        choisi["seau"] = seau
        spray.preparer(*seau)

    def apres_preparation() -> str | None:
        # « Sans spray » : directement au registre.
        return "noter" if spray.dose is None else None

    sortir, ranger = _etapes_du_bras(
        spray,
        lambda: choisi["seau"][1] if "seau" in choisi else None,
        (
            Condition("griffe partie du poste", griffe_partie),
            Condition("tête du micropore escamotée", lambda: micropore_escamote() is True),
        ),
    )
    return Module(
        nom,
        (
            Etape(
                "origine_du_bras",
                QUOI_FAIRE_BRAS,
                action=lambda: _origine_si_besoin(spray),
                fin=Condition("prise d'origine du bras du spray faite", spray.origine_faite),
                delai_max=BRAS,
                entree=(
                    Condition("carte du spray qui répond", spray.carte_repond, QUOI_FAIRE_CARTE),
                ),
            ),
            Etape(
                "preparer_la_dose",
                QUOI_FAIRE,
                action=preparer,
                fin=Condition(
                    "agitateurs des flacons en marche avant la dose", spray.agitation_faite
                ),
                delai_max=PREPARATION,
                entree=(
                    Condition("seau au poste, format connu", lambda: seau_au_poste() is not None),
                ),
                ensuite=apres_preparation,
            ),
            sortir,
            Etape(
                "pulveriser",
                QUOI_FAIRE,
                action=spray.pulveriser,
                fin=Condition("dose du spray finie (chasse comprise)", spray.pulverisation_finie),
                delai_max=DOSE,
            ),
            ranger,
            Etape("noter", QUOI_FAIRE, action=spray.noter),
        ),
        arreter=spray.arreter,
    )


def etapes_du_spray(
    spray: Spray,
    seau_au_poste: Callable[[], tuple[str | None, str] | None],
    griffe_partie: Callable[[], bool],
    micropore_escamote: Callable[[], bool | None],
    prefixe: str = "spray_",
) -> tuple[Etape, ...]:
    """Les étapes du module « spray », nommées `prefixe` + nom, pour les mettre dans un autre
    module (le remplissage du mode seaux : une fois par seau, seau vide au poste, tâche 45)."""
    module = module_spray(spray, seau_au_poste, griffe_partie, micropore_escamote)

    def renommee(etape: Etape) -> Etape:
        ensuite = etape.ensuite
        if ensuite is None:
            return replace(etape, nom=prefixe + etape.nom)

        def suivante() -> str | None:
            nom = ensuite()
            return None if nom is None else prefixe + nom

        return replace(etape, nom=prefixe + etape.nom, ensuite=suivante)

    return tuple(renommee(etape) for etape in module.etapes)


def module_nettoyage_tubes(
    spray: Spray,
    fin_de_production: Callable[[], bool],
    ozone_arrete: Callable[[], bool],
    seau_vide_au_poste: Callable[[], str | None],
    nom: str = "nettoyage_tubes",
) -> Module:
    """Le nettoyage des tubes (b). `seau_vide_au_poste()` : le format du seau vide au poste,
    ou None."""
    sortir, ranger = _etapes_du_bras(spray, seau_vide_au_poste, ())
    return Module(
        nom,
        (
            Etape(
                "attendre",
                QUOI_FAIRE,
                entree=(
                    Condition("fin de la production", fin_de_production),
                    Condition("ozone arrêté", ozone_arrete),
                    Condition("seau vide au poste", lambda: seau_vide_au_poste() is not None),
                    Condition("carte du spray prête", lambda: spray.refus_carte() is None),
                ),
            ),
            sortir,
            Etape(
                "nettoyer",
                QUOI_FAIRE,
                action=spray.nettoyer,
                fin=Condition("nettoyage des tubes fini", spray.nettoyage_fini),
                delai_max=NETTOYAGE,
            ),
            ranger,
            Etape("compter", QUOI_FAIRE, action=lambda: None),
        ),
        arreter=spray.arreter,
    )


__all__ = ["GESTE", "etapes_du_spray", "module_nettoyage_tubes", "module_spray"]
