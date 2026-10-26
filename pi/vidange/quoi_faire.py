"""Catalogue des « quoi faire » : pour chaque alarme connue, ce que Karulium doit faire.

Un seul fichier, pour qu'on puisse les relire et les améliorer d'un coup (fonction 18).
Une étape d'un module a aussi son propre « quoi faire » (celui de l'étape) : il sert quand
l'alarme vient du geste lui-même (délai dépassé, condition pas tenue). Ceux d'ici servent
quand on connaît la cause exacte : alarme d'une carte FluidNC, câble coupé, capteur muet...

Rappel : la sécurité des personnes est câblée. Ces textes aident à remettre la machine
en route ; ils ne remplacent pas l'arrêt d'urgence.
"""

from vidange.fluidnc.liaison import EtatCarte
from vidange.fluidnc.ports import ErreurFluidnc
from vidange.fluidnc.protocole import decrire_alarme
from vidange.materiel.puces import ErreurMateriel

PRISE_ORIGINE = "lancer « lieu sûr » depuis l'écran (prise d'origine des axes)"

_PRISE_ORIGINE_RATEE = (
    "La prise d'origine a échoué : vérifier le fin de course de l'axe (câble, voyant, saleté) "
    "et que rien ne bloque l'axe, débloquer la carte, puis relancer « lieu sûr »."
)

# Alarmes des cartes FluidNC (numéros de protocole.ALARMES) → quoi faire.
ALARMES_FLUIDNC: dict[int, str] = {
    1: (
        "Un axe a touché un fin de course : chercher pourquoi (obstacle, axe qui a glissé, "
        "position mal réglée). Dégager l'axe sans desserrer le frein d'un axe vertical, "
        "débloquer la carte, " + PRISE_ORIGINE + ", puis acquitter."
    ),
    2: (
        "Le programme a demandé une position hors de la course permise : erreur de réglage "
        "(machine.yaml ou réglages FluidNC). Noter l'étape et le message, faire corriger "
        "le réglage ; débloquer la carte, puis acquitter."
    ),
    3: (
        "La carte a été réinitialisée pendant un mouvement : elle ne sait plus où sont ses axes. "
        "Débloquer la carte, " + PRISE_ORIGINE + ", puis acquitter."
    ),
    4: "Palpeur déjà touché au départ : vérifier le palpeur et son câble, puis acquitter.",
    5: "Le palpeur n'a rien touché : vérifier la pièce, le palpeur et son câble, puis acquitter.",
    6: _PRISE_ORIGINE_RATEE,
    7: _PRISE_ORIGINE_RATEE,
    8: _PRISE_ORIGINE_RATEE,
    9: _PRISE_ORIGINE_RATEE,
    10: "Commande de moteur d'outil en défaut : vérifier le pilote et son câble.",
    11: (
        "Une entrée de commande de la carte (pause, arrêt, porte) est active à son démarrage : "
        "vérifier le bouton ou le capteur et son câble, puis débloquer la carte."
    ),
    12: _PRISE_ORIGINE_RATEE,
    13: (
        "Arrêt dur de la carte (arrêt d'urgence, défaut d'un pilote) : remettre la sécurité "
        "en état, regarder le voyant des pilotes, débloquer la carte, " + PRISE_ORIGINE + "."
    ),
    14: (
        "La carte ne connaît pas la position de ses axes (mise sous tension) : "
        + PRISE_ORIGINE
        + "."
    ),
    15: (
        "La carte a une erreur à son démarrage : lire son message (commande vidange-fluidnc), "
        "vérifier son fichier de réglages, puis la redémarrer."
    ),
    16: "Une carte d'extension a redémarré : vérifier son alimentation et ses câbles.",
}

ALARME_INCONNUE = (
    "Alarme inconnue de la carte : chercher son numéro dans la documentation FluidNC, "
    "débloquer la carte quand la cause est comprise, puis acquitter."
)

CARTE_COUPEE = (
    "La liaison USB avec la carte est coupée : vérifier son câble USB et son alimentation. "
    "Elle se reconnecte seule. Si elle a redémarré, " + PRISE_ORIGINE + ". Puis acquitter."
)

CARTE_REDEMARREE = (
    "La carte a redémarré toute seule (alimentation, parasite, câble USB) : vérifier son "
    "alimentation et ses câbles, " + PRISE_ORIGINE + ", puis acquitter."
)

LIGNE_REFUSEE = (
    "La carte a refusé un ordre : erreur du programme ou d'un réglage. Noter le message et "
    "l'étape, faire corriger ; débloquer la carte si elle est en alarme, puis acquitter."
)

CAPTEUR_MUET = (
    "Un capteur ou une carte d'entrées/sorties ne répond pas (son nom est dans le message) : "
    "vérifier son câble et son alimentation, puis acquitter."
)

ERREUR_PROGRAMME = (
    "Erreur imprévue du programme : noter le message (il est aussi dans le journal) et "
    "le signaler pour correction. Vérifier la machine, puis acquitter."
)

COUPURE_COURANT = (
    "Le Pi s'est arrêté net (coupure de courant ?) en plein cycle. Regarder la machine "
    "(seau en cours, axes), " + PRISE_ORIGINE + ", puis donner le Go pour reprendre."
)

PLANTAGE = (
    "Le programme du Pi a planté puis a été relancé. Regarder la machine et le journal, "
    "puis donner le Go pour reprendre ; signaler le plantage pour correction."
)


def alarme_fluidnc(numero: int) -> str:
    return ALARMES_FLUIDNC.get(numero, ALARME_INCONNUE)


def pour_carte(etat: EtatCarte) -> tuple[str, str] | None:
    """Ce qui ne va pas sur une carte FluidNC (ce qu'on voit, quoi faire), ou None si elle va bien.

    Sans le nom de la carte : « pas connectée », « alarme 1 : fin de course matérielle touchée ».
    """
    if not etat.connectee:
        return "pas connectée", CARTE_COUPEE
    if etat.en_alarme:
        if etat.alarme is None:
            return "en alarme", alarme_fluidnc(14)
        return decrire_alarme(etat.alarme), alarme_fluidnc(etat.alarme)
    return None


def pour_erreur(erreur: Exception) -> str | None:
    """Le quoi faire d'une erreur imprévue d'une étape, si on en connaît la sorte."""
    if isinstance(erreur, ErreurMateriel):
        return CAPTEUR_MUET
    if isinstance(erreur, ErreurFluidnc):
        return CARTE_COUPEE
    return None
