"""Tests du chef d'orchestre, avec une horloge imaginaire (on avance le temps à la main)."""

import json

import pytest

from vidange.chef import Carnet, Chef, Condition, ErreurChef, ErreurEtape, Etape, Module
from vidange.reglages import Machine, ReglagesChef

QUOI = "Regarder, corriger, acquitter, donner le Go."


class Horloge:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


class Banc:
    """Des drapeaux que les conditions lisent, et le compte des actions et des appels."""

    def __init__(self) -> None:
        self.drapeaux: dict[str, bool] = {}
        self.appels: list[str] = []

    def condition(self, nom: str, quoi_faire: str = "") -> Condition:
        return Condition(nom, lambda: self.drapeaux.get(nom, False), quoi_faire)

    def action(self, nom: str):
        return lambda: self.appels.append(nom)


def machine() -> Machine:
    return Machine.model_validate(
        {
            "axes": {"x": {"longueur_rail": 2, "course": [0, 2]}},
            "zones": {"zone_a": {"x": [0, 1]}, "zone_b": {"x": [1, 2]}},
            "durees": {"court": 10, "attente": 5},
        }
    )


def nouveau_chef(horloge, carnet=None, pause_tout=True) -> Chef:
    reglages = ReglagesChef(periode_s=0.01, alarme_pause_tout=pause_tout)
    return Chef(machine(), reglages, carnet, horloge=horloge)


def module_simple(banc: Banc, nom: str = "essai", **options) -> Module:
    """Deux étapes : « un » attend « pret », « deux » demande le Go ; chacune attend sa fin."""
    return Module(
        nom=nom,
        etapes=(
            Etape(
                "un",
                QUOI,
                action=banc.action(f"{nom}.un"),
                fin=banc.condition(f"{nom}.un_fini"),
                delai_max="court",
                entree=(banc.condition("pret"),),
                **options.pop("un", {}),
            ),
            Etape(
                "deux",
                QUOI,
                action=banc.action(f"{nom}.deux"),
                fin=banc.condition(f"{nom}.deux_fini"),
                delai_max="court",
                demande_go=True,
                **options.pop("deux", {}),
            ),
        ),
        pauser=banc.action(f"{nom}.pauser"),
        reprendre=banc.action(f"{nom}.reprendre"),
        arreter=banc.action(f"{nom}.arreter"),
        **options,
    )


@pytest.fixture
def horloge() -> Horloge:
    return Horloge()


@pytest.fixture
def banc() -> Banc:
    return Banc()


def tour(chef: Chef, horloge: Horloge, secondes: float = 0.1) -> None:
    horloge.t += secondes
    chef.avancer()


def etat_de(chef: Chef, nom: str = "essai"):
    return next(module for module in chef.etat().modules if module.module == nom)


# ---------------------------------------------------------------- déroulement


def test_cycle_complet(horloge, banc):
    chef = nouveau_chef(horloge)
    chef.lancer(module_simple(banc))
    tour(chef, horloge)
    assert etat_de(chef).attend == "pret"
    assert banc.appels == []

    banc.drapeaux["pret"] = True
    tour(chef, horloge)
    assert banc.appels == ["essai.un"]
    assert etat_de(chef).phase == "fin"
    assert etat_de(chef).attend == "essai.un_fini"
    tour(chef, horloge)
    assert banc.appels == ["essai.un"]  # l'action n'est lancée qu'une fois

    banc.drapeaux["essai.un_fini"] = True
    tour(chef, horloge)
    tour(chef, horloge)
    etat = etat_de(chef)
    assert (etat.etape, etat.numero, etat.nombre_etapes) == ("deux", 2, 2)
    assert etat.attend == "Go de Karulium"
    assert chef.etat().attendent_go == ["essai"]
    assert banc.appels == ["essai.un"]

    chef.donner_go("essai")
    tour(chef, horloge)
    assert banc.appels == ["essai.un", "essai.deux"]
    banc.drapeaux["essai.deux_fini"] = True
    tour(chef, horloge)
    assert etat_de(chef).statut == "fini"


def test_go_refuse_si_pas_attendu(horloge, banc):
    chef = nouveau_chef(horloge)
    chef.lancer(module_simple(banc))
    with pytest.raises(ErreurChef, match="n'attend pas de Go"):
        chef.donner_go("essai")
    with pytest.raises(ErreurChef, match="pas lancé"):
        chef.donner_go("autre")


def test_un_module_ne_se_lance_pas_deux_fois(horloge, banc):
    chef = nouveau_chef(horloge)
    chef.lancer(module_simple(banc))
    with pytest.raises(ErreurChef, match="déjà en route"):
        chef.lancer(module_simple(banc))


def test_etape_sans_fin_ni_action(horloge, banc):
    chef = nouveau_chef(horloge)
    chef.lancer(Module("attente", (Etape("attendre", QUOI, entree=(banc.condition("pret"),)),)))
    tour(chef, horloge)
    assert etat_de(chef, "attente").statut == "en_cours"
    banc.drapeaux["pret"] = True
    tour(chef, horloge)
    assert etat_de(chef, "attente").statut == "fini"


# ---------------------------------------------------------------- vérifications


def test_module_mal_decrit():
    with pytest.raises(ErreurChef, match="demande un délai_max"):
        Module("m", (Etape("e", QUOI, fin=Condition("x", lambda: True)),))
    with pytest.raises(ErreurChef, match="écrite deux fois"):
        Module("m", (Etape("e", QUOI), Etape("e", QUOI)))
    with pytest.raises(ErreurChef, match="quoi faire"):
        Module("m", (Etape("e", " "),))
    with pytest.raises(ErreurChef, match="minuscules"):
        Module("Module", (Etape("e", QUOI),))


def test_delai_et_zone_inconnus_refuses_au_lancement(horloge):
    module = Module(
        "m",
        (
            Etape("e", QUOI, fin=Condition("x", lambda: True), delai_max="inconnu"),
            Etape("f", QUOI, reserver=("zone_z",)),
        ),
    )
    with pytest.raises(ErreurChef) as erreur:
        nouveau_chef(horloge).lancer(module)
    assert "délai « inconnu » absent de machine.yaml" in str(erreur.value)
    assert "zone « zone_z » absente de machine.yaml" in str(erreur.value)


# ---------------------------------------------------------------- alarmes


def test_delai_depasse_donne_une_alarme(horloge, banc):
    chef = nouveau_chef(horloge)
    banc.drapeaux["pret"] = True
    chef.lancer(module_simple(banc))
    tour(chef, horloge)
    tour(chef, horloge, 9)
    assert etat_de(chef).statut == "en_cours"
    tour(chef, horloge, 2)
    etat = etat_de(chef)
    assert etat.statut == "alarme"
    assert etat.alarme.etape == "un"
    assert "trop long (10 s)" in etat.alarme.message
    assert "essai.un_fini" in etat.alarme.message
    assert etat.alarme.quoi_faire == QUOI
    assert "essai.arreter" in banc.appels
    assert chef.etat().alarmes == [etat.alarme]


def test_acquitter_puis_go_refait_l_etape(horloge, banc):
    chef = nouveau_chef(horloge, pause_tout=False)
    banc.drapeaux["pret"] = True
    chef.lancer(module_simple(banc))
    tour(chef, horloge)
    tour(chef, horloge, 11)
    assert etat_de(chef).statut == "alarme"
    chef.acquitter("essai")
    with pytest.raises(ErreurChef, match="pas en alarme"):
        chef.acquitter("essai")
    # Acquittée : rien ne repart sans Go, même si l'étape ne le demandait pas.
    tour(chef, horloge)
    assert etat_de(chef).attend == "Go de Karulium"
    assert banc.appels.count("essai.un") == 1
    chef.donner_go("essai")
    tour(chef, horloge)
    assert banc.appels.count("essai.un") == 2
    # Le délai repart de zéro.
    tour(chef, horloge, 9)
    assert etat_de(chef).statut == "en_cours"


def test_erreur_dans_une_condition_donne_une_alarme(horloge, banc):
    def capteur_muet() -> bool:
        raise OSError("la puce ne répond pas")

    chef = nouveau_chef(horloge)
    chef.lancer(Module("m", (Etape("e", QUOI, entree=(Condition("capteur", capteur_muet),)),)))
    tour(chef, horloge)
    assert etat_de(chef, "m").statut == "alarme"
    assert "la puce ne répond pas" in etat_de(chef, "m").alarme.message


def test_erreur_etape_dans_une_action(horloge):
    def action() -> None:
        raise ErreurEtape("carte refusée")

    chef = nouveau_chef(horloge)
    chef.lancer(Module("m", (Etape("e", QUOI, action=action),)))
    tour(chef, horloge)
    assert etat_de(chef, "m").alarme.message == "carte refusée"


def test_surveillance_pendant_les_gestes(horloge, banc):
    banc.drapeaux["pret"] = True
    banc.drapeaux["carte_ok"] = True
    surveillance = banc.condition("carte_ok", quoi_faire="Débloquer la carte.")
    chef = nouveau_chef(horloge)
    chef.lancer(module_simple(banc, surveillances=(surveillance,)))
    tour(chef, horloge)
    tour(chef, horloge)
    assert etat_de(chef).statut == "en_cours"
    banc.drapeaux["carte_ok"] = False
    tour(chef, horloge)
    alarme = etat_de(chef).alarme
    assert alarme.message == "plus tenu : carte_ok"
    assert alarme.quoi_faire == "Débloquer la carte."


def test_attente_d_entree_trop_longue(horloge, banc):
    chef = nouveau_chef(horloge)
    chef.lancer(module_simple(banc, un={"attente_entree_max": "attente"}))
    tour(chef, horloge)
    tour(chef, horloge, 4)
    assert etat_de(chef).statut == "en_cours"
    tour(chef, horloge, 2)
    assert "attente de : pret" in etat_de(chef).alarme.message


def test_alarme_met_tout_en_pause(horloge, banc):
    chef = nouveau_chef(horloge, pause_tout=True)
    banc.drapeaux["pret"] = True
    chef.lancer(module_simple(banc, "a"))
    chef.lancer(module_simple(banc, "b"))
    tour(chef, horloge)
    banc.drapeaux["b.un_fini"] = True
    tour(chef, horloge, 11)  # « a » dépasse son délai
    assert etat_de(chef, "a").statut == "alarme"
    assert chef.en_pause
    assert "b.pauser" in banc.appels
    assert "a.pauser" not in banc.appels  # « a » est arrêté, pas en pause

    chef.reprendre()
    assert "b.reprendre" in banc.appels
    assert "a.reprendre" not in banc.appels
    assert etat_de(chef, "a").statut == "alarme"


def test_alarme_seulement_pour_son_module(horloge, banc):
    chef = nouveau_chef(horloge, pause_tout=False)
    banc.drapeaux["pret"] = True
    chef.lancer(module_simple(banc, "a"))
    chef.lancer(module_simple(banc, "b"))
    tour(chef, horloge)
    banc.drapeaux["b.un_fini"] = True
    tour(chef, horloge, 11)
    assert etat_de(chef, "a").statut == "alarme"
    assert not chef.en_pause
    assert etat_de(chef, "b").etape == "deux"


# ---------------------------------------------------------------- pause


def test_pause_fige_tout_et_ne_compte_pas_dans_le_delai(horloge, banc):
    chef = nouveau_chef(horloge)
    chef.lancer(module_simple(banc))
    tour(chef, horloge)
    chef.pause()
    assert banc.appels == ["essai.pauser"]
    banc.drapeaux["pret"] = True
    tour(chef, horloge, 100)
    assert "essai.un" not in banc.appels  # rien ne démarre pendant la pause
    chef.reprendre()
    assert banc.appels == ["essai.pauser", "essai.reprendre"]
    tour(chef, horloge, 0.1)
    assert banc.appels[-1] == "essai.un"
    # Pause pendant le geste : les 100 s de pause ne comptent pas dans le délai de 10 s.
    chef.pause()
    horloge.t += 100
    chef.reprendre()
    tour(chef, horloge, 1)
    assert etat_de(chef).statut == "en_cours"


# ---------------------------------------------------------------- zones


def test_zone_reservee_fait_attendre_l_autre_module(horloge, banc):
    chef = nouveau_chef(horloge)
    banc.drapeaux["pret"] = True
    chef.lancer(
        module_simple(banc, "a", un={"reserver": ("zone_a",)}, deux={"liberer": ("zone_a",)})
    )
    tour(chef, horloge)
    assert etat_de(chef, "a").zones == ("zone_a",)

    chef.lancer(module_simple(banc, "b", un={"reserver": ("zone_a", "zone_b")}))
    tour(chef, horloge)
    etat_b = etat_de(chef, "b")
    assert etat_b.attend == "zone « zone_a » libre (tenue par « a »)"
    assert etat_b.zones == ()  # tout ou rien : zone_b n'est pas prise non plus
    assert "b.un" not in banc.appels

    # « a » finit son étape « deux », qui libère la zone.
    banc.drapeaux["a.un_fini"] = True
    tour(chef, horloge)
    tour(chef, horloge)
    chef.donner_go("a")
    tour(chef, horloge)
    banc.drapeaux["a.deux_fini"] = True
    tour(chef, horloge)
    assert etat_de(chef, "a").zones == ()
    assert "b.un" in banc.appels
    assert etat_de(chef, "b").zones == ("zone_a", "zone_b")


def test_module_fini_libere_ses_zones(horloge, banc):
    chef = nouveau_chef(horloge)
    banc.drapeaux.update({"pret": True, "essai.un_fini": True, "essai.deux_fini": True})
    chef.lancer(module_simple(banc, un={"reserver": ("zone_a",)}))
    tour(chef, horloge)
    tour(chef, horloge)
    assert etat_de(chef).zones == ("zone_a",)
    chef.donner_go("essai")
    tour(chef, horloge)
    assert etat_de(chef).statut == "fini"
    assert etat_de(chef).zones == ()


def test_abandonner_libere_les_zones(horloge, banc):
    chef = nouveau_chef(horloge)
    banc.drapeaux["pret"] = True
    chef.lancer(module_simple(banc, un={"reserver": ("zone_a",)}))
    tour(chef, horloge)
    chef.abandonner("essai")
    assert etat_de(chef).statut == "abandonne"
    assert etat_de(chef).zones == ()
    assert "essai.arreter" in banc.appels
    chef.lancer(module_simple(banc))  # on peut le relancer


# ---------------------------------------------------------------- carnet


def test_l_etat_est_note_a_chaque_changement(horloge, banc, tmp_path):
    carnet = Carnet(tmp_path / "etat-cycle.json")
    chef = nouveau_chef(horloge, carnet)
    banc.drapeaux["pret"] = True
    chef.lancer(module_simple(banc, un={"reserver": ("zone_a",)}))
    tour(chef, horloge)
    note = json.loads(carnet.chemin.read_text(encoding="utf-8"))
    assert note["modules"][0] == {
        "module": "essai",
        "statut": "en_cours",
        "etape": "un",
        "phase": "fin",
        "go_recu": False,
        "zones": ["zone_a"],
        "alarme": None,
        "memoire": {},
    }
    chef.pause()
    assert carnet.lire()["en_pause"] is True


def test_reprise_apres_coupure(horloge, banc, tmp_path):
    carnet = Carnet(tmp_path / "etat-cycle.json")
    chef = nouveau_chef(horloge, carnet)
    banc.drapeaux.update({"pret": True, "essai.un_fini": True})
    chef.lancer(module_simple(banc, un={"reserver": ("zone_a",)}))
    tour(chef, horloge)
    tour(chef, horloge)
    chef.donner_go("essai")
    tour(chef, horloge)
    assert etat_de(chef).etape == "deux"
    assert etat_de(chef).phase == "fin"

    # Coupure de courant : un nouveau chef relit le carnet.
    banc.appels.clear()
    neuf = nouveau_chef(Horloge(), carnet)
    assert neuf.reprendre_cycle([module_simple(banc)]) == ["essai"]
    etat = etat_de(neuf)
    assert (etat.etape, etat.attend, etat.zones) == ("deux", "Go de Karulium", ("zone_a",))
    neuf.avancer()
    assert banc.appels == []  # rien ne repart sans Go
    neuf.donner_go("essai")
    neuf.avancer()
    assert banc.appels == ["essai.deux"]  # l'étape est refaite depuis le début


def test_reprise_d_un_module_en_alarme(horloge, banc, tmp_path):
    carnet = Carnet(tmp_path / "etat-cycle.json")
    chef = nouveau_chef(horloge, carnet)
    banc.drapeaux["pret"] = True
    chef.lancer(module_simple(banc))
    tour(chef, horloge)
    tour(chef, horloge, 11)
    neuf = nouveau_chef(Horloge(), carnet)
    neuf.reprendre_cycle([module_simple(banc)])
    assert etat_de(neuf).statut == "alarme"
    assert "trop long" in etat_de(neuf).alarme.message


def test_reprise_refusee_si_le_module_a_change(horloge, banc, tmp_path):
    carnet = Carnet(tmp_path / "etat-cycle.json")
    chef = nouveau_chef(horloge, carnet)
    chef.lancer(module_simple(banc))
    autre = Module("essai", (Etape("autre_etape", QUOI),))
    with pytest.raises(ErreurChef, match="pas d'étape « un »"):
        nouveau_chef(Horloge(), carnet).reprendre_cycle([autre])
    with pytest.raises(ErreurChef, match="module « essai » inconnu"):
        nouveau_chef(Horloge(), carnet).reprendre_cycle([])


def test_carnet_absent_ou_abime(tmp_path):
    carnet = Carnet(tmp_path / "etat-cycle.json")
    assert carnet.lire() is None
    carnet.ecrire({"modules": []})
    assert carnet.lire() == {"version": 1, "modules": []}
    assert not list(tmp_path.glob("*.nouveau"))
    carnet.chemin.write_text("{abîmé", encoding="utf-8")
    with pytest.raises(ErreurChef, match="illisible"):
        carnet.lire()


# ---------------------------------------------------------------- tâche 7 : fiabilité


def test_une_erreur_d_etape_peut_dire_quoi_faire(horloge, banc):
    def geste():
        raise ErreurEtape("carte « portique » : alarme 1", "Dégager l'axe.")

    chef = nouveau_chef(horloge)
    chef.lancer(Module("essai", (Etape("un", QUOI, action=geste),)))
    tour(chef, horloge)
    alarme = etat_de(chef).alarme
    assert alarme.message == "carte « portique » : alarme 1"
    assert alarme.quoi_faire == "Dégager l'axe."


def test_capteur_muet_donne_son_quoi_faire(horloge):
    from vidange.materiel import ErreurMateriel
    from vidange.quoi_faire import CAPTEUR_MUET

    def lire():
        raise ErreurMateriel("signal « porte » : pas de réponse")

    chef = nouveau_chef(horloge)
    chef.lancer(Module("essai", (Etape("un", QUOI, entree=(Condition("porte", lire),)),)))
    tour(chef, horloge)
    assert etat_de(chef).alarme.quoi_faire == CAPTEUR_MUET


def test_chaque_nouvelle_alarme_est_annoncee(horloge, banc):
    chef = nouveau_chef(horloge)
    recues = []
    chef.sur_alarme.append(recues.append)
    # Un écouteur qui plante ne gêne ni le chef ni les autres écouteurs.
    chef.sur_alarme.insert(0, lambda alarme: 1 / 0)
    banc.drapeaux["pret"] = True
    chef.lancer(module_simple(banc))
    tour(chef, horloge)
    tour(chef, horloge, 11)  # délai « court » dépassé
    assert [alarme.etape for alarme in recues] == ["un"]
    assert etat_de(chef).statut == "alarme"


def test_la_memoire_du_module_est_reprise_apres_coupure(horloge, banc, tmp_path):
    carnet = Carnet(tmp_path / "etat-cycle.json")
    chef = nouveau_chef(horloge, carnet)
    chef.lancer(module_simple(banc))
    chef.memoriser("essai", seau="S1293", cycle=12)
    assert chef.memoire("essai") == {"seau": "S1293", "cycle": 12}
    with pytest.raises(ErreurChef, match="textes et nombres"):
        chef.memoriser("essai", objet=object())

    apres = nouveau_chef(horloge, carnet)
    assert apres.reprendre_cycle([module_simple(banc)]) == ["essai"]
    assert apres.memoire("essai") == {"seau": "S1293", "cycle": 12}


def test_un_module_exclusif_passe_avant_les_autres(horloge, banc):
    chef = nouveau_chef(horloge)
    banc.drapeaux["pret"] = True
    chef.lancer(module_simple(banc, "essai"))
    tour(chef, horloge)
    # « essai » est en plein geste : pas de module exclusif maintenant.
    exclusif = module_simple(banc, "lieu", exclusif=True)
    with pytest.raises(ErreurChef, match="en plein geste"):
        chef.lancer(exclusif)

    banc.drapeaux["essai.un_fini"] = True
    tour(chef, horloge)
    assert chef.etat().attendent_go == ["essai"]
    chef.lancer(exclusif)
    tour(chef, horloge)
    assert etat_de(chef, "essai").attend == "fin de « lieu »"
    assert chef.etat().attendent_go == []
    with pytest.raises(ErreurChef, match="attend la fin de « lieu »"):
        chef.donner_go("essai")

    # Le module exclusif fait tout son travail ; « essai » ne bouge pas.
    banc.drapeaux["lieu.un_fini"] = True
    tour(chef, horloge)
    tour(chef, horloge)
    chef.donner_go("lieu")
    banc.drapeaux["lieu.deux_fini"] = True
    tour(chef, horloge)
    tour(chef, horloge)
    assert etat_de(chef, "lieu").statut == "fini"
    assert "essai.deux" not in banc.appels
    assert chef.etat().attendent_go == ["essai"]
    chef.donner_go("essai")
    tour(chef, horloge)
    assert banc.appels[-1] == "essai.deux"


def test_dernier_tour_pour_le_chien_de_garde(horloge, banc):
    chef = nouveau_chef(horloge)
    assert chef.dernier_tour is None
    tour(chef, horloge, 3)
    assert chef.dernier_tour == 3


def test_ensuite_choisit_l_etape_suivante(horloge):
    """Une étape qui dit la suivante : on boucle (prise, seau, prise...), puis on saute."""
    faites: list[str] = []
    tours = iter(["un", "trois"])

    def etape(nom: str, ensuite=None) -> Etape:
        return Etape(nom, QUOI, action=lambda: faites.append(nom), ensuite=ensuite)

    chef = nouveau_chef(horloge)
    chef.lancer(
        Module(
            nom="boucle",
            etapes=(etape("un"), etape("deux", lambda: next(tours)), etape("trois")),
        )
    )
    for _ in range(10):
        chef.avancer()
    # « trois » est la dernière, sans « ensuite » : le module est fini.
    assert faites == ["un", "deux", "un", "deux", "trois"]
    assert chef.etat().modules[0].statut == "fini"
