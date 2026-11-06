"""Stockage (tâches 35 et 35 bis) : places calculées, inventaire, verrous des trajets, prise sur
les piles, rangement dans le tiroir et sur la bande du haut, scénario « stockage » du
simulateur."""

import pytest

from vidange.chef import ErreurEtape
from vidange.entrees_sorties import charger_entrees_sorties
from vidange.mycelium.module import module_mycelium
from vidange.prehension.regles import Objet, Pose
from vidange.registre import ouvrir_registre
from vidange.reglages import charger_reglages
from vidange.remplissage.module import module_remplissage
from vidange.simulateur import Simulateur
from vidange.simulateur.outil import main as simulateur
from vidange.stockage import places
from vidange.stockage.regles import PileVue, ReglesStockage
from vidange.stockage.simulation import stockage_du_simulateur
from vidange.stockage.stockage import Stockage

from .conftest import DOSSIER_PI
from .test_reglages import erreur_de, remplacer

LISTE = charger_entrees_sorties(DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml")
REGLAGES = charger_reglages(DOSSIER_PI / "reglages")
MACHINE = REGLAGES.machine
assert MACHINE.stockage is not None and MACHINE.prehension is not None
REGLES = ReglesStockage(MACHINE)
PREHENSION = MACHINE.prehension


def seau(format: str = "seau_a") -> Objet:
    """Un seau tenu (pris par son fond, de l'intérieur) : il dépasse au-dessus de la face."""
    f = MACHINE.griffe.formats[format]  # type: ignore[union-attr]
    return Objet.depuis("seau", PREHENSION.objets["seau"], rayon_m=f.rayon_haut, dessus_m=f.hauteur)


def stockage(boucle: list[bool] | None = None, registre=None, vision=None) -> Stockage:
    etat = [True] if boucle is None else boucle
    return Stockage(MACHINE, boucle_fermee=lambda: etat[0], registre=registre, vision=vision)


# ---------------------------------------------------------------- places calculées


def test_seaux_par_pile_et_cote_du_bord():
    assert {f: places.seaux_par_pile(MACHINE, f) for f in MACHINE.griffe.formats} == {  # type: ignore[union-attr]
        "seau_a": 5,
        "seau_b": 7,
        "seau_c": 5,
        "seau_d": 3,
    }
    # Bord du seau du haut = 0,496 + h + (k − 1) × pas.
    for format, h, pas in (
        ("seau_a", 0.25, 0.030),
        ("seau_b", 0.20, 0.030),
        ("seau_c", 0.235, 0.035),
        ("seau_d", 0.265, 0.045),
    ):
        for k in range(1, places.seaux_par_pile(MACHINE, format) + 1):
            assert places.bord_pile(MACHINE, format, k) == pytest.approx(0.496 + h + (k - 1) * pas)
    # La face de la tête touche le fond intérieur du seau du haut (fond + 3 mm, PR n° 56, point 2).
    assert places.contact_prise(MACHINE, "seau_a", 5) == pytest.approx(0.496 + 4 * 0.03 + 0.003)


def test_places_de_fin_de_lot():
    nombres = {f: len(places.places_fin_de_lot(MACHINE, f)) for f in MACHINE.griffe.formats}  # type: ignore[union-attr]
    # Hublot reculé à x 2,93 (agrandi de 43 cm) : toutes les piles de la bande atteignent le
    # maximum de 5 places (avant : A 4, B 5, C 4, D 4).
    assert nombres == {"seau_a": 5, "seau_b": 5, "seau_c": 5, "seau_d": 5}
    bande = places.places_fin_de_lot(MACHINE, "seau_b")
    # Axe de la 1re à x ≥ 1,29 (sortie de la bande) ; 1 cm entre piles ; loin du hublot.
    assert bande[0] == (1.29, 0.215)
    assert bande[1][0] - bande[0][0] == pytest.approx(2 * 0.115 + 0.01)
    assert bande[-1][0] + 0.115 <= 2.93 - 0.10
    for x, _ in places.places_fin_de_lot(MACHINE, "seau_a"):
        assert x >= 1.29


def test_ordre_de_vidage():
    # Tâche 35 bis : la bande y 0,215 d'abord (libérée pour les seaux pleins), puis 0,84, 0,53.
    ordre = places.ordre_piles(MACHINE, places.places_piles(MACHINE, "seau_a"))
    assert ordre == [
        "fin_1",
        "fin_2",
        "fin_3",
        "fin_4",
        "fin_5",
        "pile_1",
        "pile_2",
        "pile_4",
        "pile_3",
        "pile_5",
    ]
    magasin = stockage()
    magasin.charger_pile("pile_5", "seau_a", 3)
    magasin.charger_pile("fin_1", "seau_a", 2)
    magasin.charger_pile("pile_2", "seau_a", 5)
    magasin.charger_pile("pile_1", "seau_b", 7)
    assert magasin.pile_a_prendre("seau_a") == "fin_1"
    magasin.charger_pile("fin_1", "seau_a", 0)
    assert magasin.pile_a_prendre("seau_a") == "pile_2"
    assert magasin.pile_a_prendre("seau_b") == "pile_1"
    assert magasin.pile_a_prendre("seau_c") is None
    assert magasin.seaux_vides("seau_a") == 8


def test_capacite_des_files():
    # Stockage agrandi de 43 cm : tiroir A 20, B 21, C 17, D 17 ; butée à x 3,012.
    for format, attendu in (("seau_a", 20), ("seau_b", 21), ("seau_c", 17), ("seau_d", 17)):
        assert places.capacite_tiroir(MACHINE, format) == attendu
    assert places.places_tiroir(MACHINE, "seau_a") == {"file_1": 6, "file_2": 7, "file_3": 7}
    assert places.places_tiroir(MACHINE, "seau_d") == {"file_1": 5, "file_2": 6, "file_3": 6}
    assert MACHINE.stockage.tiroir.butee_x == 3.012  # type: ignore[union-attr]
    # La place sous la caméra du fond (x 2,8785 / 2,872) reste vide pour A et D sur la file 0,215.
    centres = MACHINE.stockage.tiroir.centres_x  # type: ignore[union-attr]
    assert centres["seau_a"]["file_1"][0] == 2.6065 and centres["seau_a"]["file_2"][0] == 2.8785
    assert centres["seau_d"]["file_1"][0] == 2.592 and centres["seau_d"]["file_2"][0] == 2.872
    magasin = stockage()
    files = []
    while (file := magasin.file_libre("seau_c")) is not None:
        files.append(file)
        magasin.seau_range(file)
    assert files == ["file_1"] * 6 + ["file_2"] * 5 + ["file_3"] * 6
    # Seau B : 7 par file.
    assert magasin.file_libre("seau_b") == "file_1"
    # Seau C, file y 0,50 : cale de 15 cm, course du pousseur plus courte d'autant.
    assert magasin.course_pousseur("file_2", "seau_c", 0.325) == pytest.approx(0.175)
    assert magasin.course_pousseur("file_1", "seau_c", 0.325) == 0.325
    assert magasin.course_pousseur("file_2", "seau_a", 0.325) == 0.325


def test_places_et_capacite_de_la_bande_du_haut():
    attendu = {"seau_a": 6, "seau_b": 7, "seau_c": 5, "seau_d": 6}
    assert {f: len(places.places_bande(MACHINE, f)) for f in attendu} == attendu
    # Capacité d'un lot (tiroir + bande) : A 26, B 28, C 22, D 23.
    lot = {f: places.capacite_lot(MACHINE, f) for f in attendu}
    assert lot == {"seau_a": 26, "seau_b": 28, "seau_c": 22, "seau_d": 23}
    assert places.places_bande(MACHINE, "seau_b") == pytest.approx(
        [2.755, 2.52, 2.285, 2.05, 1.815, 1.58, 1.345]
    )
    # Fin de course logicielle : le bord du seau du bout à x ≤ 2,87 pour chaque format.
    for format in attendu:
        rayon = MACHINE.griffe.formats[format].rayon_haut  # type: ignore[union-attr]
        assert places.places_bande(MACHINE, format)[0] + rayon <= 2.87 + 1e-9
    # Le seau poussé arrive à la dernière place ; les autres avancent d'une place.
    assert places.centres_bande(MACHINE, "seau_a", 1) == [(1.37, 0.215)]
    assert [x for x, _ in places.centres_bande(MACHINE, "seau_a", 3)] == [1.914, 1.642, 1.37]


def test_un_lot_plein_de_chaque_format():
    # Capacités de l'étude : A 26, B 28, C 22, D 23 (tiroir d'abord, puis la bande du haut).
    for format, attendu in (("seau_a", 26), ("seau_b", 28), ("seau_c", 22), ("seau_d", 23)):
        magasin = stockage()
        n = 0
        while (place := magasin.place_libre(format)) is not None:
            magasin.seau_range(place, format)
            n += 1
        assert n == attendu == magasin.seaux_pleins()


def test_le_tiroir_d_abord_puis_la_bande():
    magasin = stockage()
    rangees = []
    while (place := magasin.place_libre("seau_a")) is not None:
        rangees.append(place)
        magasin.seau_range(place, "seau_a")
    assert rangees == ["file_1"] * 6 + ["file_2"] * 7 + ["file_3"] * 7 + ["bande_haut"] * 6
    assert magasin.seaux_pleins() == 26 == magasin.capacite_lot("seau_a")
    assert "bande du haut pleine" in magasin.refus_bande("seau_a")
    # Pas de pile de fin de lot tant que la bande a des seaux pleins.
    with pytest.raises(ErreurEtape, match="bande du haut"):
        magasin.charger_pile("fin_1", "seau_a", 2)
    # La pause « plus de place » reste pour un fût plus gros.
    magasin.demander_vidage("plus de place au stockage", 12.0)
    assert magasin.messages == [
        "plus de place au stockage : vider le tiroir et la bande du stockage (26 seaux) ; "
        "substrat restant ≈ 12.0 kg"
    ]
    magasin.tiroir_vide()
    assert magasin.seaux_pleins() == 0 and magasin.inventaire.bande_haut.format is None
    assert magasin.place_libre("seau_a") == "file_1"


def test_la_bande_attend_que_ses_piles_de_fin_de_lot_soient_vides():
    magasin = stockage()
    magasin.charger_pile("fin_2", "seau_a", 1)
    for file, nombre in magasin.places_tiroir("seau_a").items():
        magasin.inventaire.changer_file(file, nombre)
    assert "fin_2" in magasin.refus_bande("seau_a")
    assert magasin.place_libre("seau_a") is None
    magasin.charger_pile("fin_2", "seau_a", 0)
    assert magasin.place_libre("seau_a") == "bande_haut"
    # Un seul format sur la bande.
    magasin.seau_range("bande_haut", "seau_a")
    assert "seaux « seau_a »" in magasin.refus_bande("seau_b")


class FausseVision:
    def __init__(self, vus):
        self.vus = vus

    def seaux_de_la_bande(self):
        return self.vus


def test_photo_apres_chaque_poussee():
    vision = FausseVision([(1.37, 0.215)])
    magasin = stockage(vision=vision)
    magasin.seau_range("bande_haut", "seau_a")
    magasin.verifier_bande()
    # À 7 mm de la ligne : permis ; à 8 mm : arrêt et alerte.
    vision.vus = [(1.37, 0.222)]
    magasin.verifier_bande()
    vision.vus = [(1.37, 0.2231)]
    with pytest.raises(ErreurEtape, match="à 8 mm de sa ligne"):
        magasin.verifier_bande()
    # Seau trop loin (bord au-delà de 2,87, vers le hublot), photo pas lue, seau manquant.
    vision.vus = [(2.75, 0.215)]
    with pytest.raises(ErreurEtape, match="dépasse 2.87"):
        magasin.verifier_bande()
    vision.vus = None
    with pytest.raises(ErreurEtape, match="pas lue"):
        magasin.verifier_bande()
    vision.vus = []
    with pytest.raises(ErreurEtape, match="voit 0 seaux"):
        magasin.verifier_bande()
    # Sans vision (pas encore écrite) : un faux répond les places attendues.
    sans = stockage()
    sans.seau_range("bande_haut", "seau_a")
    sans.verifier_bande()


def test_bande_du_haut_mal_reglee_refusee(reglages):
    remplacer(
        reglages / "machine.yaml",
        "seau_a: [2.73, 2.458, 2.186, 1.914, 1.642, 1.37]",
        "seau_a: [2.75, 2.458, 2.186, 1.914, 1.642, 1.37]",
    )
    assert "bande_haut → places → seau_a : le 1er seau (2.75) dépasse 2.87" in erreur_de(reglages)


def test_centres_du_tiroir_verifies(reglages):
    remplacer(
        reglages / "machine.yaml",
        "file_2: [2.712, 2.412, 2.112, 1.812, 1.512]",
        "file_2: [2.862, 2.562, 2.262, 1.962, 1.662]",
    )
    # La cale de 15 cm de la file 2 : le 1er seau C ne peut plus être à 2,862 (butée 3,012 − 0,15).
    assert "centres_x → seau_c → file_2 : le 1er seau (2.862) dépasse 2.862" in erreur_de(reglages)


def test_tiroir_hors_butee_refuse(reglages):
    remplacer(
        reglages / "machine.yaml",
        "file_1: [2.897, 2.662, 2.427, 2.192, 1.957, 1.722, 1.487]",
        "file_1: [2.91, 2.662, 2.427, 2.192, 1.957, 1.722, 1.487]",
    )
    assert "centres_x → seau_b → file_1 : le 1er seau (2.91) dépasse 3.012" in erreur_de(reglages)


def test_capacite_du_lot_verifiee(reglages):
    remplacer(reglages / "machine.yaml", "capacite_lot: {seau_a: 26,", "capacite_lot: {seau_a: 25,")
    assert "capacite_lot → seau_a : 25 dans les réglages" in erreur_de(reglages)


def test_coin_des_suspects_a_portee_de_la_griffe(reglages):
    suspects, _ = places.coin_inspection(MACHINE)
    quinconce = places.places_bocaux(MACHINE)
    assert quinconce["bocal_8_13"][0] == pytest.approx(2.6375) and "bocal_8_13" in suspects
    assert max(quinconce[nom][0] for nom in suspects) <= 2.738
    # Un coin trop vers le bout est refusé (le rang 13 de la rangée 8 est le dernier du quinconce).
    remplacer(reglages / "machine.yaml", "paires: {places: 14,", "paires: {places: 15,")
    remplacer(reglages / "machine.yaml", "suspects: [[8, 11]", "suspects: [[8, 14]")
    assert "la place [8, 14] (x 2.7475) est hors de la portée de la griffe" in erreur_de(reglages)


def test_bocaux_et_boites():
    quinconce = places.places_bocaux(MACHINE)
    assert len(quinconce) == 122
    assert quinconce["bocal_0_0"] == (1.2075, 0.06)
    assert quinconce["bocal_0_13"][0] == pytest.approx(2.6375)
    assert quinconce["bocal_1_12"] == (pytest.approx(2.5825), pytest.approx(0.1553))
    assert len(places.places_semence(MACHINE)) == 18
    assert len(places.places_saines(MACHINE)) == 107
    assert places.capacite_boite(MACHINE) == 18
    assert places.hauteur_boite(MACHINE, 10) == pytest.approx(0.498 + 0.13)


def test_coin_d_inspection_plein():
    magasin = stockage()
    suspects, _ = places.coin_inspection(MACHINE)
    for _ in range(9):
        magasin.poser_bocal(magasin.place_suspect_libre(), "suspect")
    assert all(place in magasin.inventaire.bocaux for place in suspects)
    with pytest.raises(ErreurEtape, match="coin d'inspection plein"):
        magasin.place_suspect_libre()


def test_boite_a_capsules_pleine():
    magasin = stockage()
    for _ in range(18):
        magasin.capsule_posee("capsules_enlevees")
    assert magasin.hauteur_boite("capsules_enlevees") == pytest.approx(0.498 + 18 * 0.013)
    with pytest.raises(ErreurEtape, match="pleine"):
        magasin.capsule_posee("capsules_enlevees")
    magasin.boite_changee("capsules_enlevees")
    magasin.capsule_posee("capsules_enlevees")


def test_charger_une_pile_verifie_le_nombre_et_la_bande():
    magasin = stockage()
    with pytest.raises(ErreurEtape, match="au plus 5"):
        magasin.charger_pile("pile_1", "seau_a", 6)
    with pytest.raises(ErreurEtape, match="pas de place de pile"):
        magasin.charger_pile("pile_9", "seau_a", 1)
    magasin.charger_pile("fin_1", "seau_a", 3)
    with pytest.raises(ErreurEtape, match="même format"):
        magasin.charger_pile("fin_2", "seau_b", 3)
    with pytest.raises(ErreurEtape, match="pas de place de pile"):
        magasin.charger_pile("fin_6", "seau_a", 1)


def test_inventaire_garde_dans_le_registre(tmp_path):
    registre = ouvrir_registre(tmp_path)
    try:
        magasin = stockage(registre=registre)
        magasin.charger_pile("pile_1", "seau_a", 5)
        magasin.seau_range("file_1")
        magasin.capsule_posee("couvercles_perces")
        magasin.poser_bocal("bocal_2_3")
        autre = stockage(registre=registre)
        assert autre.inventaire.piles["pile_1"].format == "seau_a"
        assert autre.inventaire.piles["pile_1"].nombre == 5
        assert autre.inventaire.files["file_1"] == 1
        assert autre.inventaire.boites["couvercles_perces"] == 1
        assert autre.inventaire.bocaux == {"bocal_2_3": "bocal"}
    finally:
        registre.fermer()


# ---------------------------------------------------------------- réglages


def test_reglages_stockage_refuses(reglages):
    remplacer(reglages / "machine.yaml", "pile_2: [1.61, 0.84]", "pile_2: [1.50, 0.84]")
    assert "les places « pile_1 » et « pile_2 » se chevauchent" in erreur_de(reglages)


def test_tiroir_trop_long_refuse(reglages):
    remplacer(
        reglages / "machine.yaml",
        "seau_a: {file_1: 6, file_2: 7, file_3: 7}",
        "seau_a: {file_1: 6, file_2: 8, file_3: 7}",
    )
    assert "centres_x → seau_a → file_2 : 7 centres pour 8 places" in erreur_de(reglages)


def test_file_du_tiroir_inconnue_refusee(reglages):
    remplacer(
        reglages / "machine.yaml", "files: [file_1, file_2, file_3]", "files: [file_1, file_9]"
    )
    assert "« file_9 » absente de remplissage" in erreur_de(reglages)


def test_coin_d_inspection_mal_ecrit_refuse(reglages):
    remplacer(reglages / "machine.yaml", "separation: [[5, 10]", "separation: [[8, 11]")
    assert "place [8, 11] écrite deux fois" in erreur_de(reglages)


def test_pas_de_pile_obligatoire(reglages):
    remplacer(reglages / "machine.yaml", "      pas_pile_m: 0.045\n", "")
    assert "il faut la hauteur et pas_pile_m du format « seau_d »" in erreur_de(reglages)


# ---------------------------------------------------------------- verrous des trajets


def refus(depart, arrivee, objet=None, piles=(), boucle=True):
    return REGLES.refus_prehension(depart, arrivee, objet, list(piles), boucle)


def pile(nom, x, y, nombre=5, format="seau_a"):
    rayon = MACHINE.griffe.formats[format].rayon_haut  # type: ignore[union-attr]
    return PileVue(nom, x, y, rayon, places.bord_pile(MACHINE, format, nombre))


def test_boucle_ouverte_rien_ne_bouge():
    depart = Pose(1.0, 0.6, 1.1, 0)
    assert "boucle du stockage ouverte" in refus(depart, depart.avec(x=1.2), boucle=False)
    assert "boucle du stockage ouverte" in refus(depart, depart.avec(z=1.0), boucle=False)
    # Rester sur place : rien à refuser.
    assert refus(depart, depart, boucle=False) is None
    assert "boucle du stockage ouverte" in REGLES.refus_griffe(1.0, 1.2, False)
    # Rails X +0,43 (PR n° 56, point 9) : mât de la griffe à x ≤ 2,738.
    assert REGLES.refus_griffe(1.0, 2.73, True) is None
    assert "x ≤ 2,738" in REGLES.refus_griffe(2.0, 2.74, True)


def test_seau_jamais_au_dessus_d_une_pile_pleine():
    tenu = seau()
    piles = [pile("pile_1", 1.30, 0.84, 4), pile("pile_2", 1.61, 0.84, 5)]
    # Sortie de pile_1 (4 seaux restent), en haut (bord ≤ 1,155) : passe.
    depart = Pose(1.30, 0.84, 0.905, 0)
    assert refus(depart, Pose(0.925, 0.50, 0.905, 0), tenu, piles) is None
    # Vers pile_4 en passant au-dessus de pile_2, qui a des seaux : refusé.
    assert "pile « pile_2 »" in refus(depart, Pose(1.96, 0.84, 0.85, 0), tenu, piles)
    # Sortie trop basse : fond à 3 cm au moins au-dessus du bord de la pile qui reste.
    bas = depart.avec(z=0.85)
    assert "bord de la pile + 3 cm" in refus(bas, bas.avec(x=1.25, y=0.70), tenu, piles)
    # Fond à 0,79 au moins au-dessus du plateau.
    loin = Pose(2.0, 0.60, 0.78, 0)
    assert "fond à 0,78 m" in refus(loin, loin.avec(x=1.9), tenu)


def test_rail_operateur():
    """Haut du seau au-dessus de 1,11 : axe y + rayon du bord ≤ 0,995 ; sinon haut ≤ 1,10."""
    tenu = seau()  # seau A, rayon du bord 0,1335 ; haut à z + 0,25
    depart = Pose(1.45, 0.75, 0.905, 0)
    # Rangée y 0,84 : 0,84 + 0,1335 ≤ 0,995, haut à 1,155 permis (entre les piles ou dessus).
    assert refus(depart, depart.avec(y=0.84), tenu) is None
    assert refus(Pose(1.30, 0.70, 0.905, 0), Pose(1.30, 0.84, 0.905, 0), tenu) is None
    # Axe à y 0,87 (0,87 + 0,1335 > 0,995) : haut à 1,155 refusé, à 1,10 permis.
    refuse = refus(depart, depart.avec(y=0.87), tenu)
    assert refuse is not None and "rail opérateur" in refuse and "≤ 0,995" in refuse
    assert refus(depart.avec(z=0.85), Pose(1.45, 0.87, 0.85, 0), tenu) is None
    assert "rail opérateur" in refus(depart.avec(z=0.851), Pose(1.45, 0.87, 0.851, 0), tenu)


def test_boites_a_capsules():
    bocal = Objet.depuis("bocal", PREHENSION.objets["bocal"])
    # Bocal tenu (17 cm sous la face) : bas à 0,73 au-dessus de la boîte (2,95 ; 0,53) : refusé.
    depart = Pose(2.70, 0.53, 0.90, 0)
    assert "boîte à capsules « capsules_enlevees »" in refus(depart, depart.avec(x=2.95), bocal)
    assert refus(depart.avec(z=0.95), Pose(2.95, 0.53, 0.95, 0), bocal) is None


def test_camera_du_bocal():
    tenu = seau()
    # Seau tenu près du boîtier (y < 0,44, x < 1,29) : refusé.
    assert "caméra du bocal" in refus(
        Pose(1.40, 0.215, 0.905, 0), Pose(1.20, 0.215, 0.905, 0), tenu
    )
    # Sortie de la bande : le long de y 0,215 jusqu'à x 1,29, puis vers +y jusqu'à 0,44.
    assert refus(Pose(1.85, 0.215, 0.905, 0), Pose(1.29, 0.215, 0.905, 0), tenu) is None
    assert refus(Pose(1.29, 0.215, 0.905, 0), Pose(1.29, 0.44, 0.905, 0), tenu) is None
    # Fond trop bas pendant la sortie de la bande (0,80 au moins).
    assert "il faut 0,8 m" in refus(Pose(1.85, 0.215, 0.795, 0), Pose(1.60, 0.215, 0.795, 0), tenu)
    # Tête vide : y ≥ 0,29 + rayon tant que x < 1,115 + rayon.
    assert "caméra du bocal" in refus(Pose(1.10, 0.50, 1.10, 0), Pose(1.10, 0.30, 1.10, 0))
    assert refus(Pose(1.10, 0.50, 1.10, 0), Pose(1.10, 0.34, 1.10, 0)) is None
    # Entonnoir (rayon 0,09) : x ≥ 1,205 si y < 0,38.
    entonnoir = Objet("entonnoir", 0.09, 0.0, 0.1)
    assert "caméra du bocal" in refus(
        Pose(1.20, 0.50, 1.10, 0), Pose(1.20, 0.35, 1.10, 0), entonnoir
    )
    assert refus(Pose(1.21, 0.50, 1.10, 0), Pose(1.21, 0.35, 1.10, 0), entonnoir) is None


def test_photo_du_fond():
    assert REGLES.refus_photo_du_fond(0.71, False) is None
    assert "entonnoir" in REGLES.refus_photo_du_fond(0.71, True)
    assert "0,7 à 0,73" in REGLES.refus_photo_du_fond(0.75, False)


# ---------------------------------------------------------------- avec la préhension simulée


def jouer(simulation, prehension, fabrique):
    prehension.lancer(fabrique)
    for _ in range(4000):
        if prehension.geste_fini():
            return
        simulation.temps += 0.25
    raise AssertionError("geste pas fini")


def test_prise_double_et_rendu_sur_la_pile():
    with Simulateur(REGLAGES, LISTE, "stockage") as simulation:
        scenario = stockage_du_simulateur(simulation)
        magasin, prehension = scenario.stockage, scenario.remplissage.prehension
        magasin.brancher_prehension(prehension)
        assert magasin.pile_a_prendre("seau_a") == "pile_1"
        jouer(simulation, prehension, lambda: magasin.geste_prendre_seau(prehension, "seau_a"))
        assert magasin.inventaire.piles["pile_1"].nombre == 4
        assert prehension.objet is not None and prehension.objet.sorte == "seau"
        # Deux seaux emboîtés : un de plus est parti ; le seau du dessus revient emboîté sur
        # les 3 qui restent (contact au fond du 4e).
        magasin.prise_double()
        assert magasin.inventaire.piles["pile_1"].nombre == 3
        jouer(simulation, prehension, lambda: magasin.geste_rendre_seau(prehension))
        assert magasin.inventaire.piles["pile_1"].nombre == 4
        assert prehension.objet is None
        assert prehension.tete.position().x == pytest.approx(1.30)


def test_prise_sur_la_bande_sort_par_moins_x():
    with Simulateur(REGLAGES, LISTE, "stockage") as simulation:
        scenario = stockage_du_simulateur(simulation)
        magasin, prehension = scenario.stockage, scenario.remplissage.prehension
        magasin.brancher_prehension(prehension)
        for nom in ("pile_1", "pile_2", "pile_4"):
            magasin.charger_pile(nom, "seau_a", 0)
        magasin.charger_pile("fin_2", "seau_a", 2)
        jouer(simulation, prehension, lambda: magasin.geste_prendre_seau(prehension, "seau_a"))
        fin = prehension.tete.position()
        assert (fin.x, fin.y) == (pytest.approx(1.29), pytest.approx(0.44))
        assert magasin.inventaire.piles["fin_2"].nombre == 1


def test_boucle_ouverte_la_prehension_refuse():
    with Simulateur(REGLAGES, LISTE, "stockage") as simulation:
        scenario = stockage_du_simulateur(simulation)
        magasin, prehension = scenario.stockage, scenario.remplissage.prehension
        magasin.brancher_prehension(prehension)
        simulation.fabrique.actionner("boucle_stockage", False)
        assert not magasin.boucle_fermee()
        cible = prehension.tete.position()
        assert "boucle du stockage ouverte" in prehension.refus_manuel(cible.avec(x=cible.x + 0.1))
        with pytest.raises(ErreurEtape, match="boucle du stockage ouverte"):
            prehension.lancer(lambda: magasin.geste_prendre_seau(prehension, "seau_a"))


def test_file_3_refusee_sans_chariot_du_fut():
    with Simulateur(REGLAGES, LISTE, "stockage") as simulation:
        scenario = stockage_du_simulateur(simulation)
        remplissage = scenario.remplissage.remplissage
        files = MACHINE.remplissage.rangement.files  # type: ignore[union-attr]
        simulation.fabrique.actionner("chariot_fut_en_place", False)
        assert remplissage.place_permise(files["file_1"].y)
        assert not remplissage.place_permise(files["file_3"].y)


# ---------------------------------------------------------------- scénario « stockage »


def jouer_scenario(regler=lambda simulation: None):
    with Simulateur(REGLAGES, LISTE, "stockage") as simulation:
        scenario = stockage_du_simulateur(simulation)
        regler(simulation)
        s = scenario.remplissage
        modules = [
            module_remplissage(s.remplissage, s.prehension, s.mycelium, s.plan),
            module_mycelium(s.mycelium),
        ]
        return simulation.jouer(modules), scenario


def test_scenario_stockage():
    planning, scenario = jouer_scenario()
    assert planning.fini, planning.probleme
    magasin = scenario.stockage
    plan = scenario.remplissage.plan
    assert len(plan.faits) == 19
    # 4 piles de 5 seaux A vidées dans l'ordre (la prise double rend un seau à pile_1).
    vides = ("pile_1", "pile_2", "pile_4", "pile_3")
    assert all(magasin.inventaire.piles[nom].nombre == 0 for nom in vides)
    rangements = [ligne.etape for ligne in planning.lignes if ligne.module == "remplissage"]
    # 26 seaux A par lot : 20 au tiroir (6 + 7 + 7, dont 13 déjà rangés au départ), puis 6 sur la
    # bande du haut, chacun vérifié par la photo du plafond ; pause, tiroir et bande vidés ; les
    # 6 derniers dans la file 1.
    assert rangements.count("photo_de_la_bande") == 6
    assert rangements.count("vider_le_tiroir") == 1
    assert rangements.count("confirmer_tiroir_vide") == 1
    assert magasin.messages == [
        "plus de place au stockage : vider le tiroir et la bande du stockage (26 seaux)"
    ]
    assert magasin.inventaire.files == {"file_1": 6, "file_2": 0, "file_3": 0}
    assert magasin.inventaire.bande_haut.nombre == 0
    textes = [texte for _, texte in planning.evenements]
    assert any("boucle_stockage » relâché" in texte for texte in textes)
    assert any("boucle_stockage » actionné" in texte for texte in textes)


def test_scenario_boucle_ouverte_rien_ne_bouge():
    planning, scenario = jouer_scenario(
        lambda simulation: simulation.fabrique.actionner("boucle_stockage", False)
    )
    assert not planning.fini
    assert scenario.remplissage.plan.faits == []
    # Le module attend la boucle avant tout geste : le chariot et la tête n'ont pas bougé.
    lignes = [ligne for ligne in planning.lignes if ligne.module == "remplissage"]
    assert [ligne.etape for ligne in lignes] == ["verifier_place"]
    assert lignes[0].action is None
    assert "boucle du stockage fermée" in planning.en_texte()


def test_outil_simulateur_stockage(capsys):
    assert simulateur(["stockage", "--delai-go", "0"]) == 0
    sortie = capsys.readouterr().out
    assert "vider_le_tiroir" in sortie and "confirmer_tiroir_vide" in sortie


def test_outil_places_et_piles(capsys):
    from vidange.stockage.outil import main as outil

    assert outil(["piles", "seau_a"]) == 0
    sortie = capsys.readouterr().out
    assert "5 seaux au plus" in sortie and "5 seau(x) : bord à 0,866 m" in sortie
    assert outil(["places", "seau_c"]) == 0
    sortie = capsys.readouterr().out
    assert "capacité du tiroir : 17 seaux" in sortie and "Capacité d'un lot : 22 seaux" in sortie
    assert (
        "Bande du haut y 0,215 : 5 places (centres x 2,7125, 2,4125, 2,1125, 1,8125, 1,5125)"
        in sortie
    )
    assert outil(["places", "seau_z"]) == 2
