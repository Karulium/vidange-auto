"""Tests des notifications sur le téléphone (tâche 27) : ntfy et Telegram contre de faux serveurs
locaux (jamais de vrai service), file sans réseau, heures calmes, résumé du soir, escalade."""

import json
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import SecretStr

from vidange.envois import Facteur
from vidange.envois.facteur import preparer_facteur
from vidange.envois.telephone import expediteurs_telephone
from vidange.fichier_secrets import Secrets, charger_secrets
from vidange.notifications import Notificateur, en_heures_calmes
from vidange.registre import ErreurRegistre, Registre
from vidange.registre import montees as module_montees
from vidange.reglages import ErreurReglages, ReglagesNotifications, charger_reglages

from .conftest import DOSSIER_PI
from .test_envois import Monotone
from .test_registre import GUADELOUPE, Horloge
from .test_reglages import erreur_de, remplacer

SUJET = "sujet-difficile-a-deviner-0123"
SUJET_2 = "second-sujet-difficile-4567"
JETON_BOT = "123456:jeton-du-bot-de-test"


@pytest.fixture(autouse=True)
def heure_de_la_guadeloupe(monkeypatch):
    """Les heures du registre sont locales : on fixe celle de la machine, quelle que soit celle du
    PC qui lance les tests. Et jamais de proxy vers les faux serveurs locaux."""
    monkeypatch.setenv("TZ", "America/Guadeloupe")
    time.tzset()
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    yield
    monkeypatch.undo()
    time.tzset()


class FauxServeur:
    """Un vrai petit serveur web local qui fait semblant d'être ntfy (POST /) et Telegram
    (POST /bot<jeton>/sendMessage) et note ce qu'il reçoit."""

    def __init__(self) -> None:
        self.ntfy: list[dict[str, Any]] = []
        self.telegram: list[dict[str, Any]] = []
        self.entetes: list[dict[str, str]] = []
        self.en_panne = False
        faux = self

        class Gestion(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 (nom imposé par http.server)
                corps = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if faux.en_panne:
                    self.send_response(503)
                    self.end_headers()
                    return
                faux.entetes.append(dict(self.headers))
                if self.path == "/":
                    faux.ntfy.append(corps)
                elif self.path == f"/bot{JETON_BOT}/sendMessage":
                    faux.telegram.append(corps)
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *_: Any) -> None:
                pass

        self.serveur = ThreadingHTTPServer(("127.0.0.1", 0), Gestion)
        self.adresse = f"http://127.0.0.1:{self.serveur.server_address[1]}"
        threading.Thread(target=self.serveur.serve_forever, daemon=True).start()

    def arreter(self) -> None:
        self.serveur.shutdown()
        self.serveur.server_close()


@pytest.fixture
def faux():
    serveur = FauxServeur()
    yield serveur
    serveur.arreter()


@pytest.fixture
def horloge() -> Horloge:
    # Lundi 9 novembre 2026, 10 h : en dehors des heures calmes (21:00 à 06:00).
    return Horloge(datetime(2026, 11, 9, 10, 0, tzinfo=GUADELOUPE))


@pytest.fixture
def registre(tmp_path: Path, horloge: Horloge):
    registre = Registre(tmp_path / "registre.sqlite", tmp_path / "photos", horloge=horloge)
    yield registre
    registre.fermer()


@pytest.fixture
def programme():
    return charger_reglages(DOSSIER_PI / "reglages").programme


def secrets_de(faux: FauxServeur, **plus: Any) -> Secrets:
    return Secrets(
        ntfy_serveur=faux.adresse,
        ntfy_sujet=SecretStr(SUJET),
        telegram_jeton_bot=SecretStr(JETON_BOT),
        telegram_chat=SecretStr("1111"),
        **plus,
    )


class Banc:
    """Registre + facteur (vrais expéditeurs, faux serveur) + notificateur, une seule horloge."""

    def __init__(self, registre, horloge, programme, secrets, entretien=None, **reglages) -> None:
        self.registre = registre
        self.horloge = horloge
        # Le faux serveur joue aussi l'API Telegram : jamais de vraie adresse.
        reglages.setdefault("telegram_adresse", secrets.ntfy_serveur or "http://127.0.0.1:1")
        self.reglages: ReglagesNotifications = programme.notifications.model_copy(update=reglages)
        self.monotone = Monotone()
        expediteurs, pas_regle = expediteurs_telephone(
            self.reglages, secrets, registre, horloge=horloge
        )
        self.facteur = Facteur(
            registre,
            programme.envois,
            expediteurs,
            pas_regle,
            horloge=horloge,
            monotone=self.monotone,
        )
        self.notificateur = Notificateur(
            registre, self.reglages, self.facteur, entretien, horloge=horloge
        )

    def avancer(self, **duree: float) -> None:
        self.horloge.moment += timedelta(**duree)
        self.monotone.t += timedelta(**duree).total_seconds()

    def etat(self, canal: str) -> list[str]:
        return [
            ligne["statut"]
            for ligne in self.registre.lire(
                "SELECT statut FROM envois WHERE destination = ? ORDER BY id", (canal,)
            )
        ]


@pytest.fixture
def banc(registre, horloge, programme, faux):
    return Banc(registre, horloge, programme, secrets_de(faux))


def ouvrir_alarme(registre, module="spray", message="flacon vide", quoi="Changer le flacon."):
    return registre.noter_alarme(module, message, quoi, etape="pomper")


# ------------------------------------------------------------ réglages et secrets


def test_les_reglages_du_depot_declarent_les_niveaux(programme):
    notif = programme.notifications
    assert notif.niveau_defaut == "urgent"
    assert {"fin_fut", "nettoyage_a_faire", "entretien_a_faire", "calcul_conseille"} <= set(
        notif.niveaux
    )
    assert notif.exemple is True


def test_un_niveau_inconnu_empeche_de_demarrer(reglages):
    remplacer(reglages / "programme.yaml", "fin_fut: info", "fin_fut: bruyant")
    assert "notifications" in erreur_de(reglages)


def test_le_resume_ne_peut_pas_tomber_dans_les_heures_calmes(reglages):
    remplacer(reglages / "programme.yaml", 'heure: "19:00"', 'heure: "23:00"')
    texte = erreur_de(reglages)
    assert "resume_soir" in texte and "heures calmes" in texte


def test_le_renfort_vient_apres_le_rappel(reglages):
    remplacer(reglages / "programme.yaml", "renfort_apres_min: 45", "renfort_apres_min: 10")
    assert "renfort_apres_min doit être plus long" in erreur_de(reglages)


def test_une_heure_mal_ecrite_est_refusee(reglages):
    remplacer(reglages / "programme.yaml", 'debut: "21:00"', 'debut: "9h"')
    assert "HH:MM" in erreur_de(reglages)


def test_les_priorites_ne_redescendent_pas(reglages):
    remplacer(reglages / "programme.yaml", "    rappel: 5", "    rappel: 2")
    assert "sans redescendre" in erreur_de(reglages)


def test_un_sujet_ntfy_trop_court_est_refuse(tmp_path):
    chemin = tmp_path / "secrets.yaml"
    chemin.write_text('ntfy_serveur: "https://ntfy.sh"\nntfy_sujet: "court"\n', encoding="utf-8")
    chemin.chmod(0o600)
    with pytest.raises(ErreurReglages, match="trop facile à deviner"):
        charger_secrets(chemin)


def test_une_adresse_ntfy_sans_http_est_refusee(tmp_path):
    chemin = tmp_path / "secrets.yaml"
    chemin.write_text('ntfy_serveur: "ntfy.sh"\n', encoding="utf-8")
    chemin.chmod(0o600)
    with pytest.raises(ErreurReglages, match="http"):
        charger_secrets(chemin)


def test_le_sujet_ne_sort_jamais_dans_un_texte_de_secret():
    secrets = Secrets(ntfy_sujet=SecretStr(SUJET))
    assert SUJET not in repr(secrets) and SUJET not in str(secrets)


# ------------------------------------------------------------ canaux éteints


def test_sans_secrets_les_canaux_sont_eteints_et_la_checklist_le_dit(
    registre, horloge, programme, tmp_path
):
    facteur = preparer_facteur(
        registre, programme.envois, None, tmp_path, programme.notifications, Secrets()
    )
    constats = {c.sujet: c for c in facteur.constats()}
    for nom in ("ntfy", "Telegram"):
        constat = constats[f"envoi : notifications {nom}"]
        assert constat.niveau == "ok" and "éteint" in constat.texte
        assert "pas une erreur" in constat.texte
    notificateur = Notificateur(registre, programme.notifications, facteur, horloge=horloge)
    ouvrir_alarme(registre)
    assert notificateur.canaux_actifs() == []
    assert notificateur.tour() == 0
    assert registre.lire("SELECT * FROM envois WHERE sorte = 'message'") == []
    # L'alarme est notée comme traitée : on ne l'enverra pas des jours plus tard.
    assert registre.notification_faite("alarme:1") is not None


def test_un_seul_canal_rempli_est_allume(registre, horloge, programme, faux):
    secrets = Secrets(ntfy_serveur=faux.adresse, ntfy_sujet=SecretStr(SUJET))
    banc = Banc(registre, horloge, programme, secrets)
    assert banc.notificateur.canaux_actifs() == ["ntfy"]
    ouvrir_alarme(registre)
    banc.notificateur.tour()
    assert len(faux.ntfy) == 1 and faux.telegram == []


# ------------------------------------------------------------ alarmes (60)


def test_une_alarme_part_sur_ntfy_et_telegram_avec_son_quoi_faire(banc, faux, registre):
    ouvrir_alarme(registre)
    assert banc.notificateur.tour() == 1
    [ntfy] = faux.ntfy
    assert ntfy["topic"] == SUJET
    assert ntfy["priority"] == 4  # urgent (niveau par défaut), réglage priorites_ntfy
    assert ntfy["title"] == "URGENT : alarme spray"
    assert "flacon vide" in ntfy["message"] and "Quoi faire : Changer le flacon." in ntfy["message"]
    assert "(étape « pomper »)" in ntfy["message"] and "10:00" in ntfy["message"]
    assert ntfy["click"] == banc.reglages.lien_page
    assert banc.reglages.lien_page in ntfy["message"]
    [telegram] = faux.telegram
    assert telegram["chat_id"] == "1111" and "flacon vide" in telegram["text"]
    assert telegram["disable_notification"] is False
    assert banc.etat("ntfy") == ["envoye"] and banc.etat("telegram") == ["envoye"]


def test_le_jeton_ntfy_est_envoye_s_il_est_rempli(registre, horloge, programme, faux):
    banc = Banc(registre, horloge, programme, secrets_de(faux, ntfy_jeton=SecretStr("tk_abc")))
    ouvrir_alarme(registre)
    banc.notificateur.tour()
    assert faux.entetes[0]["Authorization"] == "Bearer tk_abc"


def test_le_niveau_vient_des_reglages_le_plus_precis_gagne(registre, horloge, programme, faux):
    niveaux = {**programme.notifications.niveaux, "spray": "normal", "spray.pomper": "info"}
    banc = Banc(registre, horloge, programme, secrets_de(faux), niveaux=niveaux)
    n = banc.notificateur
    assert n.niveau("spray", "pomper") == "info"
    assert n.niveau("spray", "autre") == "normal"
    assert n.niveau("inconnu", None) == "urgent"  # niveau par défaut réglé
    ouvrir_alarme(registre)
    n.tour()
    assert faux.ntfy[0]["priority"] == 2 and faux.ntfy[0]["title"] == "alarme spray"
    assert faux.telegram[0]["disable_notification"] is True


def test_jamais_deux_fois_le_meme_message_meme_apres_un_redemarrage(banc, faux, registre):
    ouvrir_alarme(registre)
    banc.notificateur.tour()
    banc.notificateur.tour()
    assert len(faux.ntfy) == 1
    autre = Notificateur(
        registre, banc.reglages, banc.facteur, horloge=banc.horloge
    )  # le programme redémarre
    assert autre.tour() == 0
    assert len(faux.ntfy) == 1


def test_une_alarme_effacee_avant_le_depart_n_est_pas_annoncee(banc, faux, registre):
    numero = ouvrir_alarme(registre)
    registre.acquitter_alarme(numero, "karulium")
    assert banc.notificateur.tour() == 0 and faux.ntfy == []


def test_l_erreur_d_un_morceau_n_empeche_pas_les_autres(banc, faux, registre, monkeypatch):
    def plante():
        raise RuntimeError("panne")

    monkeypatch.setattr(banc.notificateur, "_fin_de_fut", plante)
    ouvrir_alarme(registre)
    assert banc.notificateur.tour() == 1


# ------------------------------------------------------------ sans réseau


def test_sans_reseau_les_messages_attendent_puis_partent_dans_l_ordre_sans_doublon(
    banc, faux, registre
):
    faux.en_panne = True
    ouvrir_alarme(registre, message="première")
    banc.notificateur.tour()
    banc.avancer(minutes=2)
    ouvrir_alarme(registre, message="deuxième")
    banc.notificateur.tour()
    assert faux.ntfy == [] and banc.etat("ntfy") == ["attente", "attente"]
    [premier, _] = banc.facteur.en_attente("ntfy")
    assert premier["essais"] >= 1 and "503" in premier["derniere_erreur"]
    # Le réseau revient : tout part, le plus vieux d'abord, une seule fois.
    faux.en_panne = False
    banc.avancer(minutes=61)
    assert banc.facteur.tournee() == 4
    assert ["première" in m["message"] for m in faux.ntfy] == [True, False]
    assert "deuxième" in faux.ntfy[1]["message"]
    banc.avancer(minutes=61)
    assert banc.facteur.tournee() == 0
    assert len(faux.ntfy) == 2


def test_un_message_trop_vieux_est_marque_en_retard(banc, faux, registre):
    faux.en_panne = True
    ouvrir_alarme(registre)
    banc.notificateur.tour()
    faux.en_panne = False
    banc.avancer(minutes=banc.reglages.en_retard_apres_min + 5)
    banc.facteur.tournee()
    assert faux.ntfy[0]["title"].endswith("(en retard)")
    assert "préparé à 10:00" in faux.ntfy[0]["message"]


def test_un_message_recent_n_est_pas_en_retard(banc, faux, registre):
    ouvrir_alarme(registre)
    banc.notificateur.tour()
    assert "retard" not in faux.ntfy[0]["title"]


def test_un_serveur_eteint_ne_fait_pas_planter_le_notificateur(registre, horloge, programme, faux):
    faux.arreter()  # plus personne n'écoute : connexion refusée
    banc = Banc(registre, horloge, programme, secrets_de(faux))
    ouvrir_alarme(registre)
    assert banc.notificateur.tour() == 1
    assert banc.etat("ntfy") == ["attente"]
    [envoi] = banc.facteur.en_attente("ntfy")
    assert "injoignable" in envoi["derniere_erreur"]
    assert JETON_BOT not in (envoi["derniere_erreur"] or "")
    [envoi] = banc.facteur.en_attente("telegram")
    assert JETON_BOT not in (envoi["derniere_erreur"] or "")


# ------------------------------------------------------------ heures calmes


def test_les_heures_calmes_traversent_minuit(programme, horloge):
    reglages = programme.notifications
    nuit = datetime(2026, 11, 9, 23, 0, tzinfo=GUADELOUPE)
    assert en_heures_calmes(reglages, nuit)
    assert en_heures_calmes(reglages, datetime(2026, 11, 10, 5, 59, tzinfo=GUADELOUPE))
    assert not en_heures_calmes(reglages, datetime(2026, 11, 10, 6, 0, tzinfo=GUADELOUPE))
    assert not en_heures_calmes(reglages, horloge.moment)
    jour = reglages.model_copy(
        update={"heures_calmes": SimpleNamespace(debut="13:00", fin="13:00")}
    )
    assert not en_heures_calmes(jour, nuit)


def test_la_nuit_seuls_les_urgents_partent(registre, horloge, programme, faux):
    niveaux = {**programme.notifications.niveaux, "spray": "normal"}
    banc = Banc(registre, horloge, programme, secrets_de(faux), niveaux=niveaux)
    horloge.moment = datetime(2026, 11, 9, 23, 30, tzinfo=GUADELOUPE)
    ouvrir_alarme(registre, module="spray", message="normale de nuit")
    ouvrir_alarme(registre, module="portique", message="urgente de nuit")
    banc.notificateur.tour()
    assert [m["message"].split(" : ")[1].split("\n")[0] for m in faux.ntfy] == ["urgente de nuit"]
    # Le matin, la normale part (elle avait attendu dans le registre) ; l'urgente, pas vue,
    # est rappelée (mais pas renvoyée une 2ᵉ fois comme message de départ).
    horloge.moment = datetime(2026, 11, 10, 6, 5, tzinfo=GUADELOUPE)
    assert banc.notificateur.tour() == 2
    assert len(faux.ntfy) == 3 and "normale de nuit" in faux.ntfy[1]["message"]
    assert faux.ntfy[2]["title"].startswith("RAPPEL URGENT")


def test_une_normale_effacee_pendant_la_nuit_n_est_jamais_envoyee(
    registre, horloge, programme, faux
):
    niveaux = {**programme.notifications.niveaux, "spray": "normal"}
    banc = Banc(registre, horloge, programme, secrets_de(faux), niveaux=niveaux)
    horloge.moment = datetime(2026, 11, 9, 23, 30, tzinfo=GUADELOUPE)
    numero = ouvrir_alarme(registre, module="spray")
    banc.notificateur.tour()
    registre.acquitter_alarme(numero, "karulium")
    horloge.moment = datetime(2026, 11, 10, 6, 5, tzinfo=GUADELOUPE)
    assert banc.notificateur.tour() == 0 and faux.ntfy == []


# ------------------------------------------------------------ escalade (63)


def test_escalade_rappel_puis_renfort(registre, horloge, programme, faux):
    secrets = secrets_de(
        faux,
        ntfy_sujets_renfort=[SecretStr(SUJET_2)],
        telegram_chats_renfort=[SecretStr("2222")],
    )
    banc = Banc(registre, horloge, programme, secrets)
    numero = ouvrir_alarme(registre)
    n = banc.notificateur
    assert n.tour() == 1
    # Avant le délai : rien de plus.
    banc.avancer(minutes=14)
    assert n.tour() == 0
    # Au 1er délai : renvoyée en priorité haute, aux mêmes destinataires.
    banc.avancer(minutes=2)
    assert n.tour() == 1
    rappel = faux.ntfy[1]
    assert rappel["topic"] == SUJET and rappel["priority"] == 5
    assert (
        rappel["title"].startswith("RAPPEL URGENT") and "Pas vue depuis 16 min" in rappel["message"]
    )
    assert "« J'ai vu »" in rappel["message"] and banc.reglages.lien_page in rappel["message"]
    assert n.tour() == 0  # une seule fois
    # Au 2ᵉ délai : envoyée aussi à la 2ᵉ liste.
    banc.avancer(minutes=30)
    assert n.tour() == 1
    assert [m["topic"] for m in faux.ntfy] == [SUJET, SUJET, SUJET_2]
    assert [m["chat_id"] for m in faux.telegram] == ["1111", "1111", "2222"]
    assert n.tour() == 0
    banc.avancer(minutes=60)
    assert n.tour() == 0
    assert registre.lire("SELECT vue_le FROM alarmes WHERE id = ?", (numero,))[0]["vue_le"] is None


def test_sans_deuxieme_liste_l_escalade_s_arrete_au_rappel(banc, faux, registre):
    ouvrir_alarme(registre)
    banc.notificateur.tour()
    banc.avancer(minutes=50)
    banc.notificateur.tour()
    assert len(faux.ntfy) == 2  # message + rappel, pas de renfort
    assert [m["topic"] for m in faux.ntfy] == [SUJET, SUJET]


def test_j_ai_vu_arrete_l_escalade(banc, faux, registre):
    numero = ouvrir_alarme(registre)
    banc.notificateur.tour()
    assert registre.noter_alarme_vue(numero, "employé (aide, 192.168.1.20)") is True
    assert registre.noter_alarme_vue(numero, "autre") is False  # la 1ʳᵉ vue est gardée
    banc.avancer(minutes=120)
    assert banc.notificateur.tour() == 0 and len(faux.ntfy) == 1
    ligne = registre.lire("SELECT * FROM alarmes WHERE id = ?", (numero,))[0]
    assert ligne["vue_par"] == "employé (aide, 192.168.1.20)" and ligne["acquittee_le"] is None
    assert numero in [a["id"] for a in registre.alarmes_ouvertes()]


def test_une_alarme_effacee_arrete_l_escalade(banc, faux, registre):
    numero = ouvrir_alarme(registre)
    banc.notificateur.tour()
    registre.acquitter_alarme(numero, "karulium")
    banc.avancer(minutes=120)
    assert banc.notificateur.tour() == 0 and len(faux.ntfy) == 1


def test_une_alarme_pas_urgente_n_escalade_pas(registre, horloge, programme, faux):
    niveaux = {**programme.notifications.niveaux, "spray": "normal"}
    banc = Banc(registre, horloge, programme, secrets_de(faux), niveaux=niveaux)
    ouvrir_alarme(registre, module="spray")
    banc.notificateur.tour()
    banc.avancer(minutes=120)
    assert banc.notificateur.tour() == 0 and len(faux.ntfy) == 1


def test_un_rappel_en_attente_ne_part_pas_si_l_alarme_a_ete_vue_entre_temps(banc, faux, registre):
    numero = ouvrir_alarme(registre)
    banc.notificateur.tour()
    faux.en_panne = True
    banc.avancer(minutes=16)
    banc.notificateur.tour()  # le rappel est préparé mais ne peut pas partir
    assert banc.etat("ntfy") == ["envoye", "attente"]
    registre.noter_alarme_vue(numero, "karulium")
    faux.en_panne = False
    banc.avancer(minutes=61)
    banc.facteur.tournee()
    assert len(faux.ntfy) == 1  # le rappel est abandonné, pas envoyé
    assert banc.etat("ntfy") == ["envoye", "envoye"]


# ------------------------------------------------------------ fin de fût, nettoyage, entretien (61)


def finir_un_fut(registre, horloge, module="poste_fut", seaux=2):
    cycle = registre.commencer_cycle(module, fut="F3")
    for numero in range(seaux):
        registre.ajouter_seau(cycle, f"S{100 + numero}")
    horloge.moment += timedelta(minutes=10)
    registre.finir_cycle(cycle)
    return cycle


def test_fin_de_fut(banc, faux, registre, horloge):
    finir_un_fut(registre, horloge)
    banc.notificateur.tour()
    [message] = faux.ntfy
    assert message["title"] == "Fin de fût" and message["priority"] == 2  # info
    assert "Fût F3 vidé à 10:10 : 2 seau(x) rempli(s)." in message["message"]
    banc.notificateur.tour()
    assert len(faux.ntfy) == 1


def test_un_cycle_abandonne_n_est_pas_une_fin_de_fut(banc, faux, registre, horloge):
    cycle = registre.commencer_cycle("poste_fut", fut="F3")
    registre.finir_cycle(cycle, "abandonne")
    banc.notificateur.tour()
    assert faux.ntfy == []


def test_nettoyage_a_faire_apres_le_delai(banc, faux, registre, horloge):
    finir_un_fut(registre, horloge)
    banc.notificateur.tour()
    assert len(faux.ntfy) == 1  # seulement la fin de fût
    banc.avancer(minutes=banc.reglages.evenements.nettoyage_apres_min + 1)
    banc.notificateur.tour()
    assert [m["title"] for m in faux.ntfy] == ["Fin de fût", "Nettoyage à faire"]
    assert faux.ntfy[1]["priority"] == 3 and "Lancer le nettoyage" in faux.ntfy[1]["message"]


def test_pas_de_rappel_si_le_nettoyage_a_commence(banc, faux, registre, horloge):
    finir_un_fut(registre, horloge)
    horloge.moment += timedelta(minutes=5)
    registre.commencer_cycle("nettoyage")
    banc.avancer(minutes=120)
    banc.notificateur.tour()
    assert [m["title"] for m in faux.ntfy] == ["Fin de fût"]


def piece(niveau="a_faire", depuis="2026-11-01T08:00:00-04:00"):
    return SimpleNamespace(
        nom="vanne_vide",
        description="Vanne de vidange",
        niveau=niveau,
        usure=5200.0,
        limite=5000.0,
        unite="manœuvres",
        exemple=True,
        a_faire="Changer la membrane.",
        depuis=depuis,
        pourcent=104.0,
    )


def test_piece_d_usure_a_faire(registre, horloge, programme, faux):
    pieces = [piece()]
    entretien = SimpleNamespace(etat=lambda: pieces)
    banc = Banc(registre, horloge, programme, secrets_de(faux), entretien=entretien)
    banc.notificateur.tour()
    [message] = faux.ntfy
    assert message["title"] == "Entretien à faire"
    assert (
        "Vanne de vidange : 5200 sur 5000 manœuvres (limite d'exemple). Changer la membrane."
        in (message["message"])
    )
    banc.notificateur.tour()
    assert len(faux.ntfy) == 1
    # Après « Fait » (nouveau point de départ) puis une nouvelle usure : annoncée de nouveau.
    pieces[:] = [piece(depuis="2026-11-09T10:30:00-04:00")]
    banc.notificateur.tour()
    assert len(faux.ntfy) == 2
    # « Bientôt » n'est pas annoncé (seulement dans le résumé du soir).
    pieces[:] = [piece(niveau="bientot", depuis="x")]
    banc.notificateur.tour()
    assert len(faux.ntfy) == 2


def test_calcul_conseille_est_pret_pour_plus_tard(banc, faux):
    assert banc.notificateur.annoncer(
        "calcul_conseille", "calcul:1", "Calcul conseillé", "À lancer."
    )
    assert not banc.notificateur.annoncer("calcul_conseille", "calcul:1", "Calcul conseillé", "À")
    assert faux.ntfy[0]["title"] == "Calcul conseillé" and faux.ntfy[0]["priority"] == 2


# ------------------------------------------------------------ résumé du soir (62)


def test_le_resume_part_a_l_heure_une_seule_fois(registre, horloge, programme, faux):
    entretien = SimpleNamespace(etat=lambda: [piece("bientot"), piece("ok")])
    banc = Banc(registre, horloge, programme, secrets_de(faux), entretien=entretien)
    finir_un_fut(registre, horloge, seaux=3)
    numero = ouvrir_alarme(registre, module="griffe", message="fût coincé")
    registre.acquitter_alarme(numero, "karulium")
    ouvrir_alarme(registre, module="spray", message="flacon vide")
    # Avant 19 h : rien (les autres messages sont déjà partis ou n'ont pas lieu d'être).
    horloge.moment = datetime(2026, 11, 9, 18, 59, tzinfo=GUADELOUPE)
    banc.notificateur.tour()
    assert not any(m["title"] == "Résumé du soir" for m in faux.ntfy)
    horloge.moment = datetime(2026, 11, 9, 19, 0, tzinfo=GUADELOUPE)
    banc.notificateur.tour()
    [resume] = [m for m in faux.ntfy if m["title"] == "Résumé du soir"]
    texte = resume["message"]
    assert "Seaux remplis : 3 (en 1 cycle(s))." in texte
    assert "Fûts vidés : 1." in texte
    assert "Alarmes : 2 (1 encore ouverte(s))." in texte
    assert "griffe : fût coincé" in texte and "spray : flacon vide" in texte
    assert "À faire demain :" in texte
    assert "Entretien, bientôt à faire : Vanne de vidange. Changer la membrane." in texte
    assert resume["priority"] == 2
    banc.notificateur.tour()
    assert len([m for m in faux.ntfy if m["title"] == "Résumé du soir"]) == 1
    # Le lendemain à 19 h : un nouveau résumé.
    horloge.moment = datetime(2026, 11, 10, 19, 5, tzinfo=GUADELOUPE)
    banc.notificateur.tour()
    assert len([m for m in faux.ntfy if m["title"] == "Résumé du soir"]) == 2


def test_resume_d_un_jour_sans_rien(banc, faux, horloge):
    horloge.moment = datetime(2026, 11, 9, 19, 0, tzinfo=GUADELOUPE)
    banc.notificateur.tour()
    texte = faux.ntfy[0]["message"]
    assert "Aucun seau rempli." in texte and "Aucune alarme." in texte
    assert "rien de prévu par le logiciel" in texte


def test_le_resume_attend_pas_au_dela_du_retard_permis(banc, faux, horloge):
    # Le Pi redémarre à 22 h 30 : trop tard pour le résumé de 19 h (retard permis : 3 h) ; et c'est
    # la nuit.
    horloge.moment = datetime(2026, 11, 9, 22, 30, tzinfo=GUADELOUPE)
    banc.notificateur.tour()
    assert faux.ntfy == []
    # Redémarré à 20 h : il part avec son retard.
    horloge.moment = datetime(2026, 11, 9, 20, 0, tzinfo=GUADELOUPE)
    banc.notificateur.tour()
    assert len(faux.ntfy) == 1


def test_resume_coupe_par_les_reglages(registre, horloge, programme, faux):
    arret = programme.notifications.resume_soir.model_copy(update={"actif": False})
    banc = Banc(registre, horloge, programme, secrets_de(faux), resume_soir=arret)
    horloge.moment = datetime(2026, 11, 9, 19, 0, tzinfo=GUADELOUPE)
    banc.notificateur.tour()
    assert faux.ntfy == []


def test_le_resume_limite_le_nombre_d_alarmes_citees(banc, faux, registre, horloge):
    for numero in range(8):
        ouvrir_alarme(registre, module="spray", message=f"alarme numéro {numero}")
    banc.notificateur.tour()
    horloge.moment = datetime(2026, 11, 9, 19, 0, tzinfo=GUADELOUPE)
    texte = banc.notificateur.texte_resume(horloge.moment)
    assert "Alarmes : 8" in texte and "(et 3 plus ancienne(s))" in texte
    assert "alarme numéro 7" in texte and "alarme numéro 2" not in texte


# ------------------------------------------------------------ la file et la base


def test_la_montee_de_version_garde_la_file_et_marque_l_existant_comme_traite(tmp_path):
    chemin = tmp_path / "registre.sqlite"
    ancienne = sqlite3.connect(chemin)
    for numero in range(1, 9):
        for instruction in module_montees.MONTEES[numero - 1]:
            ancienne.execute(instruction)
    ancienne.execute("PRAGMA user_version = 8")
    ancienne.execute(
        "INSERT INTO alarmes (quand, module, message) "
        "VALUES ('2026-11-08T10:00:00-04:00', 'a', 'x')"
    )
    ancienne.execute(
        "INSERT INTO envois (cle, destination, sorte, objet, cree_le, statut, essais) "
        "VALUES ('k1', 'secours', 'fichier', 'registre.sqlite', '2026-11-08T10:00:00-04:00', "
        "'attente', 3)"
    )
    ancienne.commit()
    ancienne.close()
    registre = Registre(chemin, tmp_path / "photos")
    try:
        assert registre.version == module_montees.VERSION
        [envoi] = registre.lire("SELECT * FROM envois")
        assert (envoi["cle"], envoi["essais"], envoi["statut"]) == ("k1", 3, "attente")
        assert registre.notification_faite("alarme:1") is not None
        registre.ajouter_envoi("ntfy", "message", "alarme:2", contenu="{}")
        assert registre.lire("SELECT contenu FROM envois WHERE destination = 'ntfy'")
        # La table refaite garde les contraintes.
        with pytest.raises(ErreurRegistre, match="CHECK"):
            registre.ajouter_envoi("inconnue", "message", "x")
    finally:
        registre.fermer()
