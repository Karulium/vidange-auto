"""Liste des entrées/sorties de la machine (`docs/entrees-sorties.yaml`).

Chaque capteur, relais ou bus y a un nom, sa carte, sa broche, son type de signal,
sa tension, son état au repos et son module. Le code ne connaît que le nom.

Vérifié par les tests et au démarrage : broche utilisée deux fois, adresse en double
sur un bus, carte ou module inconnu, trop d'entrées ou de sorties sur une carte,
tension trop forte (surtout du 24 V sur une carte sans isolement). Toutes les erreurs
sont listées d'un coup, comme pour les réglages.

Chaque carte lue par le Pi dit aussi comment elle lui est reliée (« liaison ») :
broches GPIO du Pi, puce sur le bus I2C, ou adaptateur USB-série (RS485).
Ce sont ces liaisons que suit `vidange.materiel` pour lire et commander les signaux.
"""

from collections import defaultdict
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import (
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)

from vidange.reglages import (
    ErreurReglages,
    Intervalle,
    Modele,
    Nom,
    lire_yaml,
    rediger,
    traduire_erreurs,
)
from vidange.trame_ze25 import DERNIER_OCTET_SOMME, PREMIER_OCTET_SOMME, trame_valable

ENTREES = ("contact", "pnp", "npn", "mesure")
SORTIES = ("relais", "logique")
BUS = ("i2c", "serie")
# Sortie PWM matérielle du Pi (servo de la caméra du dosage) : commandée par la vision, pas par
# le matériel tout-ou-rien.
PWM = "pwm"
# Types qui ont un état au repos (contact ouvert ou fermé).
AVEC_REPOS = ("contact", "pnp", "npn", "relais")

TypeSignal = Literal["contact", "pnp", "npn", "mesure", "relais", "logique", "i2c", "serie", "pwm"]
# Entrées et sorties tout-ou-rien (pas les mesures).
TOUT_OU_RIEN = ("contact", "pnp", "npn", "relais", "logique")

# Les puces que le Pi sait lire, et le nom de leurs broches (celui de leur fiche technique).
BROCHES_DES_PUCES: dict[str, tuple[str, ...]] = {
    "pcf8574": tuple(f"P{i}" for i in range(8)),
    "mcp23017": (*(f"A{i}" for i in range(8)), *(f"B{i}" for i in range(8))),
    "ads1115": tuple(f"A{i}" for i in range(4)),
}
# Puces qui donnent des entrées/sorties tout-ou-rien (les autres donnent des mesures).
PUCES_TOUT_OU_RIEN = ("pcf8574", "mcp23017")
Appareil = Literal[
    "sht31",
    "ads1115",
    "pcf8574",
    "mcp23017",
    "ze25_o3",
    "sps30",
    "sdp810",
    "nextion",
    "accelerometre",
    "carte_pesee",
    "boite_poste_fut",
    "carte_spray",
]
# Capteur d'ozone Winsen ZE25-O3 : une liaison série à lui seul (un adaptateur USB-RS485 par
# capteur), pas un appareil Modbus (protocole : vidange/trame_ze25.py).
CAPTEUR_OZONE = "ze25_o3"
# Capteur de particules Sensirion SPS30 : une liaison série à lui seul (protocole SHDLC,
# vidange/trame_sps30.py), soit sur un adaptateur USB-RS485, soit sur un UART du Pi.
CAPTEUR_PARTICULES = "sps30"
# Capteur de pression différentielle Sensirion SDP810-125Pa, sur le bus I2C du Pi
# (vidange/trame_sdp810.py).
CAPTEUR_PRESSION = "sdp810"
# Carte de pesée RP2040 + HX711 sur un bus RS485, lue en Modbus (pesee/README.md).
CARTE_PESEE = "carte_pesee"
# Boîte du poste du fût : reçoit par radio les mesures du plateau de pesée et répond sur le même
# bus, en Modbus (tâche 17 bis). Pas une carte RP2040 : son programme n'est pas fait par pesee/.
BOITE_POSTE_FUT = "boite_poste_fut"
# Les appareils de pesée du bus RS485 des pesées.
PESEES_DU_BUS = (CARTE_PESEE, BOITE_POSTE_FUT)
# Carte ESP32 n° 5 du spray, sur son bus RS485 à elle, en Modbus (spray/README.md, tâche 39).
CARTE_SPRAY = "carte_spray"
Texte = Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]


# ---------------------------------------------------- liaison d'une carte au Pi


def _reperes_en_texte(valeur: Any) -> Any:
    """Un repère en chiffres (3: GPIO22) est accepté, comme pour « broche »."""
    if isinstance(valeur, dict):
        return {str(cle).strip(): broche for cle, broche in valeur.items()}
    return valeur


class LiaisonGpio(Modele):
    """Carte branchée directement sur des broches GPIO du Pi (ou le Pi lui-même)."""

    type: Literal["gpio"]
    # Fichier de Linux qui donne accès aux broches (sur le Pi 5 : /dev/gpiochip0).
    fichier: Texte
    # Repère sur la carte → broche du Pi (E1: GPIO17). Sans « broches », les repères des
    # signaux sont déjà des broches du Pi (c'est le cas de la carte « pi » elle-même).
    broches: dict[str, Texte] | None = None
    # Niveau électrique qui veut dire « courant passe » (entrée) ou « relais commandé » (sortie).
    # Beaucoup de cartes relais et d'entrées optocouplées marchent « à l'envers » : bas.
    niveau_actif: Literal["haut", "bas"] = "haut"
    # Résistance de tirage des entrées dans le Pi.
    tirage: Literal["aucun", "haut", "bas"] = "aucun"

    @field_validator("broches", mode="before")
    @classmethod
    def _reperes(cls, valeur: Any) -> Any:
        return _reperes_en_texte(valeur)


class LiaisonI2c(Modele):
    """Carte reliée par une puce sur le bus I2C (extenseur de broches, convertisseur)."""

    type: Literal["i2c"]
    # Le signal de type i2c (dans « signaux ») qui mène à la puce de la carte.
    signal: Nom
    # Repère sur la carte → broche de la puce (K1: P0). Sans « broches », les repères
    # des signaux sont déjà des broches de la puce (A0 pour l'ADS1115).
    broches: dict[str, Texte] | None = None
    niveau_actif: Literal["haut", "bas"] = "haut"
    # Le PCF8574 a toujours un tirage haut ; le MCP23017 en a un qu'on peut mettre.
    tirage: Literal["aucun", "haut"] = "aucun"

    @field_validator("broches", mode="before")
    @classmethod
    def _reperes(cls, valeur: Any) -> Any:
        return _reperes_en_texte(valeur)


class LiaisonUsbSerie(Modele):
    """Carte (adaptateur USB-RS485...) branchée sur un port USB du Pi."""

    type: Literal["usb_serie"]
    # Reconnue par le numéro de série de son USB, jamais par l'ordre des ports.
    numero_serie_usb: Texte
    vitesse_bauds: int = Field(gt=0)
    parite: Literal["aucune", "paire", "impaire"] = "aucune"
    # Attente maximale d'une réponse d'un appareil.
    delai_reponse_s: float = Field(gt=0)


Liaison = Annotated[LiaisonGpio | LiaisonI2c | LiaisonUsbSerie, Field(discriminator="type")]


# ------------------------------------------- réglages des appareils d'un signal


class Conversion(Modele):
    """Mesure analogique : deux points (tension lue → valeur), une droite entre eux."""

    volts: Intervalle
    valeurs: Intervalle

    @model_validator(mode="after")
    def _deux_points_differents(self) -> "Conversion":
        if self.volts[0] == self.volts[1]:
            raise ValueError("les deux tensions de « volts » doivent être différentes")
        return self


class CapteurOzone(Modele):
    """Réglages d'un capteur d'ozone ZE25-O3 (à vérifier sur sa notice papier)."""

    # « envoi_automatique » : le capteur parle tout seul ; « question_reponse » : le Pi demande.
    mode: Literal["envoi_automatique", "question_reponse"]
    # Valeur en ppm = nombre de la trame × ce pas.
    pas_ppm: float = Field(gt=0)
    # Pleine échelle du capteur : à partir de là, la valeur est « au plafond » (≥), pas exacte.
    plafond_ppm: float = Field(gt=0)
    # Sans trame valable depuis ce délai, le capteur est dit muet.
    delai_muet_s: float = Field(gt=0)
    # Positions (de 1 à 7) des 2 octets de la valeur dans la trame de 9 octets, poids fort
    # d'abord. Elles ne sont pas les mêmes en envoi automatique et en question-réponse.
    position_valeur: tuple[int, int]
    # Question-réponse seulement : la trame de question, 9 octets en hexadécimal.
    question: bytes | None = None

    @field_validator("question", mode="before")
    @classmethod
    def _question_en_hexa(cls, valeur: Any) -> Any:
        if isinstance(valeur, str):
            try:
                return bytes.fromhex(valeur)
            except ValueError:
                raise ValueError(
                    "doit s'écrire en hexadécimal (exemple : FF0186000000000079)"
                ) from None
        return valeur

    @model_validator(mode="after")
    def _verifier(self) -> "CapteurOzone":
        erreurs: list[str] = []
        premier, dernier = PREMIER_OCTET_SOMME, DERNIER_OCTET_SOMME
        if not all(premier <= p <= dernier for p in self.position_valeur):
            erreurs.append(f"« position_valeur » : des positions de {premier} à {dernier}")
        if self.position_valeur[0] == self.position_valeur[1]:
            erreurs.append("« position_valeur » : les 2 positions doivent être différentes")
        if self.mode == "question_reponse":
            if self.question is None:
                erreurs.append("en question-réponse, « question » (la trame à envoyer) est requise")
            elif not trame_valable(self.question):
                erreurs.append(
                    "« question » : une trame de 9 octets commençant par FF, "
                    "avec la bonne somme de contrôle"
                )
        elif self.question is not None:
            erreurs.append("« question » ne sert qu'en question-réponse")
        if erreurs:
            raise ValueError("\n".join(erreurs))
        return self


class CapteurParticules(Modele):
    """Réglages d'un capteur de particules SPS30 (protocole à vérifier sur sa notice)."""

    # La concentration en masse (µg/m³) que le Pi lit : pm1_0, pm2_5, pm4_0 ou pm10.
    grandeur: Literal["pm1_0", "pm2_5", "pm4_0", "pm10"]
    # Sans mesure valable depuis ce délai, le capteur est dit muet.
    delai_muet_s: float = Field(gt=0)
    # Vitesse (bauds) quand le capteur est sur un UART du Pi ; sur un adaptateur USB-RS485, la
    # vitesse est celle de la carte (liaison) et cette ligne est interdite.
    vitesse_bauds: int | None = Field(default=None, gt=0)
    # Attente maximale d'une réponse (s), sur un UART du Pi seulement (comme la vitesse).
    delai_reponse_s: float | None = Field(default=None, gt=0)


class CapteurPression(Modele):
    """Réglages d'un capteur de pression différentielle SDP810 (le sens des tuyaux)."""

    # Vrai si les tuyaux sont branchés à l'envers : la pression lue est alors changée de signe
    # pour que « enceinte plus haute que le conteneur » soit positif.
    inverser: bool = False


class SortiePwm(Modele):
    """Sortie PWM matérielle du Pi 5 vers un module PWM → 0-10 V (EXEMPLES à vérifier)."""

    fichier: Annotated[str, StringConstraints(pattern=r"^/sys/class/pwm/pwmchip[0-9]+$")]
    canal: int = Field(ge=0, le=3)
    # Fréquence de la porteuse : la période (µs) que demande la notice du module.
    periode_us: int = Field(gt=0)
    # Tension de sortie du module (V) quand le rapport cyclique est de 100 %.
    pleine_echelle_v: float = Field(gt=0)


class Carte(Modele):
    """Une carte où l'on branche des signaux."""

    exemple: bool = False
    description: str
    # Vide : broches à tout faire (GPIO du Pi), seul le double emploi est vérifié.
    entrees: int | None = Field(default=None, ge=0)
    sorties: int | None = Field(default=None, ge=0)
    tension_max: float = Field(gt=0)
    isolee: bool
    # Comment le Pi la lit ou la commande. Sans liaison : le Pi ne la lit pas (cartes FluidNC).
    liaison: Liaison | None = None


class Signal(Modele):
    """Un capteur, un relais ou un bus."""

    exemple: bool = False
    description: str = ""
    carte: Nom
    broche: tuple[str, ...]
    type: TypeSignal
    tension: float = Field(gt=0)
    repos: Literal["ouvert", "ferme"] | None = None
    adresse: int | None = Field(default=None, ge=0)
    module: Nom
    # Pour un bus : l'appareil au bout (obligatoire en i2c).
    appareil: Appareil | None = None
    # Pour un bus sur les broches du Pi : le fichier de Linux qui y donne accès (/dev/i2c-1).
    fichier: Texte | None = None
    # Pour une mesure : son unité, et comment passer des volts à la valeur.
    unite: str = ""
    conversion: Conversion | None = None
    # Pour un capteur d'ozone : son protocole et ses seuils.
    ozone: CapteurOzone | None = None
    # Pour un capteur de particules SPS30, de pression SDP810, une consigne PWM → 0-10 V.
    particules: CapteurParticules | None = None
    pression: CapteurPression | None = None
    pwm: SortiePwm | None = None
    # Pour une entrée tout-ou-rien : l'état attendu à la check-list de démarrage (porte fermée,
    # sécurité en état...). Un autre état empêche de lancer la production, avec son nom.
    au_demarrage: Literal["actionne", "repos"] | None = None

    @field_validator("broche", mode="before")
    @classmethod
    def _une_ou_plusieurs(cls, valeur: Any) -> tuple[str, ...]:
        """Une broche seule (E1) ou une liste ([GPIO2, GPIO3]), toujours rangée en liste."""
        if not isinstance(valeur, list):
            valeur = [valeur]
        if not valeur or not all(_est_une_broche(broche) for broche in valeur):
            raise ValueError(
                "doit être une broche (exemple : E1) ou une liste entre crochets "
                "(exemple : [GPIO2, GPIO3])"
            )
        return tuple(str(broche).strip() for broche in valeur)

    @model_validator(mode="after")
    def _verifier_champs(self) -> "Signal":
        erreurs: list[str] = []
        if self.type in AVEC_REPOS and self.repos is None:
            erreurs.append(
                f"un signal de type {self.type} doit dire son état au repos : "
                "« repos: ouvert » ou « repos: ferme »"
            )
        if self.type not in AVEC_REPOS and self.repos is not None:
            erreurs.append(f"« repos » n'a pas de sens pour un signal de type {self.type}")
        if self.type == "i2c" and self.adresse is None:
            erreurs.append("un signal i2c doit avoir son adresse (exemple : « adresse: 0x48 »)")
        if self.type not in BUS and self.adresse is not None:
            erreurs.append("« adresse » ne sert qu'aux bus (i2c, serie)")
        if self.type == "i2c" and self.appareil is None:
            erreurs.append(
                "un signal i2c doit dire quel appareil est au bout (exemple : « appareil: sht31 »)"
            )
        for champ in ("appareil", "fichier"):
            if self.type not in BUS and getattr(self, champ) is not None:
                erreurs.append(f"« {champ} » ne sert qu'aux bus (i2c, serie)")
        if self.au_demarrage is not None and self.type not in ("contact", "pnp", "npn"):
            erreurs.append("« au_demarrage » ne sert qu'aux entrées contact, pnp ou npn")
        if self.conversion is not None and self.type != "mesure":
            erreurs.append("« conversion » ne sert qu'aux signaux de type mesure")
        if self.appareil == CAPTEUR_OZONE:
            if self.ozone is None:
                erreurs.append("un capteur d'ozone doit dire son protocole (« ozone: »)")
            if self.type != "serie":
                erreurs.append("un capteur d'ozone est sur une liaison série (« type: serie »)")
            if self.adresse is not None:
                erreurs.append("un capteur d'ozone n'a pas d'adresse (ce n'est pas du Modbus)")
        elif self.ozone is not None:
            erreurs.append(f"« ozone » ne sert qu'à un appareil {CAPTEUR_OZONE}")
        if self.appareil == CAPTEUR_PARTICULES:
            if self.particules is None:
                erreurs.append("un capteur de particules doit dire ses réglages (« particules: »)")
            if self.type != "serie":
                erreurs.append(
                    "un capteur de particules est sur une liaison série (« type: serie »)"
                )
            if self.adresse is not None:
                erreurs.append("un capteur de particules n'a pas d'adresse (adresse SHDLC fixe)")
        elif self.particules is not None:
            erreurs.append(f"« particules » ne sert qu'à un appareil {CAPTEUR_PARTICULES}")
        if self.appareil == CAPTEUR_PRESSION:
            if self.pression is None:
                erreurs.append("un capteur de pression doit dire ses réglages (« pression: »)")
            if self.type != "i2c":
                erreurs.append("un capteur de pression est sur le bus I2C (« type: i2c »)")
        elif self.pression is not None:
            erreurs.append(f"« pression » ne sert qu'à un appareil {CAPTEUR_PRESSION}")
        if self.pwm is not None and self.type != "pwm":
            erreurs.append("« pwm » ne sert qu'aux signaux de type pwm")
        if self.appareil in PESEES_DU_BUS:
            if self.type != "serie":
                erreurs.append("une pesée du bus RS485 est sur un bus série (« type: serie »)")
            if self.adresse is None or not 1 <= self.adresse <= 247:
                erreurs.append(
                    "une pesée du bus RS485 doit avoir son adresse sur le bus, de 1 à 247"
                )
        if self.appareil == CARTE_SPRAY:
            if self.type != "serie":
                erreurs.append("la carte du spray est sur un bus RS485 (« type: serie »)")
            if self.adresse is None or not 1 <= self.adresse <= 247:
                erreurs.append("la carte du spray doit avoir son adresse Modbus, de 1 à 247")
        if erreurs:
            raise ValueError("\n".join(erreurs))
        return self


def _est_une_broche(broche: Any) -> bool:
    return isinstance(broche, str | int) and not isinstance(broche, bool) and str(broche).strip()


class EntreesSorties(Modele):
    """entrees-sorties.yaml en entier."""

    tension_max_sans_isolement: float = Field(gt=0)
    # Broches du Pi prises par les bus, ports série et PWM : aucune carte tout-ou-rien dessus.
    gpio_reserves: list[Texte] = Field(default_factory=list)
    modules: list[Nom] = Field(min_length=1)
    cartes: dict[Nom, Carte] = Field(min_length=1)
    signaux: dict[Nom, Signal] = Field(default_factory=dict)

    def exemples(self) -> list[str]:
        """Noms des cartes et signaux encore marqués « exemple »."""
        return [
            nom for nom, ligne in [*self.cartes.items(), *self.signaux.items()] if ligne.exemple
        ]

    @model_validator(mode="after")
    def _verifier_ensemble(self) -> "EntreesSorties":
        erreurs: list[str] = []
        for nom, signal in self.signaux.items():
            if signal.module not in self.modules:
                erreurs.append(
                    f"signal « {nom} » : module inconnu « {signal.module} » "
                    f"(modules connus : {', '.join(self.modules)})"
                )
            if signal.carte not in self.cartes:
                erreurs.append(f"signal « {nom} » : carte inconnue « {signal.carte} »")
            else:
                erreurs.extend(self._verifier_tension(nom, signal))
        connus = {nom: s for nom, s in self.signaux.items() if s.carte in self.cartes}
        erreurs.extend(self._verifier_broches(connus))
        erreurs.extend(self._verifier_adresses(connus))
        erreurs.extend(self._verifier_nombres(connus))
        erreurs.extend(self._verifier_fichiers(connus))
        erreurs.extend(self._verifier_liaisons(connus))
        erreurs.extend(self._verifier_particules(connus))
        if erreurs:
            raise ValueError("\n".join(erreurs))
        return self

    def _verifier_tension(self, nom: str, signal: Signal) -> list[str]:
        carte = self.cartes[signal.carte]
        if not carte.isolee and signal.tension > self.tension_max_sans_isolement:
            return [
                f"signal « {nom} » : {signal.tension:g} V sur la carte « {signal.carte} » "
                "qui n'est pas isolée : la brancher sur une carte d'entrées optocouplées "
                "ou passer par un relais"
            ]
        if signal.tension > carte.tension_max:
            return [
                f"signal « {nom} » : {signal.tension:g} V, plus que les {carte.tension_max:g} V "
                f"acceptés par la carte « {signal.carte} »"
            ]
        return []

    @staticmethod
    def _verifier_broches(signaux: dict[str, Signal]) -> list[str]:
        """Une broche ne sert qu'à un signal, sauf un bus partagé (chacun son adresse)."""
        par_broche: dict[tuple[str, str], list[str]] = defaultdict(list)
        reperes: dict[tuple[str, str], str] = {}
        for nom, signal in signaux.items():
            for broche in signal.broche:
                # GPIO2 et gpio2 sont la même broche.
                cle = (signal.carte, broche.lower())
                par_broche[cle].append(nom)
                reperes.setdefault(cle, broche)
        erreurs = []
        for cle, noms in par_broche.items():
            if len(noms) < 2:
                continue
            types = {signaux[nom].type for nom in noms}
            bus_partage = len(types) == 1 and types <= set(BUS)
            if bus_partage and all(signaux[nom].adresse is not None for nom in noms):
                continue
            message = (
                f"carte « {cle[0]} », broche {reperes[cle]} : utilisée par plusieurs signaux "
                f"({', '.join(noms)})"
            )
            if bus_partage:
                message += " ; sur un bus partagé, chacun doit avoir son adresse"
            erreurs.append(message)
        return erreurs

    @staticmethod
    def _verifier_adresses(signaux: dict[str, Signal]) -> list[str]:
        """Sur un même bus (même carte, mêmes broches), deux appareils n'ont pas la même adresse."""
        par_adresse: dict[tuple[str, frozenset[str], int], list[str]] = defaultdict(list)
        for nom, signal in signaux.items():
            if signal.type in BUS and signal.adresse is not None:
                broches = frozenset(broche.lower() for broche in signal.broche)
                par_adresse[(signal.carte, broches, signal.adresse)].append(nom)
        erreurs = []
        for (carte, _, adresse), noms in par_adresse.items():
            if len(noms) > 1:
                bus = signaux[noms[0]]
                erreurs.append(
                    f"bus {bus.type} de la carte « {carte} » ({', '.join(bus.broche)}) : "
                    f"adresse 0x{adresse:02x} utilisée par plusieurs signaux ({', '.join(noms)})"
                )
        return erreurs

    def _verifier_nombres(self, signaux: dict[str, Signal]) -> list[str]:
        """Pas plus d'entrées ni de sorties branchées que la carte n'en a."""
        erreurs = []
        for nom_carte, carte in self.cartes.items():
            sur_la_carte = [s for s in signaux.values() if s.carte == nom_carte]
            for sorte, types, disponibles in (
                ("entrées", ENTREES, carte.entrees),
                ("sorties", SORTIES, carte.sorties),
            ):
                branchees = sum(1 for s in sur_la_carte if s.type in types)
                if disponibles is not None and branchees > disponibles:
                    erreurs.append(
                        f"carte « {nom_carte} » : {branchees} {sorte} branchées "
                        f"pour {disponibles} disponibles"
                    )
        return erreurs

    @staticmethod
    def _verifier_fichiers(signaux: dict[str, Signal]) -> list[str]:
        """Les appareils d'un même bus passent par le même fichier de Linux."""
        par_bus: dict[tuple[str, frozenset[str]], dict[str, str]] = defaultdict(dict)
        for nom, signal in signaux.items():
            if signal.fichier is not None:
                broches = frozenset(broche.lower() for broche in signal.broche)
                par_bus[(signal.carte, broches)][nom] = signal.fichier
        return [
            f"signaux {', '.join(fichiers)} : même bus mais pas le même « fichier »"
            for fichiers in par_bus.values()
            if len(set(fichiers.values())) > 1
        ]

    def _verifier_liaisons(self, signaux: dict[str, Signal]) -> list[str]:
        """Cartes lues par le Pi : liaison complète, broches qui existent, pas de double emploi."""
        erreurs: list[str] = []
        # Broches du Pi prises, par fichier GPIO : (fichier, broche) → qui la prend.
        prises: dict[tuple[str, str], list[str]] = defaultdict(list)
        for nom_carte, carte in self.cartes.items():
            sur_la_carte = {n: s for n, s in signaux.items() if s.carte == nom_carte}
            liaison = carte.liaison
            sprays = [n for n, s in sur_la_carte.items() if s.appareil == CARTE_SPRAY]
            if sprays and not isinstance(liaison, LiaisonUsbSerie):
                erreurs.append(
                    f"signal « {sprays[0]} » : la carte du spray se lit par un adaptateur "
                    f"USB-RS485 (la carte « {nom_carte} » doit avoir « liaison: usb_serie »)"
                )
            if sprays and len(sur_la_carte) > 1:
                erreurs.append(
                    f"carte « {nom_carte} » : la carte du spray a son bus à elle (une panne du "
                    f"spray ne doit pas couper les autres) ; signaux en trop : "
                    f"{', '.join(n for n in sur_la_carte if n not in sprays[:1])}"
                )
            if liaison is None:
                continue
            if isinstance(liaison, LiaisonUsbSerie):
                for nom, signal in sur_la_carte.items():
                    if signal.type != "serie":
                        erreurs.append(
                            f"signal « {nom} » : la carte « {nom_carte} » est un port série, "
                            f"elle ne porte que des signaux de type serie (pas {signal.type})"
                        )
                continue
            puce = None
            if isinstance(liaison, LiaisonI2c):
                puce = self._puce_de(nom_carte, liaison, erreurs)
                if puce is None:
                    continue
            erreurs.extend(self._verifier_broches_liaison(nom_carte, liaison, sur_la_carte, puce))
            if isinstance(liaison, LiaisonGpio):
                if liaison.broches is None:
                    for nom, signal in sur_la_carte.items():
                        for broche in signal.broche:
                            prises[(liaison.fichier, broche.lower())].append(nom)
                else:
                    for repere, broche in liaison.broches.items():
                        prises[(liaison.fichier, broche.lower())].append(f"{nom_carte}/{repere}")
        reserves = {broche.lower() for broche in self.gpio_reserves}
        for nom_carte, carte in self.cartes.items():
            liaison = carte.liaison
            if isinstance(liaison, LiaisonGpio) and liaison.broches is not None:
                for repere, broche in liaison.broches.items():
                    if broche.lower() in reserves:
                        erreurs.append(
                            f"carte « {nom_carte} », repère {repere} : la broche {broche} du Pi "
                            "est réservée aux bus et ports série (gpio_reserves)"
                        )
        for nom, signal in signaux.items():
            carte = self.cartes[signal.carte]
            if isinstance(carte.liaison, LiaisonGpio) and carte.liaison.broches is None:
                if signal.type in TOUT_OU_RIEN:
                    for broche in signal.broche:
                        if broche.lower() in reserves:
                            erreurs.append(
                                f"signal « {nom} » : la broche {broche} du Pi est réservée aux "
                                "bus et ports série (gpio_reserves)"
                            )
        for (fichier, broche), qui in prises.items():
            # Un bus partagé est déjà vérifié par _verifier_broches.
            directs = [q for q in qui if "/" not in q]
            if len(qui) > 1 and len(directs) < len(qui):
                erreurs.append(
                    f"broche {broche.upper()} du Pi ({fichier}) : prise plusieurs fois "
                    f"({', '.join(dict.fromkeys(qui))})"
                )
        return erreurs

    def _verifier_particules(self, signaux: dict[str, Signal]) -> list[str]:
        """La vitesse d'un SPS30 vient de sa carte (USB-RS485) ou de lui-même (UART du Pi)."""
        erreurs = []
        for nom, signal in signaux.items():
            if signal.appareil != CAPTEUR_PARTICULES or signal.particules is None:
                continue
            liaison = self.cartes[signal.carte].liaison
            vitesse = signal.particules.vitesse_bauds
            delai = signal.particules.delai_reponse_s
            if isinstance(liaison, LiaisonUsbSerie):
                if vitesse is not None or delai is not None:
                    erreurs.append(
                        f"signal « {nom} » : « vitesse_bauds » et « delai_reponse_s » sont "
                        f"interdites ici, ils sont ceux de la carte « {signal.carte} » (liaison)"
                    )
            elif isinstance(liaison, LiaisonGpio):
                if vitesse is None or delai is None:
                    erreurs.append(
                        f"signal « {nom} » : sur un UART du Pi, « particules → vitesse_bauds » "
                        "et « delai_reponse_s » sont requis"
                    )
                if signal.fichier is None:
                    erreurs.append(
                        f"signal « {nom} » : sur un UART du Pi, le « fichier » est requis "
                        "(exemple : /dev/ttyAMA3)"
                    )
            else:
                erreurs.append(
                    f"signal « {nom} » : un capteur de particules est sur un adaptateur "
                    "USB-RS485 ou sur un UART du Pi"
                )
        return erreurs

    def _puce_de(self, nom_carte: str, liaison: LiaisonI2c, erreurs: list[str]) -> str | None:
        bus = self.signaux.get(liaison.signal)
        if bus is None or bus.type != "i2c":
            erreurs.append(
                f"carte « {nom_carte} » : liaison → signal « {liaison.signal} » "
                "doit être un signal de type i2c de la liste"
            )
            return None
        if bus.appareil not in BROCHES_DES_PUCES:
            erreurs.append(
                f"carte « {nom_carte} » : l'appareil du signal « {liaison.signal} » "
                f"({bus.appareil}) n'a pas de broches ; puces possibles : "
                f"{', '.join(BROCHES_DES_PUCES)}"
            )
            return None
        if bus.fichier is None:
            erreurs.append(
                f"carte « {nom_carte} » : le signal « {liaison.signal} » doit avoir son "
                "« fichier » (exemple : /dev/i2c-1)"
            )
            return None
        if bus.appareil == "ads1115" and (
            liaison.niveau_actif != "haut" or liaison.tirage != "aucun"
        ):
            erreurs.append(
                f"carte « {nom_carte} » : « niveau_actif » et « tirage » "
                "ne servent pas à un ads1115"
            )
        return bus.appareil

    @staticmethod
    def _verifier_broches_liaison(
        nom_carte: str,
        liaison: LiaisonGpio | LiaisonI2c,
        sur_la_carte: dict[str, Signal],
        puce: str | None,
    ) -> list[str]:
        erreurs = []
        directe = isinstance(liaison, LiaisonGpio) and liaison.broches is None
        for nom, signal in sur_la_carte.items():
            if puce == "ads1115":
                permis = ("mesure",)
            elif directe:
                # Le Pi lui-même : pas d'entrée analogique, mais ses bus et ses sorties PWM.
                permis = (*TOUT_OU_RIEN, *BUS, PWM)
            else:
                permis = TOUT_OU_RIEN
            if signal.type not in permis:
                erreurs.append(
                    f"signal « {nom} » : un signal de type {signal.type} ne peut pas être "
                    f"sur la carte « {nom_carte} » (types possibles : {', '.join(permis)})"
                )
            if directe and signal.type in BUS and signal.fichier is None:
                erreurs.append(
                    f"signal « {nom} » : un bus sur les broches du Pi doit avoir son « fichier » "
                    "(exemple : /dev/i2c-1)"
                )
            if liaison.broches is not None:
                for broche in signal.broche:
                    if broche not in liaison.broches:
                        erreurs.append(
                            f"signal « {nom} » : repère {broche} absent de la liaison de la carte "
                            f"« {nom_carte} » (liaison → broches)"
                        )
        if puce is not None:
            if liaison.broches is not None:
                des_puces = [(f"liaison → broches → {r}", b) for r, b in liaison.broches.items()]
            else:
                des_puces = [
                    (f"signal « {n} »", b) for n, s in sur_la_carte.items() for b in s.broche
                ]
            vues: dict[str, str] = {}
            for ou, broche in des_puces:
                if broche not in BROCHES_DES_PUCES[puce]:
                    erreurs.append(
                        f"carte « {nom_carte} », {ou} : la puce {puce} n'a pas de broche "
                        f"{broche} (broches : {', '.join(BROCHES_DES_PUCES[puce])})"
                    )
                elif broche in vues:
                    erreurs.append(
                        f"carte « {nom_carte} » : broche {broche} de la puce prise deux fois "
                        f"({vues[broche]}, {ou})"
                    )
                vues.setdefault(broche, ou)
        return erreurs


def charger_entrees_sorties(chemin: Path) -> EntreesSorties:
    """Lit et vérifie la liste des entrées/sorties, ou lève ErreurReglages."""
    if not chemin.is_file():
        raise ErreurReglages(rediger([f"{chemin.name} : fichier manquant"], chemin.parent))
    try:
        return EntreesSorties.model_validate(lire_yaml(chemin))
    except ErreurReglages as erreur:
        raise ErreurReglages(rediger([str(erreur)], chemin.parent)) from None
    except ValidationError as erreur:
        raise ErreurReglages(
            rediger(traduire_erreurs(erreur, chemin.name), chemin.parent)
        ) from None
