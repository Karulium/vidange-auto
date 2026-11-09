"""Les chiffres de l'onglet « Statistiques » : par jour, par semaine ou par mois.

    stats = Statistiques(registre, reglages.programme.statistiques)
    stats.calculer("semaine")

Tout vient du registre (cycles, seaux remplis, alarmes) : rien n'est estimé ni inventé. Ce que
chaque chiffre veut dire (la page le répète) :
  - seaux : seaux remplis pendant la période (heure où ils sont notés dans le registre) ;
  - cycles : cycles commencés pendant la période, avec leur issue (terminés, abandonnés, ouverts) ;
  - durée moyenne par seau : durée des cycles TERMINÉS pendant la période qui ont rempli des seaux,
    divisée par leur nombre de seaux (pauses comprises : le registre ne note pas les pauses) ;
  - alarmes : alarmes levées pendant la période, par module ;
  - marche : temps où au moins un cycle tournait (les cycles de plusieurs modules qui se
    chevauchent ne comptent qu'une fois) ; arrêt : le reste de la période écoulée.

Une période commence à minuit, heure du Pi (la semaine le lundi, le mois le 1er). La dernière
période est la période en cours : son arrêt ne compte que jusqu'à maintenant.
"""

from collections.abc import Callable
from datetime import datetime, time, timedelta
from typing import Any, Literal

from vidange.registre import Registre
from vidange.registre.base import maintenant
from vidange.reglages import ReglagesStatistiques

Echelle = Literal["jour", "semaine", "mois"]
ECHELLES: tuple[Echelle, ...] = ("jour", "semaine", "mois")


def _minuit(jour: datetime) -> datetime:
    return datetime.combine(jour.date(), time.min, tzinfo=jour.tzinfo)


def _debut_de_periode(moment: datetime, echelle: Echelle) -> datetime:
    minuit = _minuit(moment)
    if echelle == "jour":
        return minuit
    if echelle == "semaine":
        return minuit - timedelta(days=minuit.weekday())
    return minuit.replace(day=1)


def _periode_suivante(debut: datetime, echelle: Echelle) -> datetime:
    if echelle == "jour":
        return _minuit(debut + timedelta(days=1, hours=12))
    if echelle == "semaine":
        return _minuit(debut + timedelta(days=7, hours=12))
    return _minuit(debut.replace(day=28) + timedelta(days=4, hours=12)).replace(day=1)


def _periode_precedente(debut: datetime, echelle: Echelle) -> datetime:
    if echelle == "jour":
        return _minuit(debut - timedelta(hours=12))
    if echelle == "semaine":
        return _minuit(debut - timedelta(days=7) + timedelta(hours=12))
    return _debut_de_periode(debut - timedelta(hours=12), "mois")


def _lire_heure(texte: str | None, fuseau: Any) -> datetime | None:
    if not texte:
        return None
    try:
        return datetime.fromisoformat(texte).astimezone(fuseau)
    except ValueError:
        return None


def _union_s(intervalles: list[tuple[datetime, datetime]], debut: datetime, fin: datetime) -> float:
    """Secondes couvertes par les intervalles, coupés à [debut, fin[ et sans compter deux fois."""
    coupes = sorted(
        (max(a, debut), min(b, fin)) for a, b in intervalles if a < fin and b > debut and a < b
    )
    total = 0.0
    courant_fin: datetime | None = None
    courant_debut: datetime | None = None
    for a, b in coupes:
        if courant_fin is None or a > courant_fin:
            if courant_debut is not None and courant_fin is not None:
                total += (courant_fin - courant_debut).total_seconds()
            courant_debut, courant_fin = a, b
        elif b > courant_fin:
            courant_fin = b
    if courant_debut is not None and courant_fin is not None:
        total += (courant_fin - courant_debut).total_seconds()
    return total


class Statistiques:
    def __init__(
        self,
        registre: Registre,
        reglages: ReglagesStatistiques,
        horloge: Callable[[], datetime] = maintenant,
    ) -> None:
        self.registre = registre
        self.reglages = reglages
        self._horloge = horloge

    def periodes(self, echelle: Echelle, maintenant_: datetime) -> list[tuple[datetime, datetime]]:
        """Les périodes montrées, de la plus ancienne à la période en cours."""
        nombre = {
            "jour": self.reglages.jours,
            "semaine": self.reglages.semaines,
            "mois": self.reglages.mois,
        }[echelle]
        debut = _debut_de_periode(maintenant_, echelle)
        resultat = []
        for _ in range(nombre):
            resultat.append((debut, _periode_suivante(debut, echelle)))
            debut = _periode_precedente(debut, echelle)
        resultat.reverse()
        return resultat

    def calculer(self, echelle: Echelle) -> dict[str, Any]:
        """Une ligne par période (la plus récente à la fin), et les modules qui ont des alarmes."""
        maintenant_ = self._horloge()
        fuseau = maintenant_.tzinfo
        periodes = self.periodes(echelle, maintenant_)
        depart = periodes[0][0]
        # Marge d'un jour sur la date cherchée dans la base (les heures y sont du texte).
        borne = (depart - timedelta(days=2)).isoformat(timespec="seconds")
        cycles = self.registre.lire(
            "SELECT c.id, c.module, c.debut, c.fin, c.issue, "
            "(SELECT COUNT(*) FROM seaux_du_cycle s WHERE s.cycle_id = c.id) AS nombre_seaux "
            "FROM cycles c WHERE c.fin IS NULL OR c.fin >= ?",
            (borne,),
        )
        seaux = self.registre.lire(
            "SELECT quand FROM seaux_du_cycle WHERE quand >= ?",
            (borne,),
        )
        alarmes = self.registre.lire("SELECT quand, module FROM alarmes WHERE quand >= ?", (borne,))
        ouvert_max = timedelta(hours=self.reglages.cycle_ouvert_max_h)

        cycles_lus = []
        for cycle in cycles:
            debut = _lire_heure(cycle["debut"], fuseau)
            if debut is None:
                continue
            fin = _lire_heure(cycle["fin"], fuseau)
            cycles_lus.append((cycle, debut, fin))
        intervalles = [
            (debut, fin if fin is not None else min(maintenant_, debut + ouvert_max))
            for _, debut, fin in cycles_lus
        ]
        moments_seaux = [m for m in (_lire_heure(s["quand"], fuseau) for s in seaux) if m]
        moments_alarmes = [
            (m, a["module"]) for a in alarmes if (m := _lire_heure(a["quand"], fuseau)) is not None
        ]

        modules: set[str] = set()
        lignes = []
        for debut, fin in periodes:
            terminees = [
                (cycle, d, f)
                for cycle, d, f in cycles_lus
                if f is not None and debut <= f < fin and cycle["issue"] == "termine"
            ]
            avec_seaux = [(c, d, f) for c, d, f in terminees if c["nombre_seaux"] > 0]
            seaux_des_cycles = sum(c["nombre_seaux"] for c, _, _ in avec_seaux)
            duree = sum((f - d).total_seconds() for _, d, f in avec_seaux)
            commences = [(c, d, f) for c, d, f in cycles_lus if debut <= d < fin]
            par_module: dict[str, int] = {}
            for moment, module in moments_alarmes:
                if debut <= moment < fin:
                    par_module[module] = par_module.get(module, 0) + 1
            modules.update(par_module)
            ecoule_s = (min(fin, maintenant_) - debut).total_seconds()
            marche = min(_union_s(intervalles, debut, min(fin, maintenant_)), ecoule_s)
            lignes.append(
                {
                    "debut": debut.date().isoformat(),
                    "fin": fin.date().isoformat(),
                    "en_cours": debut <= maintenant_ < fin,
                    "seaux": sum(1 for m in moments_seaux if debut <= m < fin),
                    "cycles": len(commences),
                    "cycles_termines": sum(1 for c, _, _ in commences if c["issue"] == "termine"),
                    "cycles_abandonnes": sum(
                        1 for c, _, _ in commences if c["issue"] == "abandonne"
                    ),
                    "cycles_ouverts": sum(1 for c, _, _ in commences if c["issue"] is None),
                    "duree_moyenne_seau_s": (
                        duree / seaux_des_cycles if seaux_des_cycles else None
                    ),
                    "alarmes": par_module,
                    "alarmes_total": sum(par_module.values()),
                    "marche_s": marche,
                    "arret_s": max(ecoule_s - marche, 0.0),
                }
            )
        return {
            "echelle": echelle,
            "heure": maintenant_.isoformat(timespec="seconds"),
            "modules": sorted(modules),
            "periodes": lignes,
        }
