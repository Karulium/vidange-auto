"""Le planning rendu par le simulateur : qui fait quoi, quand, et le temps total.

Heures en secondes depuis le début de la simulation. `en_texte()` pour le lire,
`en_dict()` pour un fichier JSON (page web, solveur, comparaisons plus tard).
"""

from dataclasses import dataclass, field
from typing import Any

from vidange.simulateur.axes import Mouvement


@dataclass
class LignePlanning:
    """Une étape faite (ou commencée) par un module."""

    module: str
    etape: str
    numero: int  # de 1 à nombre_etapes
    nombre_etapes: int
    # L'étape devient celle du module.
    debut: float
    # Go de Karulium (None : l'étape ne l'a pas demandé).
    go: float | None = None
    # Conditions d'entrée remplies et zones prises : l'action part.
    action: float | None = None
    # Condition de fin remplie (None : pas finie, alarme ou blocage).
    fin: float | None = None
    # Ce que l'étape a attendu avant son action (conditions, zones), en clair.
    attentes: list[str] = field(default_factory=list)
    mouvements: list[Mouvement] = field(default_factory=list)
    # Zones tenues par le module pendant le geste.
    zones: tuple[str, ...] = ()
    # Zones attendues parce qu'un autre module les tenait (solveur, tâche 23).
    zones_attendues: list[str] = field(default_factory=list)
    # L'étape a attendu une condition d'entrée (autre chose qu'une zone ou le Go).
    attend_condition: bool = False

    @property
    def attente_go(self) -> float:
        return 0.0 if self.go is None else self.go - self.debut

    @property
    def attente_entree(self) -> float:
        if self.action is None:
            return 0.0
        return self.action - (self.go if self.go is not None else self.debut)

    @property
    def geste(self) -> float:
        if self.action is None or self.fin is None:
            return 0.0
        return self.fin - self.action


@dataclass
class Planning:
    modules: list[str]
    lignes: list[LignePlanning]
    # Heure (s) où le dernier module a fini, ou où la simulation s'est arrêtée.
    temps_total: float
    # Ce que la machine imaginaire a fait toute seule : (heure, texte).
    evenements: list[tuple[float, str]] = field(default_factory=list)
    # Vide si le cycle est allé au bout ; sinon pourquoi il s'est arrêté (alarme, blocage).
    probleme: str = ""
    # Réglages d'exemple (valeurs inventées).
    exemple: bool = False
    # Un programme du solveur a été donné au chef (tâche 23), et pourquoi il a été abandonné ("" :
    # suivi jusqu'au bout).
    programme_joue: bool = False
    recul_programme: str = ""

    @property
    def fini(self) -> bool:
        return not self.probleme

    def en_texte(self) -> str:
        noms = ", ".join(f"« {nom} »" for nom in self.modules)
        lignes = [f"Simulation du cycle : module(s) {noms}"]
        if self.exemple:
            lignes.append(
                "ATTENTION : réglages d'EXEMPLE (valeurs inventées), ce planning ne dit rien "
                "de la vraie machine."
            )
        lignes.append("")
        blocs: list[tuple[float, int, list[str]]] = []
        for ligne in self.lignes:
            blocs.append((ligne.debut, 1, _decrire(ligne)))
        for heure, texte in self.evenements:
            blocs.append((heure, 0, [f"{heure_lisible(heure)}  (simulé) {texte}"]))
        for _, _, bloc in sorted(blocs, key=lambda bloc: (bloc[0], bloc[1])):
            lignes.extend(bloc)
        lignes.append("")
        if self.probleme:
            lignes.append(f"CYCLE ARRÊTÉ à {heure_lisible(self.temps_total)} : {self.probleme}")
        else:
            lignes.append(f"Temps total : {duree_lisible(self.temps_total)}")
        for module in self.modules:
            siennes = [ligne for ligne in self.lignes if ligne.module == module]
            lignes.append(
                f"  {module} : gestes {duree_lisible(sum(ligne.geste for ligne in siennes))}, "
                f"attente du Go {duree_lisible(sum(ligne.attente_go for ligne in siennes))}, "
                f"autres attentes {duree_lisible(sum(ligne.attente_entree for ligne in siennes))}"
            )
        return "\n".join(lignes)

    def en_dict(self) -> dict[str, Any]:
        return {
            "modules": self.modules,
            "exemple": self.exemple,
            "fini": self.fini,
            "probleme": self.probleme,
            "temps_total_s": _arrondi(self.temps_total),
            "etapes": [
                {
                    "module": ligne.module,
                    "etape": ligne.etape,
                    "numero": ligne.numero,
                    "debut_s": _arrondi(ligne.debut),
                    "go_s": _arrondi(ligne.go),
                    "action_s": _arrondi(ligne.action),
                    "fin_s": _arrondi(ligne.fin),
                    "attente_go_s": _arrondi(ligne.attente_go),
                    "attente_entree_s": _arrondi(ligne.attente_entree),
                    "geste_s": _arrondi(ligne.geste),
                    "attentes": ligne.attentes,
                    "zones": list(ligne.zones),
                    "mouvements": [
                        {
                            "position": mouvement.position,
                            "debut_s": _arrondi(mouvement.debut),
                            "fin_s": _arrondi(mouvement.fin),
                            "axes": {
                                axe: [_arrondi(depart), _arrondi(arrivee)]
                                for axe, (depart, arrivee) in mouvement.axes.items()
                            },
                        }
                        for mouvement in ligne.mouvements
                    ],
                }
                for ligne in self.lignes
            ],
            "evenements": [
                {"heure_s": _arrondi(heure), "texte": texte} for heure, texte in self.evenements
            ],
        }


def _decrire(ligne: LignePlanning) -> list[str]:
    fin = heure_lisible(ligne.fin) if ligne.fin is not None else "pas finie"
    duree = f" ({duree_lisible(ligne.fin - ligne.debut)})" if ligne.fin is not None else ""
    texte = [
        f"{heure_lisible(ligne.debut)} → {fin}  {ligne.module}, étape {ligne.numero}/"
        f"{ligne.nombre_etapes} « {ligne.etape} »{duree}"
    ]
    if ligne.go is not None:
        texte.append(f"    attend le Go de Karulium : {duree_lisible(ligne.attente_go)}")
    if ligne.attente_entree > 0 or ligne.attentes:
        attendu = " ; ".join(ligne.attentes) or "conditions d'entrée"
        texte.append(f"    attend {duree_lisible(ligne.attente_entree)} : {attendu}")
    if ligne.zones:
        texte.append(f"    zones tenues : {', '.join(ligne.zones)}")
    for mouvement in ligne.mouvements:
        texte.append(f"    va à « {mouvement.position} » ({', '.join(mouvement.axes)})")
    if ligne.action is not None and ligne.fin is not None:
        texte.append(f"    geste : {duree_lisible(ligne.geste)}")
    return texte


def heure_lisible(secondes: float) -> str:
    """« 01:02,5 » (minutes:secondes), ou « 1:02:03,5 » au-delà d'une heure."""
    dixiemes = round(secondes * 10)
    heures, reste = divmod(dixiemes, 36_000)
    minutes, reste = divmod(reste, 600)
    texte = f"{minutes:02d}:{reste // 10:02d},{reste % 10}"
    return f"{heures}:{texte}" if heures else texte


def duree_lisible(secondes: float) -> str:
    """« 4,2 s », « 3 min 05 s », « 1 h 02 min »."""
    if round(secondes, 1) < 60:
        return f"{secondes:.1f} s".replace(".", ",")
    entieres = round(secondes)
    if entieres < 3600:
        return f"{entieres // 60} min {entieres % 60:02d} s"
    return f"{entieres // 3600} h {entieres % 3600 // 60:02d} min"


def _arrondi(valeur: float | None) -> float | None:
    return None if valeur is None else round(valeur, 3)
