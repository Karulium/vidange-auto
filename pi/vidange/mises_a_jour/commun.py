"""Ce qui sert à toutes les mises à jour : l'erreur, et le lancement d'une commande."""

import os
import subprocess
from collections.abc import Callable, Mapping

# Lance une commande et rend ce qu'elle a écrit ; lève ErreurMiseAJour si elle échoue.
# (commande, durée maximale en s, dossier où la lancer, variables d'environnement en plus)
Lanceur = Callable[..., str]


class ErreurMiseAJour(Exception):
    """Mise à jour refusée ou ratée (avec la raison, en clair)."""


def lancer_commande(
    commande: list[str],
    duree_max_s: float,
    dossier: str | None = None,
    variables: Mapping[str, str] | None = None,
) -> str:
    """Lance une commande du système et rend sa sortie (les deux : normale et erreurs)."""
    environnement = {**os.environ, **(variables or {})}
    nom = " ".join(commande[:4])
    try:
        fini = subprocess.run(
            commande,
            capture_output=True,
            text=True,
            timeout=duree_max_s,
            cwd=dossier,
            env=environnement,
        )
    except subprocess.TimeoutExpired:
        raise ErreurMiseAJour(f"« {nom} » : trop long (plus de {duree_max_s:g} s)") from None
    except OSError as erreur:
        raise ErreurMiseAJour(f"« {nom} » impossible à lancer : {erreur}") from None
    sortie = (fini.stdout or "") + (fini.stderr or "")
    if fini.returncode != 0:
        dernieres = [ligne.strip() for ligne in sortie.splitlines() if ligne.strip()][-3:]
        raise ErreurMiseAJour(
            f"« {nom} » a échoué (code {fini.returncode}) : {' / '.join(dernieres) or 'rien dit'}"
        )
    return sortie
