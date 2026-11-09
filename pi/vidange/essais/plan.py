"""Un plan d'essais : le lire, le vérifier, l'appliquer aux seaux d'un lot (tâche 31).

Format (YAML, ou JSON qui est du YAML) :

    nom: Dose de mycélium, essai 1
    auteur: PC de bureau
    remarque: trois doses, deux seaux témoins      # facultatif
    lot:
      variete: pleurote_grise
      format: seau_a
      seaux: 18
    seaux:                 # par numéro dans le lot (1 = le premier rempli)
      1: {mycelium_g: 100}
      2: {mycelium_g: 200, spray: false}
      5: {spray_g: 15}

Les seaux non cités, et les variables non citées d'un seau, prennent le réglage normal
(machine.yaml). Seules les variables de pi/reglages/essais.yaml sont permises, dans leurs bornes.
Toutes les erreurs sont dites en une fois, en français (ErreurPlan).
"""

import json
import math
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

import yaml

from vidange.essais.variables import SPRAY, SPRAY_G, VARIABLES
from vidange.reglages import _LecteurStrict

if TYPE_CHECKING:
    from vidange.cycle.mode_seaux import Lot
    from vidange.reglages import Machine, ReglagesEssais

# Au plus tant d'erreurs dites (un fichier très faux en aurait des centaines).
ERREURS_MAX = 30
CHAMPS = ("nom", "auteur", "remarque", "lot", "seaux")
CHAMPS_LOT = ("variete", "format", "seaux")


class ErreurPlan(Exception):
    """Plan mal écrit, ou qui sort de ce que Karulium permet."""

    def __init__(self, erreurs: list[str]) -> None:
        self.erreurs = erreurs[:ERREURS_MAX]
        texte = "plan d'essais refusé :\n" + "\n".join(f"  - {e}" for e in self.erreurs)
        if len(erreurs) > ERREURS_MAX:
            texte += f"\n  - ... et {len(erreurs) - ERREURS_MAX} autre(s) erreur(s)"
        super().__init__(texte)


@dataclass(frozen=True)
class PlanEssais:
    nom: str
    auteur: str
    format: str
    variete: str
    seaux: int
    # N° du seau dans le lot → variable → valeur du plan.
    valeurs: dict[int, dict[str, float | bool]]
    remarque: str | None = None

    @property
    def variables(self) -> list[str]:
        """Les variables que le plan fait varier, dans l'ordre de VARIABLES."""
        citees = {nom for valeurs in self.valeurs.values() for nom in valeurs}
        return [nom for nom in VARIABLES if nom in citees]

    def texte_lot(self) -> str:
        return f"{self.seaux} seaux {self.format} ({self.variete})"

    def vise(self, format: str, variete: str, nombre: int) -> bool:
        return (self.format, self.variete, self.seaux) == (format, variete, nombre)

    def en_dict(self) -> dict[str, Any]:
        return {
            "nom": self.nom,
            "auteur": self.auteur,
            "remarque": self.remarque,
            "lot": {"variete": self.variete, "format": self.format, "seaux": self.seaux},
            "seaux": {str(n): dict(v) for n, v in sorted(self.valeurs.items())},
        }

    def en_json(self) -> str:
        return json.dumps(self.en_dict(), ensure_ascii=False, sort_keys=True)

    @classmethod
    def depuis(cls, donnees: dict[str, Any]) -> "PlanEssais":
        """Le plan gardé dans le registre (déjà vérifié à son arrivée)."""
        lot = donnees["lot"]
        return cls(
            donnees["nom"],
            donnees["auteur"],
            lot["format"],
            lot["variete"],
            int(lot["seaux"]),
            {int(n): dict(v) for n, v in donnees["seaux"].items()},
            donnees.get("remarque"),
        )

    # ------------------------------------------------------------ seau par seau

    def valeurs_du_seau(self, numero: int, machine: "Machine") -> dict[str, float | bool]:
        """Toutes les variables du plan pour ce seau : celle du plan, ou la normale
        (machine.yaml). Sans spray, pas de dose de spray."""
        valeurs: dict[str, float | bool] = {}
        cite = self.valeurs.get(numero, {})
        for nom in self.variables:
            if nom in cite:
                valeurs[nom] = cite[nom]
                continue
            normal = VARIABLES[nom].normal(machine, self.format)
            if normal is not None:
                valeurs[nom] = normal
        if valeurs.get(SPRAY) is False:
            valeurs.pop(SPRAY_G, None)
        return valeurs

    def tableau(self, machine: "Machine") -> list[dict[str, Any]]:
        """Le résumé seau par seau : pour chaque seau, chaque variable du plan, sa valeur et si
        c'est le réglage normal."""
        lignes = []
        for numero in range(1, self.seaux + 1):
            cite = self.valeurs.get(numero, {})
            valeurs = self.valeurs_du_seau(numero, machine)
            lignes.append(
                {
                    "numero": numero,
                    "valeurs": {
                        nom: {"valeur": valeurs.get(nom), "normal": nom not in cite}
                        for nom in self.variables
                    },
                }
            )
        return lignes

    def en_texte(self, machine: "Machine", essais: "ReglagesEssais") -> str:
        """Le tableau seau par seau, pour la commande `vidange plan`."""
        noms = self.variables
        titres = [_titre(nom, essais) for nom in noms]
        lignes = [
            f"Plan « {self.nom} » de {self.auteur}, pour un lot de {self.texte_lot()}",
            *([f"Remarque : {self.remarque}"] if self.remarque else []),
            "(* = réglage normal de machine.yaml)",
            "Seau  " + "  ".join(f"{t:<22}" for t in titres),
        ]
        for ligne in self.tableau(machine):
            cases = []
            for nom in noms:
                case = ligne["valeurs"][nom]
                texte = valeur_lisible(case["valeur"]) + (" *" if case["normal"] else "")
                cases.append(f"{texte:<22}")
            lignes.append(f"{ligne['numero']:>4}  " + "  ".join(cases))
        return "\n".join(ligne.rstrip() for ligne in lignes)


def _titre(nom: str, essais: "ReglagesEssais") -> str:
    variable = essais.variables[nom]
    return f"{variable.libelle} ({variable.unite})" if variable.unite else variable.libelle


def valeur_lisible(valeur: Any) -> str:
    if valeur is None:
        return "—"
    if valeur is True:
        return "oui"
    if valeur is False:
        return "non"
    if isinstance(valeur, float):
        return f"{valeur:g}".replace(".", ",")
    return str(valeur)


# ------------------------------------------------------------ lecture et vérification


def lire_texte(texte: str) -> Any:
    """Le texte d'un plan (YAML ou JSON) → ses données ; ErreurPlan s'il est mal écrit."""
    try:
        return yaml.load(texte, Loader=_LecteurStrict)
    except yaml.YAMLError as erreur:
        repere = getattr(erreur, "problem_mark", None)
        ligne = f", ligne {repere.line + 1}" if repere is not None else ""
        probleme = getattr(erreur, "problem", None) or str(erreur)
        raise ErreurPlan([f"fichier mal écrit{ligne} ({probleme})"]) from None


def lire_plan(texte: str, machine: "Machine", essais: "ReglagesEssais") -> PlanEssais:
    """Lit et vérifie un plan : champs, lot visé, numéros des seaux, variables connues, bornes.
    ErreurPlan avec toutes les erreurs sinon."""
    if len(texte.encode("utf-8")) > essais.fichier_max_ko * 1024:
        raise ErreurPlan([f"fichier trop gros (plus de {essais.fichier_max_ko} ko)"])
    donnees = lire_texte(texte)
    if not isinstance(donnees, dict):
        raise ErreurPlan(
            ["le plan doit être une liste de « nom: valeur » (nom, auteur, lot, seaux)"]
        )
    erreurs: list[str] = []
    erreurs += [
        f"« {cle} » : nom inconnu (noms permis : {', '.join(CHAMPS)})"
        for cle in donnees
        if cle not in CHAMPS
    ]
    nom = _texte(donnees, "nom", essais.texte_max, erreurs)
    auteur = _texte(donnees, "auteur", essais.texte_max, erreurs)
    remarque = None
    if donnees.get("remarque") is not None:
        remarque = _texte(donnees, "remarque", essais.texte_max, erreurs)
    format, variete, nombre = _lot(donnees.get("lot"), machine, essais, erreurs)
    valeurs = _seaux(donnees.get("seaux"), format, nombre, essais, erreurs)
    if erreurs:
        raise ErreurPlan(erreurs)
    assert format is not None and variete is not None and nombre is not None
    return PlanEssais(nom, auteur, format, variete, nombre, valeurs, remarque)


def _texte(donnees: dict[str, Any], cle: str, longueur: int, erreurs: list[str]) -> str:
    valeur = donnees.get(cle)
    if not isinstance(valeur, str) or not valeur.strip():
        erreurs.append(f"« {cle} » manque (un texte)")
        return ""
    if len(valeur) > longueur:
        erreurs.append(f"« {cle} » trop long (plus de {longueur} caractères)")
    return valeur.strip()


def _lot(
    lot: Any, machine: "Machine", essais: "ReglagesEssais", erreurs: list[str]
) -> tuple[str | None, str | None, int | None]:
    if not isinstance(lot, dict):
        erreurs.append("« lot » manque : variete, format et seaux du lot visé")
        return None, None, None
    erreurs += [
        f"lot → « {cle} » : nom inconnu (noms permis : {', '.join(CHAMPS_LOT)})"
        for cle in lot
        if cle not in CHAMPS_LOT
    ]
    formats = list(machine.griffe.formats) if machine.griffe is not None else []
    format = lot.get("format")
    if format not in formats:
        erreurs.append(
            f"lot → format « {format} » inconnu (machine.yaml, griffe → formats : "
            f"{', '.join(formats)})"
        )
        format = None
    variete = lot.get("variete")
    if not isinstance(variete, str) or not variete.strip():
        erreurs.append("lot → variete manque (la variété de la semence, comme au bouton du lot)")
        variete = None
    else:
        variete = variete.strip()
    nombre = lot.get("seaux")
    if isinstance(nombre, bool) or not isinstance(nombre, int):
        erreurs.append("lot → seaux : le nombre de seaux du lot (un nombre entier)")
        nombre = None
    elif not 1 <= nombre <= essais.seaux_max:
        erreurs.append(f"lot → seaux : {nombre}, il faut de 1 à {essais.seaux_max} seaux")
        nombre = None
    return format, variete, nombre


def _numero(cle: Any) -> int | None:
    if isinstance(cle, bool):
        return None
    if isinstance(cle, int):
        return cle
    if isinstance(cle, str) and cle.strip().isdigit():
        return int(cle.strip())
    return None


def _seaux(
    seaux: Any,
    format: str | None,
    nombre: int | None,
    essais: "ReglagesEssais",
    erreurs: list[str],
) -> dict[int, dict[str, float | bool]]:
    if not isinstance(seaux, dict) or not seaux:
        erreurs.append(
            "« seaux » manque : pour chaque seau qui change (par son numéro dans le lot), ses "
            "valeurs ; sinon ce n'est pas un plan d'essais"
        )
        return {}
    permises = ", ".join(essais.variables)
    resultat: dict[int, dict[str, float | bool]] = {}
    for cle, valeurs in seaux.items():
        numero = _numero(cle)
        if numero is None:
            erreurs.append(f"seaux → « {cle} » : un numéro de seau dans le lot (1, 2, 3...)")
            continue
        debut = f"seau n° {numero}"
        if numero in resultat:
            erreurs.append(f"{debut} : écrit deux fois")
            continue
        if nombre is not None and not 1 <= numero <= nombre:
            erreurs.append(f"{debut} : le lot n'a que {nombre} seaux (de 1 à {nombre})")
        if not isinstance(valeurs, dict) or not valeurs:
            erreurs.append(f"{debut} : donner ses valeurs, par exemple {{mycelium_g: 120}}")
            continue
        lues: dict[str, float | bool] = {}
        for nom, valeur in valeurs.items():
            variable = essais.variables.get(nom) if isinstance(nom, str) else None
            if variable is None:
                erreurs.append(
                    f"{debut} : variable « {nom} » inconnue ; un plan ne peut faire varier que "
                    f"{permises} (pi/reglages/essais.yaml)"
                )
                continue
            if variable.genre == "oui_non":
                if not isinstance(valeur, bool):
                    erreurs.append(
                        f"{debut}, {nom} : « {valeur} », écrire true (oui) ou false (non)"
                    )
                    continue
                lues[nom] = valeur
                continue
            if isinstance(valeur, bool) or not isinstance(valeur, int | float):
                erreurs.append(f"{debut}, {nom} : « {valeur} » n'est pas un nombre")
                continue
            if not math.isfinite(valeur):
                erreurs.append(f"{debut}, {nom} : « {valeur} » n'est pas un nombre")
                continue
            if format is not None:
                bas, haut = variable.bornes(format)
                if not bas <= valeur <= haut:
                    erreurs.append(
                        f"{debut}, {nom} = {valeur:g} {variable.unite} : hors des bornes permises "
                        f"pour {format} ({bas:g} à {haut:g} {variable.unite}, "
                        "pi/reglages/essais.yaml)"
                    )
                    continue
            lues[nom] = float(valeur)
        if lues.get(SPRAY) is False and SPRAY_G in lues:
            erreurs.append(f"{debut} : spray: false et une dose de spray, c'est l'un ou l'autre")
        resultat[numero] = lues
    return resultat


# ------------------------------------------------------------ appliquer à un lot


def appliquer(plan_id: int, plan: PlanEssais, lot: "Lot", machine: "Machine") -> "Lot":
    """Le même lot, chaque seau avec ses valeurs du plan (ou normales) et le numéro du plan."""
    seaux = tuple(
        replace(seau, essai=plan.valeurs_du_seau(numero, machine), plan_essais=plan_id)
        for numero, seau in enumerate(lot.seaux, start=1)
    )
    return replace(lot, seaux=seaux)


@dataclass(frozen=True)
class Application:
    """Une valeur d'un plan vraiment appliquée à un seau (notée au registre)."""

    numero: int
    seau: str | None
    variable: str
    voulu: float | bool
    mesure: float | None = None
    unite: str | None = None
    couche: int | None = None
    remarque: str | None = None
