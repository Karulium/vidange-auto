"""Les données d'un cycle telles que le logiciel de culture les reçoit (format décrit dans
docs/django.md, partie « Format exact d'un cycle »).

Elles sont lues dans le registre au moment de l'envoi (pas au moment où le cycle finit) :
une alarme acquittée entre-temps part acquittée.
"""

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from vidange.registre import ErreurRegistre, Registre

# Numéro du format : il change si le format change d'une façon que l'app « machine » doit savoir.
FORMAT = 1

# Les codes des objets cités par une ligne de mesure ou de photo (alias « t »).
_OBJETS = """
    LEFT JOIN futs f ON f.id = t.fut_id
    LEFT JOIN seaux s ON s.id = t.seau_id
    LEFT JOIN bocaux b ON b.id = t.bocal_id
    LEFT JOIN petris p ON p.id = t.petri_id
"""
_CODES = "f.code AS fut, s.code AS seau, b.code AS bocal, p.code AS petri"


def heure_locale(texte: str | None, fuseau: ZoneInfo) -> str | None:
    """Une heure du registre (avec décalage) → heure locale sans fuseau, à la seconde
    (« 2026-10-27T08:12:03 »), comme le logiciel de culture les range (USE_TZ = False)."""
    if texte is None:
        return None
    moment = datetime.fromisoformat(texte).astimezone(fuseau)
    return moment.replace(tzinfo=None).isoformat(timespec="seconds")


def donnees_cycle(
    registre: Registre, cycle: int, cle: str, machine: str, fuseau: ZoneInfo
) -> dict[str, Any]:
    """Tout ce que le registre sait d'un cycle, prêt à être écrit en JSON."""

    def h(texte: str | None) -> str | None:
        return heure_locale(texte, fuseau)

    lignes = registre.lire(
        "SELECT c.*, f.code AS fut FROM cycles c LEFT JOIN futs f ON f.id = c.fut_id "
        "WHERE c.id = ?",
        (cycle,),
    )
    if not lignes:
        raise ErreurRegistre(f"cycle n° {cycle} inconnu")
    c = lignes[0]

    doses: dict[int, list[dict[str, Any]]] = {}
    bocaux: list[str] = []
    for dose in registre.lire(
        "SELECT d.seau_du_cycle_id, d.quantite_g, d.couche, d.quand, b.code FROM doses_mycelium d "
        "JOIN bocaux b ON b.id = d.bocal_id "
        "JOIN seaux_du_cycle sc ON sc.id = d.seau_du_cycle_id "
        "WHERE sc.cycle_id = ? ORDER BY d.id",
        (cycle,),
    ):
        doses.setdefault(dose["seau_du_cycle_id"], []).append(
            {
                "bocal": dose["code"],
                "quantite_g": dose["quantite_g"],
                "couche": dose["couche"],
                "quand": h(dose["quand"]),
            }
        )
        if dose["code"] not in bocaux:
            bocaux.append(dose["code"])

    seaux = [
        {
            "seau": seau["code"],
            "type_seau": seau["type_seau"],
            "quand": h(seau["quand"]),
            "defaut": seau["defaut"],
            "doses": doses.get(seau["id"], []),
        }
        for seau in registre.lire(
            "SELECT sc.id, sc.quand, s.code, s.type_seau, s.defaut FROM seaux_du_cycle sc "
            "JOIN seaux s ON s.id = sc.seau_id WHERE sc.cycle_id = ? ORDER BY sc.id",
            (cycle,),
        )
    ]
    etapes = [
        {
            "etape": e["etape"],
            "debut": h(e["debut"]),
            "fin": h(e["fin"]),
            "duree_s": e["duree_s"],
            "issue": e["issue"],
        }
        for e in registre.lire(
            "SELECT * FROM etapes_faites WHERE cycle_id = ? ORDER BY id", (cycle,)
        )
    ]
    mesures = [
        {
            "nom": m["nom"],
            "valeur": m["valeur"],
            "unite": m["unite"],
            "capteur": m["capteur"],
            "quand": h(m["quand"]),
            "fut": m["fut"],
            "seau": m["seau"],
            "bocal": m["bocal"],
            "petri": m["petri"],
        }
        for m in registre.lire(
            f"SELECT t.*, {_CODES} FROM mesures t {_OBJETS} WHERE t.cycle_id = ? ORDER BY t.id",
            (cycle,),
        )
    ]
    photos = [
        {
            "numero": p["id"],
            "quand": h(p["quand"]),
            "camera": p["camera"],
            "fichier": p["chemin"],
            "remarque": p["remarque"],
            "fut": p["fut"],
            "seau": p["seau"],
            "bocal": p["bocal"],
            "petri": p["petri"],
        }
        for p in registre.lire(
            f"SELECT t.*, {_CODES} FROM photos t {_OBJETS} WHERE t.cycle_id = ? ORDER BY t.id",
            (cycle,),
        )
    ]
    alarmes = [
        {
            "numero": a["id"],
            "quand": h(a["quand"]),
            "module": a["module"],
            "etape": a["etape"],
            "message": a["message"],
            "quoi_faire": a["quoi_faire"],
            "acquittee_le": h(a["acquittee_le"]),
            "acquittee_par": a["acquittee_par"],
        }
        for a in registre.lire("SELECT * FROM alarmes WHERE cycle_id = ? ORDER BY id", (cycle,))
    ]
    return {
        "format": FORMAT,
        "cle": cle,
        "machine": machine,
        "cycle": {
            "numero": c["id"],
            "module": c["module"],
            "debut": h(c["debut"]),
            "fin": h(c["fin"]),
            "issue": c["issue"],
            "fut": c["fut"],
            "remarque": c["remarque"],
        },
        "seaux": seaux,
        "bocaux": bocaux,
        "etapes": etapes,
        "mesures": mesures,
        "photos": photos,
        "alarmes": alarmes,
    }
