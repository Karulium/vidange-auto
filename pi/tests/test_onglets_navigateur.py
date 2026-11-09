"""Les onglets Statistiques, Carnet, Réglages et l'appli installable dans un vrai navigateur.

Comme test_vue3d_navigateur.py : « hors CI », il se saute tout seul si `node`, `playwright` ou son
navigateur manquent. Il démarre le vrai serveur de l'API sur un port libre (127.0.0.1 est un
contexte sûr pour le navigateur : le service worker s'y installe), avec les vrais réglages du dépôt
(copiés), un registre rempli, et vérifie : les 5 graphiques, écrire / chercher / barrer une note,
changer un réglage (refus hors bornes, redémarrage annoncé, retour), l'onglet Réglages caché à un
employé, le service worker (cache de la coquille seulement, jamais l'API, rien d'ancien hors ligne).

À la main, pour garder des captures : ONGLETS_CAPTURES=/dossier pytest ...
"""

import os
import shutil
import socket
import subprocess
from pathlib import Path

import pytest

from vidange.api import ServeurApi, Services
from vidange.demarrage import erreurs_de_reglages
from vidange.modifiables import Modifiables
from vidange.reglages import charger_reglages
from vidange.statistiques import Statistiques

from .conftest import DOSSIER_PI
from .test_api import AIDE, CHEF, MOT_DE_PASSE, BancApi, creer_app_de_test, reglages_api

SCRIPT = Path(__file__).parent / "navigateur" / "verifier_onglets.mjs"


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


def test_les_onglets_dans_un_navigateur(tmp_path, reglages):
    banc = BancApi(tmp_path)
    try:
        registre = banc.registre
        cycle = registre.commencer_cycle("vidange")
        registre.ajouter_seau(cycle, "S1")
        registre.ajouter_seau(cycle, "S2")
        registre.finir_cycle(cycle)
        registre.noter_alarme("prehension", "dérapage", cycle=cycle)
        charges = charger_reglages(reglages)
        entrees = DOSSIER_PI.parent / "docs" / "entrees-sorties.yaml"
        services = Services(
            banc.chef,
            registre,
            banc.bilans.acquitter,
            checklist=lambda: banc.constats,
            statistiques=Statistiques(registre, charges.programme.statistiques),
            carnet=charges.programme.carnet,
            modifiables=Modifiables(
                charges.modifiables,
                charges,
                reglages,
                registre,
                lambda dossier: erreurs_de_reglages(dossier, entrees),
            ),
        )
        app = creer_app_de_test(services, tmp_path)
        port = port_libre()
        serveur = ServeurApi(app, reglages_api(port))
        serveur.demarrer()
        try:
            assert serveur.en_route
            commande = ["node", str(SCRIPT), f"http://127.0.0.1:{port}", CHEF, AIDE, MOT_DE_PASSE]
            captures = os.environ.get("ONGLETS_CAPTURES")
            if captures:
                commande.append(captures)
            fini = subprocess.run(
                commande, capture_output=True, text=True, timeout=180, check=False
            )
            assert fini.returncode == 0, fini.stderr + fini.stdout
        finally:
            serveur.arreter()
    finally:
        banc.registre.fermer()
