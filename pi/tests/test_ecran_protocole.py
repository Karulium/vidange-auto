"""Tests du protocole série Nextion et de la description des pages."""

import re

from vidange.ecran import PAGES
from vidange.ecran.protocole import (
    Appui,
    Decodeur,
    Demarrage,
    NumeroPage,
    Retour,
    couleur_565,
    ordre_page,
    ordre_valeur,
)

from .conftest import DOSSIER_PI

FIN = b"\xff\xff\xff"


def test_ordres_envoyes():
    assert ordre_page("etat") == b"page etat" + FIN
    assert ordre_valeur("b_go.bco", 2016) == b"b_go.bco=2016" + FIN
    assert ordre_valeur("t_mode.txt", "Mode : Lavage") == b't_mode.txt="Mode : Lavage"' + FIN


def test_textes_en_latin1_echappes_et_sur_une_ligne():
    texte = 'Fûts « vidés »\nà 10 h — dit "ok" \\ œuf…'
    attendu = 't.txt="Fûts « vidés » à 10 h - dit \\"ok\\" \\\\ oeuf..."'.encode("latin-1")
    assert ordre_valeur("t.txt", texte) == attendu + FIN
    # Un caractère inconnu de l'écran devient « ? » au lieu de faire planter.
    assert ordre_valeur("t.txt", "→") == b't.txt="?"' + FIN


def test_couleurs_en_16_bits():
    assert couleur_565("#000000") == 0
    assert couleur_565("#FFFFFF") == 65535
    assert couleur_565("#FF0000") == 63488
    assert couleur_565("#00FF00") == 2016
    assert couleur_565("#0000FF") == 31


def test_trames_recues_par_morceaux():
    decodeur = Decodeur()
    assert decodeur.ajouter(b"@b_g") == []
    assert decodeur.ajouter(b"o\xff\xff") == []
    suite = b"\xff" + b"\x66\x01" + FIN + b"\x00\x00\x00" + FIN + b"\x88" + FIN
    assert decodeur.ajouter(suite) == [
        Appui("b_go"),
        NumeroPage(1),
        Demarrage(),
        Demarrage(),
    ]
    (erreur, toucher) = decodeur.ajouter(b"\x02\xff\xff\xff\x65\x00\x03\x00\xff\xff\xff")
    assert erreur == Retour(0x02) and erreur.erreur == "objet inconnu sur la page"
    assert toucher == Retour(0x65, b"\x00\x03\x00") and toucher.erreur is None


def test_des_octets_sans_fin_sont_jetes():
    decodeur = Decodeur()
    decodeur.ajouter(b"\x12" * 300)
    assert decodeur.ajouter(b"@b_oui\xff\xff\xff") == [Appui("b_oui")]


def test_pages_md_decrit_chaque_page_et_chaque_objet():
    """nextion/pages.md (pour Karulium) et pages.py (pour le Pi) disent la même chose."""
    texte = (DOSSIER_PI.parent / "nextion" / "pages.md").read_text(encoding="utf-8")
    titres = re.findall(r"^## Page (\d+) : « (\w+) »", texte, flags=re.M)
    assert titres == [(str(page.numero), page.nom) for page in PAGES.values()]
    morceaux = re.split(r"^## Page ", texte, flags=re.M)[1:]
    for page, morceau in zip(PAGES.values(), morceaux, strict=True):
        lignes = re.findall(r"^\| `(\w+)` \| (\w+) \|.*\| (\d+) \|", morceau, flags=re.M)
        attendu = [
            (objet.nom, "Texte" if objet.sorte == "texte" else "Bouton", str(objet.longueur))
            for objet in page.objets
        ]
        assert lignes == attendu, f"page « {page.nom} »"
        for bouton in page.boutons:
            assert f'prints "@{bouton}",0' in morceau, f"code du bouton {bouton}"
