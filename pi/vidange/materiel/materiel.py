"""Les entrées et sorties du Pi, par leur nom dans `docs/entrees-sorties.yaml`.

    with Materiel(liste) as materiel:            # vrai matériel
        materiel.lire("reed_panneau_poste_fut")  # True = capteur actionné
        materiel.ecrire("voyant_buzzer", True)   # True = relais commandé
        materiel.mesurer("vide_venturi")         # valeur dans son unité (kPa...)
        materiel.lire_ozone("ozone_dedans")           # MesureOzone (ppm, au plafond ou non)
        materiel.ambiance("sht31_armoire")       # Ambiance(temperature_c, humidite_pct)
        materiel.peser("pesee_griffe")            # mesure brute d'une pesée du bus RS485
        materiel.lire_carte_pesee("pesee_griffe") # tout ce qu'elle dit (MesureCarte)

Pour les tests et le simulateur : `Materiel(liste, FausseFabrique(liste))`.

Sens des valeurs (le code ne pense jamais en niveaux électriques) :
- entrée : True = **actionné** (contact repos ouvert qui se ferme, capteur qui détecte,
  contact repos fermé qui s'ouvre) ;
- sortie : True = **commandé** (bobine du relais alimentée). Au départ et à l'arrêt,
  toutes les sorties sont au repos (non commandées).

Le niveau électrique dépend de la carte (« niveau_actif ») et du contact (« repos ») :
c'est calculé ici, une fois pour toutes.

Rien ici ne protège personne : la sécurité est câblée. Si une puce ne répond pas,
la lecture lève ErreurMateriel (avec le nom du signal) et le reste continue.
"""

import threading
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Literal, NamedTuple, Protocol

from vidange.entrees_sorties import (
    BOITE_POSTE_FUT,
    CAPTEUR_OZONE,
    ENTREES,
    PESEES_DU_BUS,
    SORTIES,
    EntreesSorties,
    LiaisonGpio,
    LiaisonUsbSerie,
    Signal,
)
from vidange.journal import donner_journal
from vidange.materiel import carte_pesee
from vidange.materiel.carte_pesee import MesureCarte
from vidange.materiel.modbus import ClientModbus, PortSerie
from vidange.materiel.ozone import LecteurOzone, MesureOzone
from vidange.materiel.puces import (
    Ads1115,
    BusI2c,
    BusI2cLinux,
    ErreurMateriel,
    Lignes,
    LignesGpio,
    Mcp23017,
    Pcf8574,
    PeseeMuette,
    Sht31,
    Tirage,
)

journal = donner_journal("materiel")


class Ambiance(NamedTuple):
    temperature_c: float
    humidite_pct: float


# --------------------------------------------- d'où vient chaque signal (le plan)

# Une ressource : ("gpio", fichier), ("i2c", fichier, adresse, puce) ou ("serie", carte).
Ressource = tuple


@dataclass(frozen=True)
class Branchement:
    """Comment un signal arrive au Pi, tiré de la liste des entrées/sorties."""

    nom: str
    sorte: Literal["entree", "sortie", "mesure", "ambiance", "ozone", "pesee"]
    ressource: Ressource
    # Broche tout-ou-rien (GPIO17, P0...) ou voie de l'ADS1115 (A0...).
    broche: str = ""
    niveau_actif_haut: bool = True
    # Contact fermé au repos : actionné = courant coupé.
    repos_ferme: bool = False
    tirage: Tirage = "aucun"

    def niveau(self, actif: bool) -> bool:
        """Niveau électrique (True = haut) d'un signal actionné ou commandé (actif)."""
        courant = actif != self.repos_ferme if self.sorte == "entree" else actif
        return courant == self.niveau_actif_haut

    def actif(self, haut: bool) -> bool:
        """L'inverse : le niveau électrique lu → actionné ou non."""
        courant = haut == self.niveau_actif_haut
        return courant != self.repos_ferme if self.sorte == "entree" else courant


def _bus_i2c(signal: Signal) -> Ressource:
    return ("i2c", signal.fichier, signal.adresse, signal.appareil)


def tracer_branchements(liste: EntreesSorties) -> dict[str, Branchement]:
    """Les signaux que le Pi lit ou commande lui-même (les autres sont ignorés ici).

    La liste a déjà été vérifiée au chargement : chaque référence existe.
    """
    branchements = {}
    for nom, signal in liste.signaux.items():
        liaison = liste.cartes[signal.carte].liaison
        if liaison is None:
            continue
        if isinstance(liaison, LiaisonUsbSerie):
            if signal.appareil == CAPTEUR_OZONE:
                branchements[nom] = Branchement(nom, "ozone", ("serie", signal.carte))
            elif signal.appareil in PESEES_DU_BUS:
                branchements[nom] = Branchement(nom, "pesee", ("serie", signal.carte))
            continue
        if signal.type == "i2c" and signal.appareil == "sht31":
            branchements[nom] = Branchement(nom, "ambiance", _bus_i2c(signal))
            continue
        if signal.type not in (*ENTREES, *SORTIES):
            continue
        broche = signal.broche[0]
        if liaison.broches is not None:
            broche = liaison.broches[broche]
        if isinstance(liaison, LiaisonGpio):
            ressource: Ressource = ("gpio", liaison.fichier)
        else:
            ressource = _bus_i2c(liste.signaux[liaison.signal])
        if signal.type == "mesure":
            branchements[nom] = Branchement(nom, "mesure", ressource, broche)
            continue
        branchements[nom] = Branchement(
            nom,
            "entree" if signal.type in ENTREES else "sortie",
            ressource,
            broche,
            niveau_actif_haut=liaison.niveau_actif == "haut",
            repos_ferme=signal.repos == "ferme",
            tirage=liaison.tirage,
        )
    return branchements


# ---------------------------------------------------- de quoi ouvrir le matériel


class Fabrique(Protocol):
    """Ce qui ouvre le matériel : le vrai (VraieFabrique) ou le faux (FausseFabrique)."""

    def gpio(self, fichier: str) -> Lignes: ...

    def bus_i2c(self, fichier: str) -> BusI2c: ...

    def port_serie(self, liaison: LiaisonUsbSerie) -> PortSerie: ...


class VraieFabrique:
    def gpio(self, fichier: str) -> Lignes:
        return LignesGpio(fichier)

    def bus_i2c(self, fichier: str) -> BusI2c:
        return BusI2cLinux(fichier)

    def port_serie(self, liaison: LiaisonUsbSerie) -> PortSerie:
        import serial

        from vidange.fluidnc.ports import trouver_port

        parites = {
            "aucune": serial.PARITY_NONE,
            "paire": serial.PARITY_EVEN,
            "impaire": serial.PARITY_ODD,
        }
        port = serial.Serial()
        try:
            port.port = trouver_port(liaison.numero_serie_usb)
        except Exception as erreur:
            raise OSError(str(erreur)) from None
        port.baudrate = liaison.vitesse_bauds
        port.parity = parites[liaison.parite]
        port.timeout = liaison.delai_reponse_s
        port.write_timeout = liaison.delai_reponse_s
        port.exclusive = True
        port.open()
        # Adaptateur FT232 : il rend les octets reçus au bout de 1 ms au lieu de 16 (le bus des
        # pesées pose plus de 200 questions par seconde).
        try:
            port.set_low_latency_mode(True)
        except (AttributeError, NotImplementedError, OSError, ValueError):
            pass
        return port


# ------------------------------------------------------------------ le Materiel


class Materiel:
    def __init__(
        self,
        liste: EntreesSorties,
        fabrique: Fabrique | None = None,
        seulement: Iterable[str] | None = None,
    ) -> None:
        """`seulement` : n'ouvrir que ces signaux (essais d'une carte à la fois)."""
        self.liste = liste
        self.fabrique = fabrique if fabrique is not None else VraieFabrique()
        self.branchements = tracer_branchements(liste)
        if seulement is not None:
            choisis = set(seulement)
            inconnus = sorted(choisis - set(self.branchements))
            if inconnus:
                raise ErreurMateriel(
                    f"signaux inconnus ou pas lus par le Pi lui-même : {', '.join(inconnus)}"
                )
            self.branchements = {n: b for n, b in self.branchements.items() if n in choisis}
        self._verrou = threading.RLock()
        self._commandes: dict[str, bool] = {}
        self._bus: dict[str, BusI2c] = {}
        self._lignes: dict[Ressource, Lignes] = {}
        self._puces: dict[Ressource, Ads1115 | Sht31] = {}
        self._clients: dict[str, ClientModbus] = {}
        self._ozones: dict[str, LecteurOzone] = {}
        try:
            self._preparer()
        except Exception:
            self.fermer()
            raise

    def _bus_de(self, fichier: str) -> BusI2c:
        if fichier not in self._bus:
            self._bus[fichier] = self.fabrique.bus_i2c(fichier)
        return self._bus[fichier]

    def _preparer(self) -> None:
        """Ouvre chaque puce une fois, met les broches en entrée ou en sortie (au repos)."""
        par_ressource: dict[Ressource, list[Branchement]] = {}
        for branchement in self.branchements.values():
            par_ressource.setdefault(branchement.ressource, []).append(branchement)
        for ressource, groupe in par_ressource.items():
            sorte = ressource[0]
            if sorte == "serie":
                carte = ressource[1]
                liaison = self.liste.cartes[carte].liaison
                assert isinstance(liaison, LiaisonUsbSerie)
                ouvrir = lambda liaison=liaison: self.fabrique.port_serie(liaison)  # noqa: E731
                ozones = [b.nom for b in groupe if b.sorte == "ozone"]
                if ozones:
                    # Un capteur d'ozone a son adaptateur à lui : pas de Modbus, pas de partage.
                    for nom in ozones:
                        reglage = self.liste.signaux[nom].ozone
                        assert reglage is not None
                        self._ozones[nom] = LecteurOzone(ouvrir, reglage, nom=carte)
                else:
                    self._clients[carte] = ClientModbus(ouvrir, nom=carte)
                continue
            if sorte == "i2c" and ressource[3] in ("ads1115", "sht31"):
                classe = Ads1115 if ressource[3] == "ads1115" else Sht31
                self._puces[ressource] = classe(self._bus_de(ressource[1]), ressource[2])
                continue
            if sorte == "gpio":
                lignes: Lignes = self.fabrique.gpio(ressource[1])
            else:
                classe_tor = Pcf8574 if ressource[3] == "pcf8574" else Mcp23017
                lignes = classe_tor(self._bus_de(ressource[1]), ressource[2])
            entrees = {b.broche: b.tirage for b in groupe if b.sorte == "entree"}
            sorties = {b.broche: b.niveau(False) for b in groupe if b.sorte == "sortie"}
            self._lignes[ressource] = lignes
            try:
                lignes.preparer(entrees, sorties)
            except ErreurMateriel as erreur:
                noms = ", ".join(b.nom for b in groupe)
                raise ErreurMateriel(f"{erreur} (signaux {noms})") from None
            for branchement in groupe:
                if branchement.sorte == "sortie":
                    self._commandes[branchement.nom] = False

    def _branchement(self, nom: str, *sortes: str) -> Branchement:
        if nom not in self.liste.signaux:
            raise KeyError(f"signal inconnu « {nom} » (absent de entrees-sorties.yaml)")
        branchement = self.branchements.get(nom)
        if branchement is None:
            raise ErreurMateriel(
                f"signal « {nom} » : le Pi ne le lit pas lui-même (carte sans liaison, ou bus)"
            )
        if branchement.sorte not in sortes:
            raise ErreurMateriel(
                f"signal « {nom} » : c'est un signal de sorte « {branchement.sorte} », "
                f"pas « {' ou '.join(sortes)} »"
            )
        return branchement

    def _au_nom_de(self, nom: str, action):
        try:
            return action()
        except ErreurMateriel as erreur:
            # Même sorte d'erreur (PeseeMuette reste PeseeMuette).
            raise type(erreur)(f"signal « {nom} » : {erreur}") from None
        except OSError as erreur:
            raise ErreurMateriel(f"signal « {nom} » : {erreur}") from None

    # --------------------------------------------------------------- lecture

    def lire(self, nom: str) -> bool:
        """Entrée tout-ou-rien : True = actionnée. Sortie : True = commandée."""
        branchement = self._branchement(nom, "entree", "sortie")
        if branchement.sorte == "sortie":
            return self._commandes[nom]
        lignes = self._lignes[branchement.ressource]
        with self._verrou:
            haut = self._au_nom_de(nom, lambda: lignes.lire(branchement.broche))
        return branchement.actif(haut)

    def lire_entrees(self) -> dict[str, bool | ErreurMateriel]:
        """Toutes les entrées tout-ou-rien ; une entrée illisible donne son erreur."""
        resultat: dict[str, bool | ErreurMateriel] = {}
        for nom, branchement in self.branchements.items():
            if branchement.sorte == "entree":
                try:
                    resultat[nom] = self.lire(nom)
                except ErreurMateriel as erreur:
                    resultat[nom] = erreur
        return resultat

    def mesurer(self, nom: str) -> float:
        """Mesure analogique (ADS1115) ou capteur d'ozone (ppm), dans l'unité du signal."""
        branchement = self._branchement(nom, "mesure", "ozone")
        signal = self.liste.signaux[nom]
        if branchement.sorte == "ozone":
            return self.lire_ozone(nom).ppm
        puce = self._puces[branchement.ressource]
        assert isinstance(puce, Ads1115)
        with self._verrou:
            volts = self._au_nom_de(nom, lambda: puce.mesurer(branchement.broche, signal.tension))
        if signal.conversion is None:
            return volts
        (v0, v1), (y0, y1) = signal.conversion.volts, signal.conversion.valeurs
        return y0 + (volts - v0) * (y1 - y0) / (v1 - v0)

    def lire_ozone(self, nom: str) -> MesureOzone:
        """Mesure d'un capteur d'ozone ZE25-O3. Lève CapteurMuet s'il ne dit plus rien."""
        self._branchement(nom, "ozone")
        lecteur = self._ozones[nom]
        return self._au_nom_de(nom, lecteur.lire)

    def ambiance(self, nom: str) -> Ambiance:
        """Température (°C) et humidité (%) d'un SHT31."""
        branchement = self._branchement(nom, "ambiance")
        puce = self._puces[branchement.ressource]
        assert isinstance(puce, Sht31)
        with self._verrou:
            return Ambiance(*self._au_nom_de(nom, puce.mesurer))

    def peser(self, nom: str) -> int:
        """Mesure brute d'une pesée du bus RS485 (sans unité : voir vidange.pesees).

        Lève ErreurMateriel si elle ne répond pas ; HX711 muet ou radio du plateau muette :
        PeseeMuette."""
        mesure = self.lire_carte_pesee(nom)
        if mesure.hx711_muet:
            raise PeseeMuette(f"signal « {nom} » : HX711 muet (débranché ?)")
        if mesure.radio_muette:
            raise PeseeMuette(f"signal « {nom} » : radio du plateau muette")
        return mesure.brut

    def lire_carte_pesee(self, nom: str) -> MesureCarte:
        """Tout ce que dit une pesée du bus RS485 (pesee/README.md), en une question : carte
        RP2040 (8 registres, signature 0x5053) ou boîte du poste du fût (13 registres, signature
        0x5046, avec le plateau).

        Lève ErreurMateriel si elle ne répond pas ou si ce n'est pas l'appareil attendu."""
        self._branchement(nom, "pesee")
        signal = self.liste.signaux[nom]
        assert signal.adresse is not None
        client = self._clients[signal.carte]
        adresse = signal.adresse
        boite = signal.appareil == BOITE_POSTE_FUT
        nombre = carte_pesee.NB_REGISTRES_BOITE if boite else carte_pesee.NB_REGISTRES
        registres = self._au_nom_de(
            nom, lambda: client.lire_registres(adresse, carte_pesee.FONCTION, 0, nombre)
        )
        decoder = carte_pesee.decoder_boite if boite else carte_pesee.decoder
        return self._au_nom_de(nom, lambda: decoder(registres))

    def unite(self, nom: str) -> str:
        signal = self.liste.signaux[nom]
        if signal.unite:
            return signal.unite
        return "V" if signal.conversion is None and signal.type == "mesure" else ""

    # -------------------------------------------------------------- commande

    def ecrire(self, nom: str, commande: bool) -> None:
        """Sortie : True = commandée (relais alimenté), False = au repos."""
        branchement = self._branchement(nom, "sortie")
        lignes = self._lignes[branchement.ressource]
        with self._verrou:
            self._au_nom_de(
                nom, lambda: lignes.ecrire(branchement.broche, branchement.niveau(commande))
            )
            self._commandes[nom] = commande
        journal.debug("Sortie %s : %s", nom, "commandée" if commande else "au repos")

    def sorties(self) -> Iterator[str]:
        return (nom for nom, b in self.branchements.items() if b.sorte == "sortie")

    def mettre_au_repos(self) -> None:
        """Toutes les sorties au repos ; continue même si l'une échoue."""
        for nom in list(self._commandes):
            try:
                self.ecrire(nom, False)
            except ErreurMateriel as erreur:
                journal.error("Mise au repos impossible : %s", erreur)

    # ----------------------------------------------------------------- fin

    def fermer(self) -> None:
        self.mettre_au_repos()
        for objet in [
            *self._lignes.values(),
            *self._clients.values(),
            *self._ozones.values(),
            *self._bus.values(),
        ]:
            try:
                objet.fermer()
            except Exception as erreur:
                journal.error("Fermeture du matériel : %s", erreur)
        self._lignes.clear()
        self._clients.clear()
        self._ozones.clear()
        self._bus.clear()
        self._puces.clear()
        self._commandes.clear()

    def __enter__(self) -> "Materiel":
        return self

    def __exit__(self, *_: object) -> None:
        self.fermer()
