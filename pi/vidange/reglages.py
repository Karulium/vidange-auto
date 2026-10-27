"""Chargement et vérification des fichiers de réglages (`pi/reglages/*.yaml`).

Chaque fichier a son modèle ci-dessous. Au démarrage, tout est vérifié ; la moindre
erreur arrête le programme avec un message en français qui dit quel fichier,
quel réglage, et ce qui ne va pas. Toutes les erreurs sont listées d'un coup.
"""

from pathlib import Path
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    IPvAnyNetwork,
    StringConstraints,
    ValidationError,
    model_validator,
)


class ErreurReglages(Exception):
    """Réglages faux : le programme ne doit pas démarrer."""


class Modele(BaseModel):
    """Base de tous les réglages : un nom inconnu est une erreur (faute de frappe)."""

    model_config = ConfigDict(extra="forbid", frozen=True)


# Noms des axes, positions, zones : minuscules sans accent, comme dans le code.
Nom = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]
Intervalle = tuple[float, float]
# Lettres des axes d'une carte FluidNC.
Lettre = Literal["X", "Y", "Z", "A", "B", "C"]


# ---------------------------------------------------------------- machine.yaml


class Axe(Modele):
    """Un axe : longueur de son rail et course permise, en mètres."""

    longueur_rail: float = Field(gt=0)
    course: Intervalle
    # Carte FluidNC qui fait bouger l'axe (nom dans fluidnc.yaml) et lettre de l'axe sur la carte.
    carte: Nom | None = None
    lettre: Lettre | None = None

    @model_validator(mode="after")
    def _verifier_course(self) -> "Axe":
        if (self.carte is None) != (self.lettre is None):
            raise ValueError("« carte » et « lettre » vont ensemble : écrire les deux, ou aucun")
        debut, fin = self.course
        if debut >= fin:
            raise ValueError(
                f"la course doit aller du plus petit au plus grand ({debut:g} puis {fin:g})"
            )
        if debut < 0 or fin > self.longueur_rail:
            raise ValueError(
                f"la course ({debut:g} à {fin:g} m) sort du rail (0 à {self.longueur_rail:g} m)"
            )
        return self


class GesteLieuSur(Modele):
    """Un geste du retour en lieu sûr : une prise d'origine d'une carte, ou aller à une position."""

    # Carte FluidNC (nom dans fluidnc.yaml) dont on fait la prise d'origine ($H).
    prise_origine: Nom | None = None
    # Position nommée (plus haut dans « positions ») où envoyer les axes.
    aller: Nom | None = None
    # Délai maximal du geste (nom dans « durees »).
    delai: Nom

    @model_validator(mode="after")
    def _un_seul_geste(self) -> "GesteLieuSur":
        if (self.prise_origine is None) == (self.aller is None):
            raise ValueError("écrire « prise_origine: carte » ou « aller: position » (un seul)")
        return self


class Machine(Modele):
    """machine.yaml : axes, positions nommées, zones réservées."""

    # Vrai tant que le fichier contient des valeurs inventées : le programme le signale.
    exemple: bool = False
    axes: dict[Nom, Axe] = Field(min_length=1)
    # Une position donne une valeur (m) pour un ou plusieurs axes.
    positions: dict[Nom, dict[Nom, float]] = Field(default_factory=dict)
    # Une zone donne un intervalle (m) pour un ou plusieurs axes ;
    # un axe non cité veut dire « toute sa course ».
    zones: dict[Nom, Annotated[dict[Nom, Intervalle], Field(min_length=1)]] = Field(
        default_factory=dict
    )
    # Délais maximaux des étapes (s), par nom : le code des modules ne cite que ces noms.
    durees: dict[Nom, Annotated[float, Field(gt=0)]] = Field(default_factory=dict)
    # Retour en lieu sûr (après une coupure, ou à la mise en route) : gestes faits dans l'ordre.
    lieu_sur: list[GesteLieuSur] = Field(default_factory=list)

    @model_validator(mode="after")
    def _verifier_positions_et_zones(self) -> "Machine":
        erreurs: list[str] = []
        for numero, geste in enumerate(self.lieu_sur, start=1):
            if geste.delai not in self.durees:
                erreurs.append(f"lieu_sur n° {numero} : délai « {geste.delai} » absent de durees")
            if geste.aller is None:
                continue
            if geste.aller not in self.positions:
                erreurs.append(f"lieu_sur n° {numero} : position inconnue « {geste.aller} »")
                continue
            for axe in self.positions[geste.aller]:
                if axe in self.axes and self.axes[axe].carte is None:
                    erreurs.append(
                        f"lieu_sur n° {numero} : l'axe « {axe} » de la position "
                        f"« {geste.aller} » n'a pas de carte FluidNC"
                    )
        lettres_prises: dict[tuple[str, str], str] = {}
        for nom, axe in self.axes.items():
            if axe.carte is None or axe.lettre is None:
                continue
            autre = lettres_prises.setdefault((axe.carte, axe.lettre), nom)
            if autre != nom:
                erreurs.append(
                    f"les axes « {autre} » et « {nom} » ont la même lettre {axe.lettre} "
                    f"sur la carte « {axe.carte} »"
                )
        for nom, valeurs in self.positions.items():
            for axe, valeur in valeurs.items():
                if axe not in self.axes:
                    erreurs.append(f"position « {nom} » : axe inconnu « {axe} »")
                    continue
                debut, fin = self.axes[axe].course
                if not debut <= valeur <= fin:
                    erreurs.append(
                        f"position « {nom} » : {axe} = {valeur:g} m sort de la course "
                        f"({debut:g} à {fin:g} m)"
                    )
        zones_correctes = []
        for nom, intervalles in self.zones.items():
            correcte = True
            for axe, (debut, fin) in intervalles.items():
                if axe not in self.axes:
                    erreurs.append(f"zone « {nom} » : axe inconnu « {axe} »")
                    correcte = False
                    continue
                course_debut, course_fin = self.axes[axe].course
                if debut >= fin:
                    erreurs.append(
                        f"zone « {nom} » : sur {axe}, aller du plus petit au plus grand "
                        f"({debut:g} puis {fin:g})"
                    )
                    correcte = False
                elif debut < course_debut or fin > course_fin:
                    erreurs.append(
                        f"zone « {nom} » : sur {axe}, {debut:g} à {fin:g} m sort de la course "
                        f"({course_debut:g} à {course_fin:g} m)"
                    )
                    correcte = False
            if correcte:
                zones_correctes.append(nom)
        for i, nom_a in enumerate(zones_correctes):
            for nom_b in zones_correctes[i + 1 :]:
                if self._se_chevauchent(nom_a, nom_b):
                    erreurs.append(f"les zones « {nom_a} » et « {nom_b} » se chevauchent")
        if erreurs:
            raise ValueError("\n".join(erreurs))
        return self

    def _se_chevauchent(self, nom_a: str, nom_b: str) -> bool:
        """Deux zones se chevauchent si elles se recouvrent sur tous les axes à la fois."""
        zone_a, zone_b = self.zones[nom_a], self.zones[nom_b]
        for axe in zone_a.keys() | zone_b.keys():
            debut_a, fin_a = zone_a.get(axe, self.axes[axe].course)
            debut_b, fin_b = zone_b.get(axe, self.axes[axe].course)
            # Deux zones qui se touchent juste au bord ne se chevauchent pas.
            if max(debut_a, debut_b) >= min(fin_a, fin_b):
                return False
        return True


# -------------------------------------------------------------- programme.yaml


class Journal(Modele):
    niveau: Literal["detail", "info", "avertissement", "erreur"]
    taille_fichier_mo: float = Field(gt=0)
    nombre_fichiers: int = Field(ge=1)


class ReglagesChef(Modele):
    """Réglages du chef d'orchestre."""

    # Tous les combien il regarde les conditions des étapes (s).
    periode_s: float = Field(gt=0, le=1)
    # Une alarme dans un module met toute la machine en pause, ou seulement ce module.
    alarme_pause_tout: bool


class ReglagesRegistre(Modele):
    """Réglages du registre (base SQLite) et de sa copie de secours quotidienne."""

    # La copie du jour se fait à partir de cette heure (heure du Pi, de 0 à 23).
    heure_sauvegarde: int = Field(ge=0, le=23)
    # Nombre de copies quotidiennes gardées ; les plus vieilles sont effacées.
    copies_gardees: int = Field(ge=1)
    # Tous les combien (minutes) on regarde s'il faut faire la copie du jour.
    periode_verification_min: float = Field(gt=0, le=60)


class ReglagesSante(Modele):
    """Santé de l'informatique du Pi (fonction 45) : seuils d'alerte."""

    # Tous les combien (minutes) on mesure et on note dans le registre.
    periode_min: float = Field(gt=0, le=60)
    # Le Pi 5 ralentit vers 80-85 °C : on prévient avant.
    temperature_pi_attention_c: float = Field(gt=0)
    # Place libre sur le SSD (dossier des données), en Go : attention, puis démarrage refusé.
    disque_libre_attention_go: float = Field(gt=0)
    disque_libre_minimum_go: float = Field(gt=0)
    # Mémoire vive disponible, en Mo.
    memoire_libre_attention_mo: float = Field(gt=0)
    # La dernière copie de secours du registre ne doit pas être plus vieille que (heures).
    sauvegarde_age_max_h: float = Field(gt=0)

    @model_validator(mode="after")
    def _verifier_seuils(self) -> "ReglagesSante":
        if self.disque_libre_minimum_go >= self.disque_libre_attention_go:
            raise ValueError(
                "disque_libre_minimum_go doit être plus petit que disque_libre_attention_go"
            )
        return self


class ReglagesChienDeGarde(Modele):
    """Chien de garde (fonction 14) : le Pi surveille les cartes, et se fait surveiller."""

    # Tous les combien (s) il regarde les cartes et le chef, et dit « je vis » à systemd.
    periode_s: float = Field(gt=0, le=10)
    # Le chef qui n'a pas fait de tour depuis ce temps (s) est déclaré figé.
    chef_fige_s: float = Field(gt=0)

    @model_validator(mode="after")
    def _verifier_delais(self) -> "ReglagesChienDeGarde":
        if self.chef_fige_s < 2 * self.periode_s:
            raise ValueError(
                f"chef_fige_s ({self.chef_fige_s:g} s) doit valoir au moins 2 fois "
                f"periode_s ({self.periode_s:g} s)"
            )
        return self


class ReglagesOnduleur(Modele):
    """Arrêt propre sur onduleur (fonction 4)."""

    # Tous les combien (s) on regarde le signal de l'onduleur.
    periode_s: float = Field(gt=0, le=10)
    # Courant coupé depuis ce temps (s) : machine en pause, état noté, puis le Pi s'éteint.
    delai_avant_arret_s: float = Field(ge=0)
    # Commande qui éteint le Pi (le compte « vidange » doit avoir le droit de la lancer).
    commande_arret: list[Annotated[str, StringConstraints(min_length=1)]] = Field(min_length=1)


class ReglagesBilan(Modele):
    """Bilan écrit à chaque alarme (fonction 17)."""

    # Les dernières lignes du journal recopiées dans le bilan.
    lignes_journal: int = Field(ge=0, le=1000)


class ReglagesFiabilite(Modele):
    sante: ReglagesSante
    chien_de_garde: ReglagesChienDeGarde
    onduleur: ReglagesOnduleur
    bilan: ReglagesBilan


class ReglagesApi(Modele):
    """API du Pi et page web locale (tâche 8)."""

    # Adresse où l'API écoute : « 0.0.0.0 » = toutes les liaisons réseau du Pi (local et Tailscale).
    adresse: str = Field(min_length=1)
    port: int = Field(ge=1, le=65535)
    # Seuls ces réseaux peuvent joindre l'API et la page : les autres sont refusés d'office.
    reseaux_autorises: list[IPvAnyNetwork] = Field(min_length=1)
    # La page web redemande l'état tous les (s).
    rafraichir_s: float = Field(gt=0, le=60)
    # Nombre de lignes rendues au plus d'un coup (historique, alarmes, photos).
    lignes_max: int = Field(ge=1, le=10000)


# Une couleur « #RRGGBB » (rouge, vert, bleu en hexadécimal), comme dans un logiciel de dessin.
Couleur = Annotated[str, StringConstraints(pattern=r"^#[0-9A-Fa-f]{6}$")]


class FondTexte(Modele):
    fond: Couleur
    texte: Couleur


class CouleursEcran(Modele):
    """Code couleur de l'écran (fonction 47)."""

    marche: FondTexte
    go: FondTexte
    pause: FondTexte
    alarme: FondTexte
    repos: FondTexte
    mode: FondTexte
    bouton: FondTexte
    inactif: FondTexte


class ReglagesEcran(Modele):
    """Écran Nextion de la porte de l'armoire (tâche 9)."""

    vitesse_bauds: int = Field(gt=0)
    # Le Pi lit les boutons et met l'écran à jour tous les (s).
    periode_s: float = Field(gt=0, le=2)
    # Il demande à l'écran s'il est là tous les (s) ; muet : sans réponse depuis « silence_s ».
    presence_s: float = Field(gt=0)
    silence_s: float = Field(gt=0)
    # Port série impossible à ouvrir : nouvel essai tous les (s).
    reconnexion_s: float = Field(gt=0)
    # Retour à la page d'état sans appui depuis ce temps (s) ; une question « Oui / Non »
    # sans réponse est abandonnée plus vite.
    retour_accueil_s: float = Field(gt=0)
    confirmation_s: float = Field(gt=0)
    # Durée d'affichage d'un message (« Aucun Go attendu »...).
    message_s: float = Field(gt=0)
    couleurs: CouleursEcran

    @model_validator(mode="after")
    def _verifier_delais(self) -> "ReglagesEcran":
        if self.silence_s < 2 * self.presence_s:
            raise ValueError(
                f"silence_s ({self.silence_s:g} s) doit valoir au moins 2 fois "
                f"presence_s ({self.presence_s:g} s)"
            )
        return self


class EnvoiCulture(Modele):
    """Envoi des cycles au logiciel de culture (Django), format dans docs/django.md."""

    # Adresse de l'app « machine » qui reçoit les cycles ; vide : pas encore prête, les cycles
    # attendent dans la file (rien n'est perdu).
    adresse: str = ""
    # Nom de cette machine, envoyé avec chaque cycle.
    machine: str = Field(min_length=1)
    # Le logiciel de culture compte en heure locale sans fuseau (USE_TZ = False) : les heures
    # lui sont envoyées dans ce fuseau.
    fuseau_horaire: str = Field(min_length=1)
    # Sans réponse après ce temps (s), l'essai est raté. Court : l'arrêt du programme l'attend.
    delai_reponse_s: float = Field(gt=0, le=10)

    @model_validator(mode="after")
    def _verifier(self) -> "EnvoiCulture":
        if self.adresse and not self.adresse.startswith(("http://", "https://")):
            raise ValueError(f"adresse « {self.adresse} » : doit commencer par http:// ou https://")
        try:
            ZoneInfo(self.fuseau_horaire)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(
                f"fuseau horaire inconnu « {self.fuseau_horaire} » (exemple : America/Guadeloupe)"
            ) from None
        return self


class EnvoiSecours(Modele):
    """Copie de secours vers la maison (par Tailscale)."""

    # Commande qui copie un fichier ou un dossier vers la maison ; « {chemin} » y est remplacé
    # par ce qu'il faut copier. Vide : pas encore prête, les copies attendent dans la file.
    commande: list[Annotated[str, StringConstraints(min_length=1)]] = Field(default_factory=list)
    # La commande est arrêtée si elle dure plus que ça (s).
    duree_max_s: float = Field(gt=0)
    # Envoyer aussi, chaque jour, le dossier des photos (seules les nouvelles partent avec rsync).
    photos: bool

    @model_validator(mode="after")
    def _verifier(self) -> "EnvoiSecours":
        if self.commande and not any("{chemin}" in morceau for morceau in self.commande):
            raise ValueError("commande : il manque « {chemin} » (ce qu'il faut copier)")
        return self


class ReglagesEnvois(Modele):
    """File d'envoi vers l'extérieur (tâche 10). La machine n'attend jamais le réseau."""

    # La file est regardée tous les (s).
    periode_s: float = Field(gt=0, le=3600)
    # Après un essai raté vers une destination, on attend ce temps (s), doublé à chaque nouvel
    # échec, sans dépasser « attente_max_min ».
    attente_premier_echec_s: float = Field(gt=0)
    attente_max_min: float = Field(gt=0)
    # Un envoi qui attend depuis plus que ça (h) est signalé dans la check-list.
    signaler_apres_h: float = Field(gt=0)
    # Les envois réussis restent visibles ce nombre de jours, puis sont effacés de la file.
    garder_envoyes_jours: int = Field(ge=1)
    culture: EnvoiCulture
    secours: EnvoiSecours

    @model_validator(mode="after")
    def _verifier_attentes(self) -> "ReglagesEnvois":
        if self.attente_max_min * 60 < self.attente_premier_echec_s:
            raise ValueError("attente_max_min doit être plus long que attente_premier_echec_s")
        return self


class Programme(Modele):
    """programme.yaml : réglages du programme lui-même (pas de la machine)."""

    journal: Journal
    chef: ReglagesChef
    registre: ReglagesRegistre
    fiabilite: ReglagesFiabilite
    api: ReglagesApi
    ecran: ReglagesEcran
    envois: ReglagesEnvois


# ---------------------------------------------------------------- fluidnc.yaml


class LiaisonFluidnc(Modele):
    """Réglages communs aux liaisons série avec les cartes FluidNC."""

    vitesse_bauds: int = Field(gt=0)
    # Place dans le tampon de réception de la carte (octets) : le contrôle de flux
    # n'envoie jamais plus de lignes sans réponse que ce qui y tient.
    taille_tampon: int = Field(ge=16)
    # Tous les combien on demande l'état (« ? »).
    periode_etat_s: float = Field(gt=0)
    # Sans rien recevoir pendant ce temps, la carte est déclarée muette et la liaison reprise.
    delai_silence_s: float = Field(gt=0)
    # Attente entre deux essais de connexion.
    delai_reconnexion_s: float = Field(gt=0)

    @model_validator(mode="after")
    def _verifier_delais(self) -> "LiaisonFluidnc":
        if self.delai_silence_s < 3 * self.periode_etat_s:
            raise ValueError(
                f"delai_silence_s ({self.delai_silence_s:g} s) doit valoir au moins "
                f"3 fois periode_etat_s ({self.periode_etat_s:g} s)"
            )
        return self


class CarteFluidnc(Modele):
    description: str = ""
    # Numéro de série de l'USB de la carte : c'est lui qui la reconnaît, jamais l'ordre des ports.
    numero_serie_usb: Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]


class Fluidnc(Modele):
    """fluidnc.yaml : les cartes FluidNC et leur liaison avec le Pi."""

    exemple: bool = False
    liaison: LiaisonFluidnc
    cartes: dict[Nom, CarteFluidnc] = Field(min_length=1)

    @model_validator(mode="after")
    def _verifier_numeros(self) -> "Fluidnc":
        deja_vus: dict[str, str] = {}
        erreurs = []
        for nom, carte in self.cartes.items():
            autre = deja_vus.setdefault(carte.numero_serie_usb, nom)
            if autre != nom:
                erreurs.append(
                    f"les cartes « {autre} » et « {nom} » ont le même numéro de série USB "
                    f"« {carte.numero_serie_usb} »"
                )
        if erreurs:
            raise ValueError("\n".join(erreurs))
        return self


# --------------------------------------------------------------- l'ensemble


class Reglages(Modele):
    machine: Machine
    programme: Programme
    fluidnc: Fluidnc


# Nom du fichier → (nom dans Reglages, modèle). Ajouter ici chaque nouveau fichier.
FICHIERS: dict[str, tuple[str, type[Modele]]] = {
    "machine.yaml": ("machine", Machine),
    "programme.yaml": ("programme", Programme),
    "fluidnc.yaml": ("fluidnc", Fluidnc),
}


def charger_reglages(dossier: Path) -> Reglages:
    """Lit et vérifie tous les fichiers de réglages, ou lève ErreurReglages."""
    if not dossier.is_dir():
        raise ErreurReglages(f"Le dossier des réglages n'existe pas : {dossier}")
    erreurs: list[str] = []
    for chemin in sorted([*dossier.glob("*.yaml"), *dossier.glob("*.yml")]):
        if chemin.name not in FICHIERS:
            erreurs.append(
                f"{chemin.name} : fichier inconnu (fichiers attendus : {', '.join(FICHIERS)})"
            )
    valeurs: dict[str, Modele] = {}
    for nom_fichier, (cle, modele) in FICHIERS.items():
        chemin = dossier / nom_fichier
        if not chemin.exists():
            erreurs.append(f"{nom_fichier} : fichier manquant")
            continue
        try:
            valeurs[cle] = modele.model_validate(lire_yaml(chemin))
        except ErreurReglages as erreur:
            erreurs.append(str(erreur))
        except ValidationError as erreur:
            erreurs.extend(traduire_erreurs(erreur, nom_fichier))
    if not erreurs:
        erreurs.extend(_verifier_entre_fichiers(valeurs))
    if erreurs:
        raise ErreurReglages(rediger(erreurs, dossier))
    return Reglages.model_validate(valeurs)


def _verifier_entre_fichiers(valeurs: dict[str, Modele]) -> list[str]:
    """Ce qu'un fichier cite d'un autre fichier doit y exister."""
    machine, fluidnc = valeurs["machine"], valeurs["fluidnc"]
    assert isinstance(machine, Machine) and isinstance(fluidnc, Fluidnc)
    cartes = ", ".join(fluidnc.cartes)
    erreurs = [
        f"machine.yaml, axes → {nom} : carte « {axe.carte} » absente de fluidnc.yaml "
        f"(cartes : {cartes})"
        for nom, axe in machine.axes.items()
        if axe.carte is not None and axe.carte not in fluidnc.cartes
    ]
    erreurs += [
        f"machine.yaml, lieu_sur n° {numero} : carte « {geste.prise_origine} » absente de "
        f"fluidnc.yaml (cartes : {cartes})"
        for numero, geste in enumerate(machine.lieu_sur, start=1)
        if geste.prise_origine is not None and geste.prise_origine not in fluidnc.cartes
    ]
    return erreurs


def rediger(erreurs: list[str], dossier: Path) -> str:
    lignes = "\n".join(f"  - {erreur}" for erreur in erreurs)
    return f"Réglages faux dans {dossier}, le programme ne démarre pas :\n{lignes}"


# ------------------------------------------------------ lecture des fichiers


class _LecteurStrict(yaml.SafeLoader):
    """Lecteur YAML qui refuse un nom écrit deux fois (YAML garderait le second sans rien dire)."""


def _construire_dict(lecteur: _LecteurStrict, noeud: yaml.MappingNode) -> dict[Any, Any]:
    resultat: dict[Any, Any] = {}
    for noeud_cle, noeud_valeur in noeud.value:
        cle = lecteur.construct_object(noeud_cle, deep=True)
        if cle in resultat:
            raise yaml.constructor.ConstructorError(
                None, None, f"« {cle} » est écrit deux fois", noeud_cle.start_mark
            )
        resultat[cle] = lecteur.construct_object(noeud_valeur, deep=True)
    return resultat


_LecteurStrict.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construire_dict)


def lire_yaml(chemin: Path) -> dict[str, Any]:
    """Lit un fichier YAML qui doit contenir une liste de « nom: valeur »."""
    try:
        with chemin.open(encoding="utf-8") as fichier:
            donnees = yaml.load(fichier, Loader=_LecteurStrict)
    except yaml.YAMLError as erreur:
        repere = getattr(erreur, "problem_mark", None)
        ligne = f", ligne {repere.line + 1}" if repere is not None else ""
        probleme = getattr(erreur, "problem", None) or str(erreur)
        raise ErreurReglages(f"{chemin.name}{ligne} : fichier mal écrit ({probleme})") from None
    except UnicodeDecodeError:
        raise ErreurReglages(f"{chemin.name} : fichier non enregistré en UTF-8") from None
    if donnees is None:
        raise ErreurReglages(f"{chemin.name} : fichier vide")
    if not isinstance(donnees, dict):
        raise ErreurReglages(f"{chemin.name} : le fichier doit être une liste de « nom: valeur »")
    return donnees


# ---------------------------------------------- erreurs de pydantic en français

_MESSAGES = {
    "missing": "manque",
    "extra_forbidden": "nom inconnu (faute de frappe ?)",
    "float_parsing": "doit être un nombre",
    "float_type": "doit être un nombre",
    "int_parsing": "doit être un nombre entier",
    "int_type": "doit être un nombre entier",
    "int_from_float": "doit être un nombre entier",
    "bool_parsing": "doit être « true » (oui) ou « false » (non)",
    "bool_type": "doit être « true » (oui) ou « false » (non)",
    "string_type": "doit être un texte (entre guillemets s'il n'a que des chiffres)",
    "dict_type": "doit être une liste de « nom: valeur »",
    "list_type": "doit être une liste (une ligne « - nom » par élément)",
    "model_type": "doit être une liste de « nom: valeur »",
    "tuple_type": "doit être deux nombres entre crochets, par exemple [0.0, 1.0]",
    "string_pattern_mismatch": "nom à écrire en minuscules, sans accent ni espace (a-z, 0-9, _)",
}


def _message(detail: dict[str, Any]) -> str:
    sorte = detail["type"]
    contexte = detail.get("ctx", {})
    if sorte == "string_pattern_mismatch" and str(contexte.get("pattern", "")).startswith("^#"):
        return 'couleur à écrire « #RRGGBB » entre guillemets (exemple : "#00A000")'
    if sorte in _MESSAGES:
        return _MESSAGES[sorte]
    if sorte in ("too_short", "too_long") and detail["loc"] and detail["loc"][-1] == "course":
        return "doit être deux nombres entre crochets, par exemple [0.0, 1.0]"
    if sorte == "too_short":
        return "ne doit pas être vide" if contexte.get("min_length") == 1 else "trop court"
    if sorte == "too_long":
        return "trop d'éléments"
    if sorte == "greater_than":
        return f"doit être plus grand que {contexte['gt']}"
    if sorte == "greater_than_equal":
        return f"doit valoir au moins {contexte['ge']}"
    if sorte == "less_than":
        return f"doit être plus petit que {contexte['lt']}"
    if sorte == "less_than_equal":
        return f"doit valoir au plus {contexte['le']}"
    if sorte == "literal_error":
        return f"doit être l'un de : {contexte['expected']}"
    if sorte == "union_tag_invalid":
        return f"type: doit être l'un de : {contexte['expected_tags']}"
    if sorte == "union_tag_not_found":
        return f"« {contexte['discriminator'].strip(chr(39))} » manque"
    if sorte == "value_error":
        return str(contexte["error"])
    return detail["msg"]


def traduire_erreurs(erreur: ValidationError, nom_fichier: str) -> list[str]:
    """Une ligne en français par erreur : « fichier, endroit : ce qui ne va pas »."""
    lignes = []
    for detail in erreur.errors():
        # « [key] » : pydantic signale que l'erreur est dans le nom lui-même.
        # Un nombre : la place dans une liste, comptée à partir de 1 (pydantic part de 0).
        endroit = " → ".join(
            f"n° {morceau + 1}" if isinstance(morceau, int) else str(morceau)
            for morceau in detail["loc"]
            if morceau != "[key]"
        )
        debut = f"{nom_fichier}, {endroit}" if endroit else nom_fichier
        for ligne in _message(detail).split("\n"):
            lignes.append(f"{debut} : {ligne}")
    return lignes
