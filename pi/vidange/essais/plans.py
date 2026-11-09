"""Les plans d'essais du Pi : chargés, acceptés, lancés avec un lot, retirés (tâche 31).

    plans = PlansEssais(registre, reglages.machine, reglages.essais)
    plans.charger(texte, qui)           # commande ou API : une PROPOSITION, rien ne change
    plans.accepter(numero, qui)         # Karulium, sur la page (rôle « régler »), après le tableau
    plans.pour_le_lot(format, variete, nombre)   # le plan accepté qui vise ce lot, ou None
    plans.lancer(numero, qui)           # au Go du lot (vidange.cycle.lancement)
    plans.retirer(numero, qui)          # tant que le lot n'a pas commencé
    plans.noter(numero, application)    # pendant le lot : chaque valeur vraiment appliquée

Règle 6 du dépôt : un plan chargé n'est qu'une proposition ; il ne sert qu'accepté par Karulium,
et seulement au lot qu'il vise (même variété, même format, même nombre de seaux), qui part
lui-même au Go à l'écran. Un seul plan accepté à la fois. Tout est dans le registre (copie de
secours comprise) ; rien ne dépend du réseau ni du PC qui a préparé le plan.
"""

import json
import threading
import uuid
from typing import TYPE_CHECKING, Any

from vidange.essais.plan import Application, ErreurPlan, PlanEssais, lire_plan, valeur_lisible
from vidange.journal import donner_journal
from vidange.registre import ErreurRegistre, Registre

if TYPE_CHECKING:
    from vidange.reglages import Machine, ReglagesEssais

journal = donner_journal("essais")

# Ce que dit chaque état, pour la page et la commande.
ETATS = {
    "propose": "chargé, pas encore accepté",
    "accepte": "accepté : attend son lot",
    "lance": "lancé avec un lot",
    "retire": "retiré",
}


class PlansEssais:
    def __init__(self, registre: Registre, machine: "Machine", essais: "ReglagesEssais") -> None:
        self.registre = registre
        self.machine = machine
        self.essais = essais
        self._verrou = threading.Lock()

    # ------------------------------------------------------------ arrivée et choix de Karulium

    def lire(self, texte: str) -> PlanEssais:
        """Vérifie un plan sans le garder (ErreurPlan sinon)."""
        return lire_plan(texte, self.machine, self.essais)

    def charger(self, texte: str, qui: str) -> int:
        """Un plan arrive (commande ou API) : vérifié, gardé comme proposition. Rend son n°."""
        plan = self.lire(texte)
        with self._verrou:
            proposes = self.registre.lire(
                "SELECT COUNT(*) AS n FROM plans_essais WHERE etat = 'propose'"
            )[0]["n"]
            if proposes >= self.essais.proposes_max:
                raise ErreurPlan(
                    [
                        f"déjà {proposes} plans chargés et pas acceptés (au plus "
                        f"{self.essais.proposes_max}, essais.yaml) : en retirer d'abord"
                    ]
                )
            numero = self.registre.ajouter_plan_essais(
                qui,
                cle=str(uuid.uuid4()),
                nom=plan.nom,
                auteur=plan.auteur,
                format=plan.format,
                variete=plan.variete,
                seaux=plan.seaux,
                contenu=plan.en_json(),
                texte=texte,
            )
        journal.info(
            "Plan d'essais n° %d « %s » chargé par %s, pour un lot de %s : attend d'être accepté",
            numero,
            plan.nom,
            qui,
            plan.texte_lot(),
        )
        return numero

    def accepter(self, numero: int, qui: str) -> None:
        """Karulium accepte le plan (après avoir vu son tableau). Il est revérifié avec les
        réglages d'aujourd'hui ; un seul plan accepté à la fois."""
        with self._verrou:
            ligne = self._ligne(numero)
            if ligne["etat"] != "propose":
                raise ErreurPlan([f"plan n° {numero} : {ETATS[ligne['etat']]}, pas à accepter"])
            # Les bornes ont pu changer depuis son arrivée.
            self.lire(ligne["texte"])
            autre = self._accepte()
            if autre is not None:
                raise ErreurPlan(
                    [
                        f"le plan n° {autre['id']} « {autre['nom']} » est déjà accepté et attend "
                        "son lot : le retirer d'abord (un seul plan accepté à la fois)"
                    ]
                )
            self._changer(numero, "accepte", qui, ("propose",))
        journal.warning(
            "Plan d'essais n° %d « %s » accepté par %s : il ira au prochain lot de %s",
            numero,
            ligne["nom"],
            qui,
            self._plan(ligne).texte_lot(),
        )

    def retirer(self, numero: int, qui: str) -> None:
        """Retire un plan chargé ou accepté (pas un plan déjà lancé avec son lot)."""
        with self._verrou:
            ligne = self._ligne(numero)
            if ligne["etat"] not in ("propose", "accepte"):
                raise ErreurPlan(
                    [f"plan n° {numero} : {ETATS[ligne['etat']]}, il ne peut plus être retiré"]
                )
            self._changer(numero, "retire", qui, ("propose", "accepte"))
        journal.warning("Plan d'essais n° %d « %s » retiré par %s", numero, ligne["nom"], qui)

    # ------------------------------------------------------------ le lot

    def accepte(self) -> tuple[int, PlanEssais] | None:
        """Le plan accepté qui attend son lot, ou None."""
        ligne = self._accepte()
        return None if ligne is None else (ligne["id"], self._plan(ligne))

    def pour_le_lot(self, format: str, variete: str, nombre: int) -> tuple[int, PlanEssais] | None:
        """Le plan accepté qui vise ce lot (même format, variété et nombre de seaux), ou None."""
        accepte = self.accepte()
        if accepte is None or not accepte[1].vise(format, variete, nombre):
            return None
        return accepte

    def lancer(self, numero: int, qui: str) -> None:
        """Au Go du lot : le plan est attaché au lot qui part (il ne peut plus être retiré)."""
        self._changer(numero, "lance", qui, ("accepte",))
        journal.warning("Plan d'essais n° %d lancé avec le lot (Go de %s)", numero, qui)

    def defaire_lancement(self, numero: int) -> None:
        """Le lot n'a pas pu partir après tout : le plan redevient accepté."""
        self._changer(numero, "accepte", None, ("lance",))

    def noter(self, numero: int, application: Application) -> None:
        """Une valeur vraiment appliquée à un seau (registre, puis envoi au logiciel de culture).
        Une erreur du registre est dite au journal : le lot continue."""
        remarque = application.remarque
        try:
            ligne = self._ligne(numero)
            cite = self._plan(ligne).valeurs.get(application.numero, {})
            source = "plan" if application.variable in cite else "réglage normal"
            remarque = source if remarque is None else f"{source} ; {remarque}"
            self.registre.noter_essai_applique(
                numero,
                application.numero,
                application.seau,
                application.variable,
                application.voulu,
                application.mesure,
                application.unite,
                application.couche,
                remarque,
            )
        except (ErreurPlan, ErreurRegistre) as erreur:
            journal.error(
                "Plan d'essais n° %d, seau n° %d : valeur appliquée pas notée (%s)",
                numero,
                application.numero,
                erreur,
            )

    # ------------------------------------------------------------ ce qu'on montre

    def en_dict(self, numero: int) -> dict[str, Any]:
        ligne = self._ligne(numero)
        plan = self._plan(ligne)
        appliques = self.registre.lire(
            "SELECT e.numero, e.variable, e.voulu, e.mesure, e.unite, e.couche, e.remarque, "
            "e.quand, s.code AS seau FROM essais_appliques e LEFT JOIN seaux s ON s.id = e.seau_id "
            "WHERE e.plan_id = ? ORDER BY e.id",
            (numero,),
        )
        for application in appliques:
            application["voulu"] = json.loads(application["voulu"])
        return {
            "numero": ligne["id"],
            "nom": plan.nom,
            "auteur": plan.auteur,
            "remarque": plan.remarque,
            "lot": plan.texte_lot(),
            "format": plan.format,
            "variete": plan.variete,
            "seaux": plan.seaux,
            "etat": ligne["etat"],
            "etat_texte": ETATS[ligne["etat"]],
            "charge": {"quand": ligne["charge_le"], "qui": ligne["charge_par"]},
            "accepte": _qui_quand(ligne, "accepte"),
            "lance": _qui_quand(ligne, "lance"),
            "retire": _qui_quand(ligne, "retire"),
            "variables": [
                {
                    "nom": nom,
                    "libelle": self.essais.variables[nom].libelle,
                    "unite": self.essais.variables[nom].unite,
                }
                for nom in plan.variables
            ],
            "tableau": plan.tableau(self.machine),
            "appliques": appliques,
            "seaux_faits": len({a["numero"] for a in appliques}),
            "texte": plan.en_texte(self.machine, self.essais),
        }

    def liste(self, tous: bool = False) -> list[dict[str, Any]]:
        """Les plans, le plus récent d'abord (sans `tous` : pas les retirés)."""
        filtre = "" if tous else "WHERE etat != 'retire'"
        lignes = self.registre.lire(f"SELECT id FROM plans_essais {filtre} ORDER BY id DESC")
        return [self.en_dict(ligne["id"]) for ligne in lignes]

    def variables(self) -> list[dict[str, Any]]:
        """Ce qu'un plan peut faire varier (essais.yaml), pour la page."""
        return [
            {
                "nom": nom,
                "libelle": v.libelle,
                "genre": v.genre,
                "unite": v.unite,
                "min": v.min,
                "max": v.max,
                "formats": {f: {"min": b.min, "max": b.max} for f, b in v.formats.items()},
                "aide": v.aide,
                "lue_par": v.lue_par,
            }
            for nom, v in self.essais.variables.items()
        ]

    def texte(self, numero: int) -> str:
        """Le fichier du plan tel qu'il est arrivé."""
        return self._ligne(numero)["texte"]

    # ------------------------------------------------------------ outils

    def _ligne(self, numero: int) -> dict[str, Any]:
        lignes = self.registre.lire("SELECT * FROM plans_essais WHERE id = ?", (numero,))
        if not lignes:
            raise ErreurPlan([f"plan d'essais n° {numero} inconnu"])
        return lignes[0]

    def _accepte(self) -> dict[str, Any] | None:
        lignes = self.registre.lire(
            "SELECT * FROM plans_essais WHERE etat = 'accepte' ORDER BY id LIMIT 1"
        )
        return lignes[0] if lignes else None

    @staticmethod
    def _plan(ligne: dict[str, Any]) -> PlanEssais:
        return PlanEssais.depuis(json.loads(ligne["contenu"]))

    def _changer(self, numero: int, etat: str, qui: str | None, depuis: tuple[str, ...]) -> None:
        try:
            self.registre.changer_etat_plan(numero, etat, qui, depuis)
        except ErreurRegistre as erreur:
            raise ErreurPlan([str(erreur)]) from None


def _qui_quand(ligne: dict[str, Any], etat: str) -> dict[str, Any] | None:
    quand = ligne[f"{etat}_le"]
    return None if quand is None else {"quand": quand, "qui": ligne[f"{etat}_par"]}


__all__ = ["ETATS", "PlansEssais", "valeur_lisible"]
