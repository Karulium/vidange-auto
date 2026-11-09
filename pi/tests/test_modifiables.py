"""Réglages modifiables depuis la page (tâche 28 bis) : liste, bornes, vérifications du
démarrage avant l'écriture, historique, retour en arrière, écriture sûre."""

import os
import shutil

import pytest

from vidange.demarrage import erreurs_de_reglages
from vidange.modifiables import ErreurModifiable, Modifiables
from vidange.modifiables.texte_yaml import ErreurTexteYaml, ecrire_valeur, remplacer_valeur
from vidange.registre import Registre
from vidange.reglages import ErreurReglages, charger_reglages

from .conftest import DOSSIER_PI

QUI = "page web (chef, 192.168.1.20)"


@pytest.fixture
def entrees_sorties_chemin():
    return DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml"


@pytest.fixture
def banc(reglages, entrees_sorties_chemin, tmp_path):
    """Les vrais réglages du dépôt (copiés), un registre, et Modifiables devant."""
    registre = Registre(tmp_path / "r.sqlite", tmp_path / "photos")
    occupe = [""]
    modifiables = Modifiables(
        charger_reglages(reglages).modifiables,
        charger_reglages(reglages),
        reglages,
        registre,
        lambda dossier: erreurs_de_reglages(dossier, entrees_sorties_chemin),
        lambda: occupe[0],
    )
    modifiables.occupe = occupe
    modifiables.dossier_reglages = reglages
    yield modifiables
    registre.fermer()


def lignes(chemin) -> list[str]:
    return chemin.read_text(encoding="utf-8").split("\n")


# ---------------------------------------------------------------- écrire une valeur dans le texte


def test_texte_une_seule_valeur_change_et_les_commentaires_restent():
    texte = (
        "# commentaire\n"
        "a:\n"
        "  x: 1   # un\n"
        '  heure: "10:00"  # deux\n'
        "b:\n"
        '  heure: "11:00"\n'
        "  sous:\n"
        "    x: 5\n"
    )
    neuf = remplacer_valeur(texte, "a.heure", "12:30")
    assert neuf == texte.replace('heure: "10:00"  # deux', 'heure: "12:30"  # deux')
    neuf = remplacer_valeur(texte, "b.sous.x", 7)
    assert neuf == texte.replace("    x: 5", "    x: 7")
    neuf = remplacer_valeur(texte, "a.x", 2.5)
    assert "  x: 2.5   # un" in neuf


def test_texte_nombre_sans_exposant():
    assert ecrire_valeur(0.00001) == "0.00001"
    assert ecrire_valeur(15.0) == "15.0"
    assert ecrire_valeur(15) == "15"
    assert ecrire_valeur("19:00") == '"19:00"'


@pytest.mark.parametrize("chemin", ["a.absent", "z.x", "a"])
def test_texte_chemin_introuvable(chemin):
    with pytest.raises(ErreurTexteYaml):
        remplacer_valeur("a:\n  x: 1\n", chemin, 2)


def test_texte_valeur_pas_sur_une_ligne_simple():
    with pytest.raises(ErreurTexteYaml):
        remplacer_valeur("a:\n  x: [1, 2]\n", "a.x", 2)


# ---------------------------------------------------------------- la liste vérifiée au démarrage


def test_la_liste_du_depot_est_valide_et_loin_du_mouvement(reglages):
    liste = charger_reglages(reglages).modifiables.reglages
    assert liste
    for nom, reglage in liste.items():
        assert reglage.fichier in ("programme.yaml", "entretien.yaml"), nom
        assert reglage.chemin.split(".")[0] in ("notifications", "alerte", "pieces"), nom


@pytest.mark.parametrize(
    ("fichier", "chemin"),
    [
        ("machine.yaml", "durees.vidange_max"),
        ("machine.yaml", "positions.stockage_haut"),
        ("fluidnc.yaml", "cartes.portique.course"),
        ("accelerometre.yaml", "broches.sda"),
        ("programme.yaml", "chef.periode_s"),
        ("programme.yaml", "api.port"),
        ("programme.yaml", "lot.fond_periode_s"),
    ],
)
def test_une_entree_qui_vise_le_mouvement_empeche_de_demarrer(reglages, fichier, chemin):
    liste = reglages / "modifiables.yaml"
    texte = liste.read_text(encoding="utf-8")
    texte += f"""
  intrus:
    libelle: Intrus
    fichier: {fichier}
    chemin: {chemin}
    genre: nombre
    min: 0
    max: 1
    unite: m
    aide: Ne doit jamais être permis.
    redemarrage: true
"""
    liste.write_text(texte, encoding="utf-8")
    with pytest.raises(ErreurReglages) as erreur:
        charger_reglages(reglages)
    assert "intrus" in str(erreur.value)
    assert "touche au mouvement" in str(erreur.value) or "fichier" in str(erreur.value)


def test_une_entree_sur_un_reglage_qui_n_existe_pas(reglages):
    liste = reglages / "modifiables.yaml"
    texte = liste.read_text(encoding="utf-8").replace(
        "notifications.escalade.rappel_apres_min", "notifications.escalade.n_existe_pas"
    )
    liste.write_text(texte, encoding="utf-8")
    with pytest.raises(ErreurReglages, match="n'existe pas"):
        charger_reglages(reglages)


def test_une_valeur_actuelle_hors_des_bornes_empeche_de_demarrer(reglages):
    programme = reglages / "programme.yaml"
    programme.write_text(
        programme.read_text(encoding="utf-8").replace(
            "rappel_apres_min: 15", "rappel_apres_min: 2"
        ),
        encoding="utf-8",
    )
    with pytest.raises(ErreurReglages, match="hors des bornes"):
        charger_reglages(reglages)


def test_bornes_pas_dans_l_ordre(reglages):
    liste = reglages / "modifiables.yaml"
    texte = liste.read_text(encoding="utf-8").replace(
        "min: 5\n    max: 120", "min: 500\n    max: 120"
    )
    liste.write_text(texte, encoding="utf-8")
    with pytest.raises(ErreurReglages, match="plus petit que max"):
        charger_reglages(reglages)


# ---------------------------------------------------------------- changer


def test_l_etat_donne_valeurs_bornes_et_aide(banc):
    etat = banc.etat()
    resume = next(r for r in etat["reglages"] if r["nom"] == "heure_resume_soir")
    assert resume["valeur"] == resume["en_vigueur"] == "19:00"
    assert resume["min"] == "12:00" and resume["unite"].startswith("heure")
    assert resume["aide"] and resume["peut_revenir"] is False
    assert etat["redemarrage_necessaire"] is False and etat["occupe"] == ""


def test_un_changement_ne_touche_qu_une_ligne_et_est_note(banc):
    avant = lignes(banc.dossier_reglages / "programme.yaml")
    fait = banc.changer("heure_resume_soir", "20:00", QUI)
    apres = lignes(banc.dossier_reglages / "programme.yaml")
    assert fait["ancien"] == "19:00" and fait["nouveau"] == "20:00" and fait["redemarrage"] is True
    differences = [(a, b) for a, b in zip(avant, apres, strict=True) if a != b]
    assert len(avant) == len(apres) and len(differences) == 1
    assert differences[0][1].strip().startswith('heure: "20:00"')
    # Le registre garde qui, quand, avant, après.
    historique = banc.historique()
    assert len(historique) == 1
    assert historique[0]["qui"] == QUI and historique[0]["nom"] == "heure_resume_soir"
    assert (historique[0]["ancien"], historique[0]["nouveau"]) == ("19:00", "20:00")
    # Le programme n'a pas relu ses réglages : redémarrage nécessaire.
    etat = banc.etat()
    resume = next(r for r in etat["reglages"] if r["nom"] == "heure_resume_soir")
    assert resume["valeur"] == "20:00" and resume["en_vigueur"] == "19:00"
    assert resume["redemarrage_necessaire"] is True and etat["redemarrage_necessaire"] is True
    # Et les réglages relus sont valides et portent la nouvelle valeur.
    assert (
        charger_reglages(banc.dossier_reglages).programme.notifications.resume_soir.heure == "20:00"
    )


def test_nombre_et_entier(banc):
    banc.changer("escalade_rappel", 20, QUI)
    banc.changer("resume_alarmes_max", 3, QUI)
    banc.changer("usure_avance", 12.5, QUI)
    relus = charger_reglages(banc.dossier_reglages)
    assert relus.programme.notifications.escalade.rappel_apres_min == 20
    assert relus.programme.notifications.resume_soir.alarmes_max == 3
    assert relus.entretien.alerte.avance_pourcent == 12.5


@pytest.mark.parametrize(
    ("nom", "valeur", "mot"),
    [
        ("heure_resume_soir", "23:30", "hors des bornes"),
        ("heure_resume_soir", "7h", "HH:MM"),
        ("heure_resume_soir", 19, "HH:MM"),
        ("escalade_rappel", 1, "hors des bornes"),
        ("escalade_rappel", 500, "hors des bornes"),
        ("escalade_rappel", "dix", "nombre"),
        ("escalade_rappel", True, "nombre"),
        ("escalade_rappel", float("nan"), "nombre"),
        ("resume_alarmes_max", 2.5, "entier"),
        ("usure_avance", 0, "hors des bornes"),
    ],
)
def test_valeur_fausse_refusee_et_rien_n_est_ecrit(banc, nom, valeur, mot):
    avant = (banc.dossier_reglages / "programme.yaml").read_bytes()
    avant_e = (banc.dossier_reglages / "entretien.yaml").read_bytes()
    with pytest.raises(ErreurModifiable, match=mot) as erreur:
        banc.changer(nom, valeur, QUI)
    assert erreur.value.statut == 422
    assert (banc.dossier_reglages / "programme.yaml").read_bytes() == avant
    assert (banc.dossier_reglages / "entretien.yaml").read_bytes() == avant_e
    assert banc.historique() == []


def test_reglage_inconnu(banc):
    with pytest.raises(ErreurModifiable) as erreur:
        banc.changer("positions_du_portique", 3, QUI)
    assert erreur.value.statut == 404


def test_meme_valeur_refusee(banc):
    with pytest.raises(ErreurModifiable, match="vaut déjà"):
        banc.changer("heure_resume_soir", "19:00", QUI)


def test_refuse_par_les_verifications_du_demarrage(banc):
    """Le résumé du soir ne peut pas tomber dans les heures calmes (21:00 à 06:00) : la
    vérification complète refuse, et le fichier reste identique."""
    avant = (banc.dossier_reglages / "programme.yaml").read_bytes()
    with pytest.raises(ErreurModifiable, match="heures calmes") as erreur:
        banc.changer("heure_resume_soir", "21:30", QUI)
    assert erreur.value.statut == 409
    assert "rien n'a été changé" in str(erreur.value)
    assert (banc.dossier_reglages / "programme.yaml").read_bytes() == avant
    assert banc.historique() == []
    # Le rappel ne peut pas dépasser le renfort (45 min).
    with pytest.raises(ErreurModifiable, match="renfort_apres_min"):
        banc.changer("escalade_rappel", 60, QUI)


def test_refuse_pendant_un_geste_ou_un_lot(banc):
    banc.occupe[0] = "un geste ou un lot est en cours"
    avant = (banc.dossier_reglages / "programme.yaml").read_bytes()
    with pytest.raises(ErreurModifiable, match="refusé maintenant") as erreur:
        banc.changer("heure_resume_soir", "20:00", QUI)
    assert erreur.value.statut == 409
    assert (banc.dossier_reglages / "programme.yaml").read_bytes() == avant
    assert banc.etat()["occupe"]
    banc.occupe[0] = ""
    banc.changer("heure_resume_soir", "20:00", QUI)


def test_ecriture_sure_meme_si_le_renommage_rate(banc, monkeypatch):
    chemin = banc.dossier_reglages / "programme.yaml"
    avant = chemin.read_bytes()

    def rate(*_):
        raise OSError("disque plein")

    monkeypatch.setattr(os, "replace", rate)
    with pytest.raises(OSError, match="disque plein"):
        banc.changer("heure_resume_soir", "20:00", QUI)
    assert chemin.read_bytes() == avant
    assert banc.historique() == []


def test_ecriture_sans_fichier_provisoire_oublie_et_droits_gardes(banc):
    chemin = banc.dossier_reglages / "programme.yaml"
    os.chmod(chemin, 0o640)
    banc.changer("heure_resume_soir", "20:00", QUI)
    assert not list(banc.dossier_reglages.glob("*.nouveau"))
    assert oct(chemin.stat().st_mode & 0o777) == "0o640"


def test_les_autres_fichiers_ne_bougent_pas(banc, reglages, tmp_path):
    copie = tmp_path / "copie"
    shutil.copytree(reglages, copie)
    banc.changer("usure_avance", 20, QUI)
    for fichier in reglages.glob("*.yaml"):
        if fichier.name != "entretien.yaml":
            assert fichier.read_bytes() == (copie / fichier.name).read_bytes()


# ---------------------------------------------------------------- revenir


def test_revenir(banc):
    premier = banc.changer("heure_resume_soir", "20:00", QUI)["numero"]
    assert next(r for r in banc.etat()["reglages"] if r["nom"] == "heure_resume_soir")[
        "peut_revenir"
    ]
    fait = banc.revenir(premier, QUI)
    assert fait["nouveau"] == "19:00" and fait["ancien"] == "20:00"
    relus = charger_reglages(banc.dossier_reglages)
    assert relus.programme.notifications.resume_soir.heure == "19:00"
    # Le retour est noté aussi, avec sa raison.
    historique = banc.historique()
    assert [h["nouveau"] for h in historique] == ["19:00", "20:00"]
    assert "retour" in historique[0]["raison"]
    # Le changement n° premier n'est plus le dernier : on ne revient pas deux fois dessus.
    with pytest.raises(ErreurModifiable, match="n'est plus le dernier"):
        banc.revenir(premier, QUI)
    # Mais on peut revenir sur le retour (le dernier).
    banc.revenir(fait["numero"], QUI)
    assert (
        charger_reglages(banc.dossier_reglages).programme.notifications.resume_soir.heure == "20:00"
    )


def test_revenir_refuse_si_le_fichier_a_ete_change_a_la_main(banc):
    numero = banc.changer("escalade_rappel", 20, QUI)["numero"]
    fichier = banc.dossier_reglages / "programme.yaml"
    fichier.write_text(
        fichier.read_text(encoding="utf-8").replace("rappel_apres_min: 20", "rappel_apres_min: 25"),
        encoding="utf-8",
    )
    with pytest.raises(ErreurModifiable, match="autrement"):
        banc.revenir(numero, QUI)


def test_revenir_refuse_pendant_un_geste(banc):
    numero = banc.changer("escalade_rappel", 20, QUI)["numero"]
    banc.occupe[0] = "un geste est en cours"
    with pytest.raises(ErreurModifiable, match="refusé maintenant"):
        banc.revenir(numero, QUI)


def test_revenir_sur_un_numero_inconnu(banc):
    with pytest.raises(ErreurModifiable) as erreur:
        banc.revenir(999, QUI)
    assert erreur.value.statut == 404


def test_chaque_reglage_de_la_liste_se_change_aux_bornes_sans_jamais_planter(banc):
    """Aux bornes, un changement est accepté, ou refusé proprement (ErreurModifiable) : jamais
    une autre erreur, et le dossier reste toujours chargeable."""
    for nom, reglage in banc.liste.reglages.items():
        for valeur in (reglage.min, reglage.max):
            try:
                banc.changer(nom, valeur, QUI)
            except ErreurModifiable:
                pass
            charger_reglages(banc.dossier_reglages)
