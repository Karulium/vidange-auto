"""Tests de la file d'envoi : cycles vers le logiciel de culture, copies vers la maison."""

import json
import re
import sys
import threading
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from vidange.envois import (
    FORMAT,
    EchecEnvoi,
    ExpediteurCulture,
    ExpediteurSecours,
    Facteur,
    mettre_en_file_secours,
    preparer_facteur,
)
from vidange.envois.cycle import heure_locale
from vidange.envois.outil import main as outil
from vidange.registre import Registre, SauvegardeQuotidienne, ouvrir_registre
from vidange.reglages import ErreurReglages, ReglagesRegistre, charger_reglages

from .conftest import DOSSIER_PI
from .test_registre import GUADELOUPE, Horloge
from .test_reglages import remplacer

JETON = "jeton-de-test-0123456789"
DJANGO_MD = DOSSIER_PI.parent / "docs" / "django.md"


@pytest.fixture
def horloge() -> Horloge:
    return Horloge(datetime(2026, 10, 27, 8, 0, tzinfo=GUADELOUPE))


@pytest.fixture
def donnees(tmp_path: Path) -> Path:
    return tmp_path / "donnees"


@pytest.fixture
def registre(donnees: Path, horloge: Horloge):
    registre = Registre(donnees / "registre.sqlite", donnees / "photos", horloge=horloge)
    yield registre
    registre.fermer()


@pytest.fixture
def envois():
    return charger_reglages(DOSSIER_PI / "reglages").programme.envois


class Monotone:
    """Fausse horloge des attentes, qu'on avance à la main."""

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class Django:
    """Faux logiciel de culture : un vrai petit serveur web local qui note ce qu'il reçoit."""

    def __init__(self) -> None:
        self.recus: list[dict[str, Any]] = []
        self.entetes: list[dict[str, str]] = []
        # Réponses à donner, dans l'ordre (puis 201 pour tout).
        self.reponses: list[int] = []
        django = self

        class Gestion(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 (nom imposé par http.server)
                corps = self.rfile.read(int(self.headers["Content-Length"]))
                django.entetes.append(dict(self.headers))
                code = django.reponses.pop(0) if django.reponses else 201
                if code < 300:
                    django.recus.append(json.loads(corps))
                self.send_response(code)
                self.end_headers()
                self.wfile.write(b'{"detail": "seau inconnu"}' if code == 400 else b"{}")

            def log_message(self, *_: Any) -> None:
                pass

        self.serveur = ThreadingHTTPServer(("127.0.0.1", 0), Gestion)
        self.adresse = f"http://127.0.0.1:{self.serveur.server_address[1]}/machine/api/cycles/"
        threading.Thread(target=self.serveur.serve_forever, daemon=True).start()

    def arreter(self) -> None:
        self.serveur.shutdown()
        self.serveur.server_close()


@pytest.fixture
def django():
    django = Django()
    yield django
    django.arreter()


def remplir_un_cycle(registre: Registre, donnees: Path, horloge: Horloge) -> int:
    cycle = registre.commencer_cycle("vidange", fut="F3")
    horloge.moment += timedelta(minutes=5)
    seau = registre.ajouter_seau(cycle, "S1293")
    registre.objet("seau", "S1293", type_seau="opaque_10l")
    registre.ajouter_dose(seau, "B327", 120.0)
    registre.ajouter_dose(seau, "B328")
    registre.ajouter_seau(cycle, "S1294", bocal="B328")
    registre.noter_mesure("poids_seau", 6.2, "kg", capteur="balance", cycle=cycle, seau="S1293")
    registre.noter_etape(cycle, "descendre", horloge.moment - timedelta(seconds=12), 12.4)
    photo = donnees / "photos" / "2026-10-27" / "dose.jpg"
    photo.parent.mkdir(parents=True)
    photo.write_bytes(b"jpeg")
    registre.noter_photo(photo, camera="dosage", cycle=cycle, seau="S1293", bocal="B327")
    alarme = registre.noter_alarme("vidange", "fût coincé", "Dégager le fût.", cycle=cycle)
    registre.acquitter_alarme(alarme, "karulium")
    horloge.moment += timedelta(minutes=10)
    registre.finir_cycle(cycle)
    return cycle


def facteur_culture(registre, envois, adresse, monotone=None, horloge=None) -> Facteur:
    culture = envois.culture.model_copy(update={"adresse": adresse})
    expediteur = ExpediteurCulture(culture, JETON, registre)
    return Facteur(
        registre,
        envois,
        {"culture": expediteur},
        horloge=horloge or registre._horloge,
        monotone=monotone or Monotone(),
    )


def file(registre: Registre) -> list[dict[str, Any]]:
    return registre.lire("SELECT * FROM envois ORDER BY id")


# ------------------------------------------------------------ la file dans le registre


def test_un_cycle_fini_entre_dans_la_file_une_seule_fois(registre, donnees, horloge):
    cycle = remplir_un_cycle(registre, donnees, horloge)
    (envoi,) = file(registre)
    assert (envoi["destination"], envoi["sorte"], envoi["objet"]) == (
        "culture",
        "cycle",
        str(cycle),
    )
    assert envoi["statut"] == "attente"
    assert re.fullmatch(r"[0-9a-f-]{36}", envoi["cle"])
    assert registre.ajouter_envoi("culture", "cycle", str(cycle)) == envoi["id"]
    assert len(file(registre)) == 1


def test_la_file_survit_a_un_redemarrage(registre, donnees, horloge):
    remplir_un_cycle(registre, donnees, horloge)
    registre.fermer()
    autre = ouvrir_registre(donnees)
    try:
        assert [e["statut"] for e in file(autre)] == ["attente"]
    finally:
        autre.fermer()


# ------------------------------------------------------------ format d'un cycle


def test_heure_locale_sans_fuseau(envois):
    from zoneinfo import ZoneInfo

    fuseau = ZoneInfo(envois.culture.fuseau_horaire)
    assert heure_locale("2026-10-27T12:00:00+00:00", fuseau) == "2026-10-27T08:00:00"
    assert heure_locale(None, fuseau) is None


def test_donnees_d_un_cycle(registre, donnees, horloge, envois):
    cycle = remplir_un_cycle(registre, donnees, horloge)
    expediteur = ExpediteurCulture(envois.culture, JETON, registre)
    (envoi,) = file(registre)
    d = expediteur.donnees(envoi)
    assert d["format"] == FORMAT == 1
    assert d["cle"] == envoi["cle"]
    assert d["machine"] == envois.culture.machine
    assert d["cycle"] == {
        "numero": cycle,
        "module": "vidange",
        "debut": "2026-10-27T08:00:00",
        "fin": "2026-10-27T08:15:00",
        "issue": "termine",
        "fut": "F3",
        "remarque": None,
    }
    assert d["seaux"] == [
        {
            "seau": "S1293",
            "type_seau": "opaque_10l",
            "quand": "2026-10-27T08:05:00",
            "doses": [
                {"bocal": "B327", "quantite_g": 120.0, "quand": "2026-10-27T08:05:00"},
                {"bocal": "B328", "quantite_g": None, "quand": "2026-10-27T08:05:00"},
            ],
        },
        {
            "seau": "S1294",
            "type_seau": None,
            "quand": "2026-10-27T08:05:00",
            "doses": [{"bocal": "B328", "quantite_g": None, "quand": "2026-10-27T08:05:00"}],
        },
    ]
    assert d["bocaux"] == ["B327", "B328"]
    assert d["etapes"][0]["etape"] == "descendre"
    assert d["etapes"][0]["debut"] == "2026-10-27T08:04:48"
    assert d["mesures"] == [
        {
            "nom": "poids_seau",
            "valeur": 6.2,
            "unite": "kg",
            "capteur": "balance",
            "quand": "2026-10-27T08:05:00",
            "fut": None,
            "seau": "S1293",
            "bocal": None,
            "petri": None,
        }
    ]
    assert d["photos"][0]["fichier"] == "2026-10-27/dose.jpg"
    assert (d["photos"][0]["seau"], d["photos"][0]["bocal"]) == ("S1293", "B327")
    assert d["alarmes"][0]["message"] == "fût coincé"
    assert d["alarmes"][0]["acquittee_par"] == "karulium"


def cles(valeur: Any) -> Any:
    """La forme d'un JSON : les noms des champs, sans les valeurs."""
    if isinstance(valeur, dict):
        return {nom: cles(v) for nom, v in valeur.items()}
    if isinstance(valeur, list):
        return [cles(valeur[0])] if valeur else []
    return None


def test_l_exemple_de_django_md_a_exactement_les_champs_envoyes(registre, donnees, horloge, envois):
    """Le format écrit dans docs/django.md et celui du code ne peuvent pas diverger."""
    texte = DJANGO_MD.read_text(encoding="utf-8")
    exemple = json.loads(re.search(r"```json\n(.*?)\n```", texte, re.DOTALL).group(1))
    remplir_un_cycle(registre, donnees, horloge)
    (envoi,) = file(registre)
    envoye = ExpediteurCulture(envois.culture, JETON, registre).donnees(envoi)
    assert cles(exemple) == cles(envoye)
    assert exemple["format"] == FORMAT


# ------------------------------------------------------------ envoi au logiciel de culture


def test_un_cycle_part_au_logiciel_de_culture(registre, donnees, horloge, envois, django):
    remplir_un_cycle(registre, donnees, horloge)
    facteur = facteur_culture(registre, envois, django.adresse)
    assert facteur.tournee() == 1
    (envoi,) = file(registre)
    assert envoi["statut"] == "envoye"
    assert envoi["envoye_le"] is not None
    (recu,) = django.recus
    assert recu["cle"] == envoi["cle"]
    assert recu["seaux"][0]["seau"] == "S1293"
    assert django.entetes[0]["Authorization"] == f"Token {JETON}"
    assert django.entetes[0]["Content-Type"].startswith("application/json")
    # Plus rien à envoyer.
    assert facteur.tournee() == 0
    assert len(django.recus) == 1


def test_serveur_injoignable_le_cycle_attend_et_l_attente_double(
    registre, donnees, horloge, envois
):
    remplir_un_cycle(registre, donnees, horloge)
    monotone = Monotone()
    # Un port où personne n'écoute.
    django = Django()
    adresse = django.adresse
    django.arreter()
    facteur = facteur_culture(registre, envois, adresse, monotone)
    assert facteur.tournee() == 0
    (envoi,) = file(registre)
    assert envoi["statut"] == "attente"
    assert envoi["essais"] == 1
    assert "injoignable" in envoi["derniere_erreur"]
    # Pas de nouvel essai avant l'attente...
    monotone.t += envois.attente_premier_echec_s - 1
    facteur.tournee()
    assert file(registre)[0]["essais"] == 1
    # ... puis un essai, et l'attente suivante est doublée.
    monotone.t += 1
    facteur.tournee()
    assert file(registre)[0]["essais"] == 2
    monotone.t += 2 * envois.attente_premier_echec_s - 1
    facteur.tournee()
    assert file(registre)[0]["essais"] == 2
    monotone.t += 1
    facteur.tournee()
    assert file(registre)[0]["essais"] == 3


def test_l_attente_est_plafonnee(registre, envois):
    registre.ajouter_envoi("culture", "cycle", "1")
    monotone = Monotone()

    class Panne:
        def envoyer(self, envoi, arret):
            raise EchecEnvoi("réseau coupé")

    facteur = Facteur(registre, envois, {"culture": Panne()}, monotone=monotone)
    for _ in range(20):
        facteur.tournee()
        monotone.t += envois.attente_max_min * 60
    assert file(registre)[0]["essais"] == 20


def test_le_serveur_revient_tout_part(registre, donnees, horloge, envois, django):
    remplir_un_cycle(registre, donnees, horloge)
    registre.finir_cycle(registre.commencer_cycle("lavage"))
    django.reponses = [503]
    monotone = Monotone()
    facteur = facteur_culture(registre, envois, django.adresse, monotone)
    assert facteur.tournee() == 0
    # Le premier a raté : la tournée s'arrête, le second n'a pas été essayé.
    assert [e["essais"] for e in file(registre)] == [1, 0]
    monotone.t += envois.attente_premier_echec_s
    assert facteur.tournee() == 2
    assert [r["cycle"]["module"] for r in django.recus] == ["vidange", "lavage"]


def test_un_cycle_refuse_est_mis_de_cote_les_suivants_partent(
    registre, donnees, horloge, envois, django
):
    remplir_un_cycle(registre, donnees, horloge)
    registre.finir_cycle(registre.commencer_cycle("lavage"))
    django.reponses = [400]
    facteur = facteur_culture(registre, envois, django.adresse)
    assert facteur.tournee() == 1
    refuse, envoye = file(registre)
    assert refuse["statut"] == "refuse"
    assert "400" in refuse["derniere_erreur"] and "seau inconnu" in refuse["derniere_erreur"]
    assert envoye["statut"] == "envoye"
    (constat,) = facteur.constats()
    assert constat.niveau == "attention"
    assert f"n° {refuse['id']}" in constat.texte
    # Corrigé côté logiciel de culture : on le renvoie, avec la même clé.
    registre.renvoyer(refuse["id"])
    assert facteur.tournee() == 1
    assert django.recus[-1]["cle"] == refuse["cle"]
    assert facteur.constats()[0].niveau == "ok"


def test_jeton_refuse_on_reessaie(registre, donnees, horloge, envois, django):
    """401 : c'est le jeton qui est faux, pas les données : on réessaiera."""
    remplir_un_cycle(registre, donnees, horloge)
    django.reponses = [401]
    facteur_culture(registre, envois, django.adresse).tournee()
    assert file(registre)[0]["statut"] == "attente"


def test_pas_regle_rien_ne_part_et_rien_ne_se_perd(registre, donnees, horloge, envois):
    remplir_un_cycle(registre, donnees, horloge)
    facteur = preparer_facteur(registre, envois, None, donnees)
    assert facteur.expediteurs == {"culture": None, "secours": None}
    assert facteur.tournee() == 0
    assert file(registre)[0]["statut"] == "attente"
    culture, secours = facteur.constats()
    assert culture.niveau == secours.niveau == "ok"
    assert "adresse vide" in culture.texte and "1 envoi(s) attendent" in culture.texte
    # Adresse donnée mais pas de jeton.
    culture = envois.culture.model_copy(update={"adresse": "http://192.168.1.20/machine/"})
    reglages = envois.model_copy(update={"culture": culture})
    facteur = preparer_facteur(registre, reglages, None, donnees)
    assert "jeton_culture" in facteur.constats()[0].texte
    assert isinstance(
        preparer_facteur(registre, reglages, JETON, donnees).expediteurs["culture"],
        ExpediteurCulture,
    )


def test_un_envoi_trop_vieux_est_signale(registre, donnees, horloge, envois):
    remplir_un_cycle(registre, donnees, horloge)

    class Panne:
        def envoyer(self, envoi, arret):
            raise EchecEnvoi("logiciel de culture injoignable")

    facteur = Facteur(registre, envois, {"culture": Panne()}, horloge=horloge)
    facteur.tournee()
    assert facteur.constats()[0].niveau == "ok"
    horloge.moment += timedelta(hours=envois.signaler_apres_h + 1)
    (constat,) = facteur.constats()
    assert constat.niveau == "attention"
    assert "injoignable" in constat.texte


def test_les_envois_reussis_sont_effaces_apres_quelques_jours(
    registre, donnees, horloge, envois, django
):
    remplir_un_cycle(registre, donnees, horloge)
    facteur = facteur_culture(registre, envois, django.adresse, horloge=horloge)
    facteur.tournee()
    horloge.moment += timedelta(days=envois.garder_envoyes_jours - 1)
    facteur.tournee()
    assert len(file(registre)) == 1
    horloge.moment += timedelta(days=2)
    facteur.tournee()
    assert file(registre) == []


# ------------------------------------------------------------ copie de secours (maison)


def copie_python(dossier: Path) -> list[str]:
    """Une commande qui « envoie à la maison » en copiant dans un dossier (à la place de rsync)."""
    script = (
        "import shutil, sys, pathlib; s = pathlib.Path(sys.argv[1]); d = pathlib.Path(sys.argv[2]);"
        "d.mkdir(exist_ok=True);"
        "(shutil.copytree(s, d / s.name, dirs_exist_ok=True) if s.is_dir() "
        "else shutil.copy(s, d))"
    )
    return [sys.executable, "-c", script, "{chemin}", str(dossier)]


def facteur_secours(registre, envois, donnees, commande, duree_max_s=60.0) -> Facteur:
    secours = envois.secours.model_copy(update={"commande": commande, "duree_max_s": duree_max_s})
    reglages = envois.model_copy(update={"secours": secours})
    expediteur = ExpediteurSecours(secours, donnees)
    return Facteur(registre, reglages, {"secours": expediteur}, monotone=Monotone())


def test_la_copie_du_jour_et_les_photos_partent_a_la_maison(
    registre, donnees, horloge, envois, tmp_path
):
    maison = tmp_path / "maison"
    commande = copie_python(maison)
    secours = envois.secours.model_copy(update={"commande": commande})
    (donnees / "photos" / "2026-10-27").mkdir(parents=True)
    (donnees / "photos" / "2026-10-27" / "a.jpg").write_bytes(b"jpeg")
    sauvegarde = SauvegardeQuotidienne(
        registre,
        donnees / "sauvegardes",
        ReglagesRegistre(heure_sauvegarde=3, copies_gardees=3, periode_verification_min=10),
        horloge=horloge,
        apres_copie=mettre_en_file_secours(registre, secours, donnees),
    )
    sauvegarde.faire_si_besoin()
    assert [(e["sorte"], e["objet"]) for e in file(registre)] == [
        ("fichier", "sauvegardes/registre-2026-10-27.sqlite"),
        ("fichier", "photos"),
    ]
    facteur = facteur_secours(registre, envois, donnees, commande)
    assert facteur.tournee() == 2
    assert (maison / "registre-2026-10-27.sqlite").is_file()
    assert (maison / "photos" / "2026-10-27" / "a.jpg").read_bytes() == b"jpeg"


def test_une_copie_plus_recente_remplace_celle_qui_attendait(registre, donnees, horloge, envois):
    secours = envois.secours.model_copy(update={"commande": ["rsync", "{chemin}", "maison:"]})
    sauvegarde = SauvegardeQuotidienne(
        registre,
        donnees / "sauvegardes",
        ReglagesRegistre(heure_sauvegarde=3, copies_gardees=3, periode_verification_min=10),
        horloge=horloge,
        apres_copie=mettre_en_file_secours(registre, secours, donnees),
    )
    sauvegarde.faire_si_besoin()
    horloge.moment += timedelta(days=1)
    sauvegarde.faire_si_besoin()
    assert [e["objet"] for e in file(registre)] == [
        "photos",
        "sauvegardes/registre-2026-10-28.sqlite",
    ]


def test_sans_commande_rien_n_est_mis_en_file_pour_la_maison(registre, donnees, envois):
    assert mettre_en_file_secours(registre, envois.secours, donnees) is None


def test_copie_ratee_on_reessaiera(registre, donnees, envois):
    (donnees / "x.txt").write_text("x")
    registre.ajouter_envoi("secours", "fichier", "x.txt")
    commande = [
        sys.executable,
        "-c",
        "import sys; print('maison injoignable'); sys.exit(12)",
        "{chemin}",
    ]
    facteur_secours(registre, envois, donnees, commande).tournee()
    (envoi,) = file(registre)
    assert envoi["statut"] == "attente"
    assert (
        "code 12" in envoi["derniere_erreur"] and "maison injoignable" in envoi["derniere_erreur"]
    )


def test_commande_introuvable_on_reessaiera(registre, donnees, envois):
    (donnees / "x.txt").write_text("x")
    registre.ajouter_envoi("secours", "fichier", "x.txt")
    facteur_secours(registre, envois, donnees, ["commande-qui-n-existe-pas", "{chemin}"]).tournee()
    (envoi,) = file(registre)
    assert envoi["statut"] == "attente"
    assert "impossible à lancer" in envoi["derniere_erreur"]


def test_fichier_disparu_est_mis_de_cote(registre, donnees, envois):
    registre.ajouter_envoi("secours", "fichier", "sauvegardes/registre-2026-01-01.sqlite")
    facteur_secours(registre, envois, donnees, copie_python(donnees / "maison")).tournee()
    assert file(registre)[0]["statut"] == "refuse"


def test_une_copie_trop_longue_ou_l_arret_l_interrompent(registre, donnees, envois):
    (donnees / "x.txt").write_text("x")
    registre.ajouter_envoi("secours", "fichier", "x.txt")
    lente = [sys.executable, "-c", "import time; time.sleep(30)", "{chemin}"]
    secours = envois.secours.model_copy(update={"commande": lente, "duree_max_s": 0.3})
    with pytest.raises(EchecEnvoi, match="trop longue"):
        ExpediteurSecours(secours, donnees).envoyer(file(registre)[0], threading.Event())
    arret = threading.Event()
    arret.set()
    secours = envois.secours.model_copy(update={"commande": lente})
    with pytest.raises(EchecEnvoi, match="arrêt du programme"):
        ExpediteurSecours(secours, donnees).envoyer(file(registre)[0], arret)


# ------------------------------------------------------------ réglages


@pytest.mark.parametrize(
    ("avant", "apres", "message"),
    [
        ('adresse: ""', "adresse: serveur/machine", "http://"),
        ("fuseau_horaire: America/Guadeloupe", "fuseau_horaire: Mars/Olympus", "fuseau horaire"),
        ("commande: []", 'commande: [rsync, "maison:x/"]', "{chemin}"),
        ("attente_max_min: 60", "attente_max_min: 0.5", "attente_max_min"),
    ],
)
def test_reglages_faux_des_envois(reglages, avant, apres, message):
    remplacer(reglages / "programme.yaml", avant, apres)
    with pytest.raises(ErreurReglages, match=re.escape(message)):
        charger_reglages(reglages)


# ------------------------------------------------------------ outil vidange-envois


def test_outil(reglages, donnees, horloge, capsys):
    registre = ouvrir_registre(donnees)
    cycle = registre.commencer_cycle("vidange", fut="F3")
    registre.finir_cycle(cycle)
    registre.ajouter_envoi("secours", "fichier", "photos")
    registre.noter_essai_envoi(2, "refuse", "n'existe plus")
    registre.fermer()
    base = ["--reglages", str(reglages), "--donnees", str(donnees)]

    assert outil(["etat", *base]) == 0
    sortie = capsys.readouterr().out
    assert "logiciel de culture : 1 en attente" in sortie
    assert "refuse" in sortie and "n'existe plus" in sortie

    assert outil(["montrer", str(cycle), *base]) == 0
    montre = json.loads(capsys.readouterr().out)
    assert montre["cycle"]["fut"] == "F3"

    assert outil(["renvoyer", "2", *base]) == 0
    assert outil(["renvoyer", "99", *base]) == 1
    capsys.readouterr()

    secrets = donnees.parent / "absent.yaml"
    assert outil(["essayer", *base, "--secrets", str(secrets)]) == 0
    assert "0 envoi(s) réussi(s)" in capsys.readouterr().out
