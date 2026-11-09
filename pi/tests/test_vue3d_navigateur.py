"""La page de la vue 3D dans un vrai navigateur (Playwright, Chromium sans écran).

Ce test est « hors CI » : il se saute tout seul si `node`, la bibliothèque `playwright` ou son
navigateur manquent (GitHub Actions ne les installe pas). Il démarre le vrai serveur de l'API sur
un port libre, avec de fausses cartes dont les axes bougent, charge la page, ouvre l'onglet « Vue
3D », vérifie que la scène reçoit les boîtes et les positions, puis rejoue une alarme.

À la main, pour garder une capture d'écran de la vue : VUE3D_CAPTURE=/chemin/vue.png pytest ...
"""

import math
import os
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from vidange.api import ServeurApi, Services
from vidange.chef import Alarme
from vidange.fluidnc import EtatCarte
from vidange.reglages import charger_reglages
from vidange.vue3d import EnregistreurRejeu, Vue3d

from .conftest import DOSSIER_PI
from .test_api import CHEF, MOT_DE_PASSE, BancApi, creer_app_de_test, reglages_api

SCRIPT = Path(__file__).parent / "navigateur" / "verifier_vue3d.mjs"


def _navigateur_disponible() -> bool:
    if shutil.which("node") is None:
        return False
    essai = subprocess.run(
        ["node", "-e", "require('playwright')"], capture_output=True, timeout=30, check=False
    )
    return essai.returncode == 0


pytestmark = pytest.mark.skipif(
    not _navigateur_disponible(), reason="node ou playwright absent (test hors CI)"
)


def port_libre() -> int:
    with socket.socket() as prise:
        prise.bind(("127.0.0.1", 0))
        return prise.getsockname()[1]


class FaussesCartes:
    """Des cartes dont chaque axe va et vient dans sa course, pour faire bouger la vue."""

    def __init__(self, machine) -> None:
        self.machine = machine
        self.liaisons = {
            carte: SimpleNamespace(etat=EtatCarte(connectee=True))
            for carte in {a.carte for a in machine.axes.values() if a.carte}
        }
        self.depart = time.monotonic()
        self.fil = threading.Thread(target=self._bouger, daemon=True)
        self.arret = threading.Event()

    def _bouger(self) -> None:
        while not self.arret.is_set():
            t = time.monotonic() - self.depart
            for n, axe in enumerate(self.machine.axes.values()):
                if axe.carte is None or axe.lettre is None:
                    continue
                debut, fin = axe.course
                milieu, amplitude = (debut + fin) / 2, (fin - debut) / 2
                valeur = milieu + 0.8 * amplitude * math.sin(t * 0.8 + n)
                facteur = 1000 if axe.unite == "m" else 1
                self.liaisons[axe.carte].etat.positions[axe.lettre] = valeur * facteur
            time.sleep(0.05)


def test_la_vue_3d_dans_un_navigateur(tmp_path):
    reglages = charger_reglages(DOSSIER_PI / "reglages")
    cartes = FaussesCartes(reglages.machine)
    cartes.fil.start()
    banc = BancApi(tmp_path)
    try:
        zones = {"exemple_zone_a": "essai"}
        vue = Vue3d(reglages.vue3d, reglages.machine, cartes.liaisons, lambda: zones)
        rejeux = EnregistreurRejeu(tmp_path, reglages.vue3d.rejeu, vue.positions, vue.zones_tenues)
        # Un rejeu déjà écrit : 4 s de positions autour d'une alarme (des relevés de 0,2 s).
        alarme = Alarme("essai", "un", "tour pas suivi", "Voir la machine.", "2026-11-09T10:00:00")
        numero = banc.registre.noter_alarme("essai", alarme.message, alarme.quoi_faire, "un")
        horloge = [0.0]
        rejeux._horloge = lambda: horloge[0]
        for _ in range(20):
            horloge[0] += 0.2
            rejeux.echantillonner()
        rejeux.recevoir(alarme)
        rejeux.numero(alarme, numero)
        for _ in range(20):
            horloge[0] += 0.2
            rejeux.echantillonner()
        rejeux.terminer()
        assert rejeux.numeros() == [numero]

        services = Services(
            banc.chef,
            banc.registre,
            banc.bilans.acquitter,
            checklist=lambda: banc.constats,
            vue3d=vue,
            rejeux=rejeux,
        )
        app = creer_app_de_test(services, tmp_path)
        port = port_libre()
        serveur = ServeurApi(app, reglages_api(port))
        serveur.demarrer()
        try:
            assert serveur.en_route
            commande = [
                "node",
                str(SCRIPT),
                f"http://127.0.0.1:{port}",
                CHEF,
                MOT_DE_PASSE,
                str(len(reglages.vue3d.boites)),
                str(len(reglages.machine.zones)),
                str(numero),
            ]
            capture = os.environ.get("VUE3D_CAPTURE")
            if capture:
                commande.append(capture)
            fini = subprocess.run(
                commande, capture_output=True, text=True, timeout=120, check=False
            )
            assert fini.returncode == 0, fini.stderr + fini.stdout
        finally:
            serveur.arreter()
    finally:
        cartes.arret.set()
        banc.registre.fermer()
