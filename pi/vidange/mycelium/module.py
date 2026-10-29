"""Le module « mycelium » du chef d'orchestre : une dose de semence sur chaque couche.

Les étapes se répètent (une couche, la suivante...) : `ensuite` dit laquelle vient après.

    origine_manivelle    prise d'origine de la manivelle (tour lent) si elle n'est pas connue,
                         puis manivelle en haut
    attendre_une_couche  une couche versée et tassée attend son mycélium (Mycelium.demander)
    changer_de_bocal     bocal neuf (1er seau, ou bocal fini) : mors ouverts, bocal posé
                         (Préhension, case vide), serré
    ecarter_le_chariot   le chariot de remplissage s'écarte (y ≥ 0,375)
    aller_doser          demi-tour du bocal tête en bas (manivelle en bas), glissière au dosage,
                         manivelle en bas
    amener_le_seau       le chariot revient avec le seau, plateau à la hauteur du dosage
    agiter               casse du bloc (1re agitation d'un bocal), agitation jusqu'à la dose
    liberer_le_seau      le chariot repart (vers la griffe ou le stockage)
    rentrer              manivelle en haut, demi-tour du bocal debout (manivelle en bas),
                         garage
    fin                  plus de couche à doser (simulateur, essais)

Le Go de Karulium n'est pas demandé : la couche tassée par la griffe suffit à lancer le dosage.
Après une alarme ou une coupure, le chef demande toujours le Go avant de refaire l'étape.
"""

from vidange.chef import Condition, Etape, Module
from vidange.mycelium.mycelium import QUOI_FAIRE, Mycelium

GESTE = "mycelium_geste_max"
CHARIOT = "mycelium_chariot_max"
AGITATION = "mycelium_agitation_max"
QUOI_FAIRE_CHARIOT = (
    "Regarder le chariot de remplissage : est-il bloqué, ou attend-il quelque chose ? Corriger, "
    "puis acquitter et donner le Go."
)


def module_mycelium(mycelium: Mycelium) -> Module:
    agitateur = mycelium.agitateur
    fin = Condition("geste du mycélium fini", mycelium.geste_fini)
    ecarte = Condition("chariot de remplissage écarté (y ≥ 0,375)", mycelium.chariot_ecarte)
    garage = Condition("agitateur au garage, manivelle en haut, bocal debout", mycelium.au_garage)

    def geste(
        nom: str, fabrique, ensuite=None, delai: str = GESTE, entree=(), quoi_faire=QUOI_FAIRE
    ) -> Etape:
        return Etape(
            nom,
            quoi_faire,
            action=lambda: mycelium.lancer(fabrique),
            fin=fin,
            delai_max=delai,
            entree=(agitateur.pretes, *entree),
            ensuite=ensuite,
        )

    def chariot(nom: str, action, condition: Condition, ensuite=None, entree=()) -> Etape:
        return Etape(
            nom,
            QUOI_FAIRE_CHARIOT,
            action=action,
            fin=condition,
            delai_max=CHARIOT,
            entree=entree,
            ensuite=ensuite,
        )

    return Module(
        nom="mycelium",
        etapes=(
            geste("origine_manivelle", mycelium.geste_origine),
            Etape(
                "attendre_une_couche",
                "Le mycélium attend que la griffe ait versé et tassé une couche de substrat.",
                entree=(Condition("une couche attend son mycélium", mycelium.couche_ou_fin),),
                ensuite=mycelium.apres_attente,
            ),
            geste(
                "changer_de_bocal",
                mycelium.geste_changer_de_bocal,
                mycelium.apres_bocal,
                entree=(garage,),
                quoi_faire="Mettre un bocal neuf de la bonne variété dans le porte-bocal, puis "
                "acquitter et donner le Go.",
            ),
            chariot(
                "ecarter_le_chariot",
                mycelium.ecarter_le_chariot,
                ecarte,
                ensuite=mycelium.apres_ecart,
                entree=(garage,),
            ),
            geste("aller_doser", mycelium.geste_aller_doser, entree=(ecarte,)),
            chariot(
                "amener_le_seau",
                mycelium.amener_le_seau,
                Condition(
                    "seau sous le bocal, plateau à la hauteur du dosage", mycelium.seau_au_dosage
                ),
                entree=(
                    Condition(
                        "agitateur au dosage, manivelle en bas, bocal tête en bas",
                        mycelium.pret_pour_le_seau,
                    ),
                ),
            ),
            geste("agiter", mycelium.geste_agiter, mycelium.apres_agitation, AGITATION),
            chariot("liberer_le_seau", mycelium.ecarter_le_chariot, ecarte),
            geste("rentrer", mycelium.geste_rentrer, mycelium.apres_retour, entree=(ecarte,)),
            Etape("fin", "Rien à faire : plus de couche à doser.", ensuite=lambda: None),
        ),
        surveillances=(
            agitateur.surveillance,
            Condition(
                "chariot de remplissage écarté pendant que l'agitateur roule",
                mycelium.surveiller_chariot,
            ),
        ),
        pauser=mycelium.pauser,
        reprendre=mycelium.reprendre,
        arreter=mycelium.arreter,
    )
