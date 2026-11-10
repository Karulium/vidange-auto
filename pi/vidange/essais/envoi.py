"""Un plan d'essais appliqué, tel que le logiciel de culture le reçoit (tâche 31).

Format décrit dans docs/django.md (« Les plans d'essais appliqués »). Les données sont lues dans le
registre au moment de l'envoi : chaque seau fait ajoute une ligne et remet le plan dans la file
(il part de plus en plus complet ; l'app « machine » remplace le précédent, reconnu par `plan.cle`).
"""

import json
from typing import Any
from zoneinfo import ZoneInfo

from vidange.envois.cycle import heure_locale
from vidange.registre import ErreurRegistre, Registre

# Numéro du format : il change si le format change d'une façon que l'app « machine » doit savoir.
FORMAT = 1


def donnees_plan(
    registre: Registre, plan: int, cle: str, machine: str, fuseau: ZoneInfo
) -> dict[str, Any]:
    """Le plan et, seau par seau, les valeurs vraiment appliquées, prêts à être écrits en JSON."""

    def h(texte: str | None) -> str | None:
        return heure_locale(texte, fuseau)

    lignes = registre.lire("SELECT * FROM plans_essais WHERE id = ?", (plan,))
    if not lignes:
        raise ErreurRegistre(f"plan d'essais n° {plan} inconnu")
    p = lignes[0]
    contenu = json.loads(p["contenu"])
    seaux: dict[int, dict[str, Any]] = {}
    for ligne in registre.lire(
        "SELECT e.*, s.code AS seau FROM essais_appliques e "
        "LEFT JOIN seaux s ON s.id = e.seau_id WHERE e.plan_id = ? ORDER BY e.numero, e.id",
        (plan,),
    ):
        seau = seaux.setdefault(ligne["numero"], {"numero": ligne["numero"], "seau": None})
        seau["seau"] = seau["seau"] or ligne["seau"]
        seau.setdefault("valeurs", []).append(
            {
                "variable": ligne["variable"],
                "voulu": json.loads(ligne["voulu"]),
                "mesure": ligne["mesure"],
                "unite": ligne["unite"],
                "couche": ligne["couche"],
                "quand": h(ligne["quand"]),
                "remarque": ligne["remarque"],
            }
        )
    return {
        "format": FORMAT,
        "cle": cle,
        "machine": machine,
        "plan": {
            "cle": p["cle"],
            "numero": p["id"],
            "nom": p["nom"],
            "auteur": p["auteur"],
            "remarque": contenu.get("remarque"),
            "etat": p["etat"],
            "lot": {"variete": p["variete"], "format": p["format"], "seaux": p["seaux"]},
            "charge_le": h(p["charge_le"]),
            "charge_par": p["charge_par"],
            "accepte_le": h(p["accepte_le"]),
            "accepte_par": p["accepte_par"],
            "lance_le": h(p["lance_le"]),
            "lance_par": p["lance_par"],
            "prevu": contenu["seaux"],
        },
        "seaux": [seaux[numero] for numero in sorted(seaux)],
    }
