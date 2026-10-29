"""Faux matériel pour les tests et le simulateur : un faux de chaque capteur et de chaque carte.

Les faux imitent les puces au niveau de leurs octets (registres de l'ADS1115, somme de
contrôle du SHT31, trames Modbus...), pour que le vrai code de `puces.py` et `modbus.py`
soit testé lui aussi. Seules les broches GPIO du Pi sont imitées plus haut (`FauxGpio`).

    faux = FausseFabrique(liste)
    materiel = Materiel(liste, faux)
    faux.actionner("reed_panneau_poste_fut", True)   # le capteur est actionné
    faux.regler("vide_venturi", -40)                  # dans l'unité du signal
    faux.regler_ambiance("sht31_armoire", 28.5, 70)
    faux.regler_pesee("pesee_fut", 1_234_567)        # mesure brute de la carte HX711
    faux.commande("voyant_buzzer")                    # ce qu'a fait le programme
    faux.debrancher("sht31_armoire")                  # la puce ne répond plus
    faux.debrancher("pesee_fut")                      # prise de la pesée débranchée
    faux.carte_pesee("pesee_griffe").hx711_muet = True  # carte du bus RS485 : HX711 muet

Le faux suit le même plan que le vrai (niveau actif, contact au repos, tirage), à l'envers.
"""

import errno
from collections.abc import Mapping

from vidange.entrees_sorties import (
    BROCHES_DES_PUCES,
    CARTE_PESEE,
    EntreesSorties,
    LiaisonUsbSerie,
)
from vidange.materiel import carte_pesee
from vidange.materiel.materiel import Branchement, tracer_branchements
from vidange.materiel.modbus import crc_modbus
from vidange.materiel.puces import Ads1115, BusI2c, Hx711, Tirage, crc_sht31


def _pas_de_reponse() -> OSError:
    return OSError(errno.EREMOTEIO, "Remote I/O error")


# ------------------------------------------------------------------ broches GPIO


class FauxGpio:
    """Les broches GPIO du Pi. Une entrée prend le niveau donné de l'extérieur, sinon son tirage."""

    def __init__(self) -> None:
        self.entrees: dict[str, Tirage] = {}
        self.sorties: dict[str, bool] = {}
        self.exterieur: dict[str, bool] = {}
        self.ferme = False

    def preparer(self, entrees: Mapping[str, Tirage], sorties: Mapping[str, bool]) -> None:
        self.entrees = dict(entrees)
        self.sorties = dict(sorties)

    def lire(self, broche: str) -> bool:
        if broche in self.sorties:
            return self.sorties[broche]
        if broche not in self.entrees:
            raise KeyError(f"faux GPIO : broche {broche} pas préparée")
        return self.exterieur.get(broche, self.entrees[broche] == "haut")

    def ecrire(self, broche: str, haut: bool) -> None:
        if broche not in self.sorties:
            raise KeyError(f"faux GPIO : broche {broche} pas préparée en sortie")
        self.sorties[broche] = haut

    def niveau(self, broche: str) -> bool:
        return self.lire(broche)

    def fermer(self) -> None:
        self.ferme = True


# ------------------------------------------------------------------- bus I2C


class FauxAppareilI2c:
    def __init__(self) -> None:
        self.debranche = False

    def recevoir(self, donnees: bytes) -> None:
        raise NotImplementedError

    def envoyer(self, nombre: int) -> bytes:
        raise NotImplementedError


class FauxBusI2c:
    """Un bus I2C où l'on accroche des faux appareils à leur adresse."""

    def __init__(self) -> None:
        self.appareils: dict[int, FauxAppareilI2c] = {}
        self.ferme = False

    def _appareil(self, adresse: int) -> FauxAppareilI2c:
        appareil = self.appareils.get(adresse)
        if appareil is None or appareil.debranche:
            raise _pas_de_reponse()
        return appareil

    def ecrire(self, adresse: int, donnees: bytes) -> None:
        self._appareil(adresse).recevoir(bytes(donnees))

    def lire(self, adresse: int, nombre: int) -> bytes:
        return self._appareil(adresse).envoyer(nombre)

    def ecrire_lire(self, adresse: int, donnees: bytes, nombre: int) -> bytes:
        self.ecrire(adresse, donnees)
        return self.lire(adresse, nombre)

    def fermer(self) -> None:
        self.ferme = True


class FauxSht31(FauxAppareilI2c):
    def __init__(self, temperature_c: float = 25.0, humidite_pct: float = 50.0) -> None:
        super().__init__()
        self.temperature_c = temperature_c
        self.humidite_pct = humidite_pct
        self._pret = False
        self.abime = False

    def recevoir(self, donnees: bytes) -> None:
        self._pret = donnees == bytes([0x24, 0x00])

    def envoyer(self, nombre: int) -> bytes:
        if not self._pret:
            raise _pas_de_reponse()  # le vrai répond NACK sans mesure demandée
        self._pret = False
        brut_t = round((self.temperature_c + 45) * 65535 / 175)
        brut_h = round(self.humidite_pct * 65535 / 100)
        octets = b""
        for brut in (max(0, min(65535, brut_t)), max(0, min(65535, brut_h))):
            mot = brut.to_bytes(2, "big")
            octets += mot + bytes([crc_sht31(mot) ^ (0xFF if self.abime else 0)])
        return octets[:nombre]


class FauxAds1115(FauxAppareilI2c):
    """Tensions réglables sur A0 à A3. La conversion est finie tout de suite."""

    def __init__(self) -> None:
        super().__init__()
        self.tensions = dict.fromkeys(BROCHES_DES_PUCES["ads1115"], 0.0)
        self._registres = {Ads1115.CONVERSION: 0, Ads1115.CONFIG: 0x8583}
        self._pointeur = 0

    def recevoir(self, donnees: bytes) -> None:
        self._pointeur = donnees[0]
        if len(donnees) == 3 and self._pointeur == Ads1115.CONFIG:
            config = int.from_bytes(donnees[1:3], "big")
            voie = BROCHES_DES_PUCES["ads1115"][(config >> 12 & 0b111) - 0b100]
            echelles = {g: e for e, g in Ads1115.GAINS.items()}
            echelle = echelles.get(config >> 9 & 0b111, 0.256)
            brut = round(self.tensions[voie] * 32768 / echelle)
            self._registres[Ads1115.CONVERSION] = max(-32768, min(32767, brut)) & 0xFFFF
            self._registres[Ads1115.CONFIG] = config | 0x8000

    def envoyer(self, nombre: int) -> bytes:
        return self._registres.get(self._pointeur, 0).to_bytes(2, "big")[:nombre]


class FauxPcf8574(FauxAppareilI2c):
    """Une broche écrite à 1 prend le niveau donné de l'extérieur (tirée en haut sinon)."""

    def __init__(self) -> None:
        super().__init__()
        self.octet = 0xFF
        self.exterieur: dict[str, bool] = {}

    def recevoir(self, donnees: bytes) -> None:
        self.octet = donnees[-1]

    def niveau(self, broche: str) -> bool:
        numero = BROCHES_DES_PUCES["pcf8574"].index(broche)
        if not self.octet >> numero & 1:
            return False
        return self.exterieur.get(broche, True)

    def envoyer(self, nombre: int) -> bytes:
        octet = sum(1 << i for i, b in enumerate(BROCHES_DES_PUCES["pcf8574"]) if self.niveau(b))
        return bytes([octet])[:nombre]


class FauxMcp23017(FauxAppareilI2c):
    """Registres de la puce (mode d'origine, adresse qui avance seule à chaque octet)."""

    def __init__(self) -> None:
        super().__init__()
        self.registres = [0] * 0x16
        self.registres[0x00] = self.registres[0x01] = 0xFF  # tout en entrée au départ
        self.exterieur: dict[str, bool] = {}
        self._pointeur = 0

    def _mot(self, registre: int) -> int:
        return self.registres[registre] | self.registres[registre + 1] << 8

    def niveau(self, broche: str) -> bool:
        numero = BROCHES_DES_PUCES["mcp23017"].index(broche)
        if not self._mot(0x00) >> numero & 1:
            return bool(self._mot(0x14) >> numero & 1)
        tire = bool(self._mot(0x0C) >> numero & 1)
        return self.exterieur.get(broche, tire)

    def recevoir(self, donnees: bytes) -> None:
        self._pointeur = donnees[0]
        for octet in donnees[1:]:
            self.registres[self._pointeur] = octet
            self._pointeur = (self._pointeur + 1) % len(self.registres)

    def envoyer(self, nombre: int) -> bytes:
        octets = []
        for _ in range(nombre):
            if self._pointeur in (0x12, 0x13):
                debut = (self._pointeur - 0x12) * 8
                broches = BROCHES_DES_PUCES["mcp23017"][debut : debut + 8]
                octets.append(sum(1 << i for i, b in enumerate(broches) if self.niveau(b)))
            else:
                octets.append(self.registres[self._pointeur])
            self._pointeur = (self._pointeur + 1) % len(self.registres)
        return bytes(octets)


# ------------------------------------------------------------- pesée (HX711)


class FauxHx711:
    """Une carte HX711 au bout de ses 2 broches : une mesure toujours prête, envoyée bit par bit
    à chaque impulsion de SCK (le plus fort d'abord), DT à 1 après la 25ᵉ impulsion.
    Débranchée : DT reste à 1 (tirage haut du Pi), comme une prise de pesée débranchée.

    Elle a sa propre horloge, qui n'avance que quand le lecteur attend (`dormir`) : une prise
    débranchée ne fait pas attendre les tests ni le simulateur, et une impulsion n'est jamais
    jugée trop longue parce que l'ordinateur d'essai est chargé."""

    def __init__(self) -> None:
        self.temps = 0.0
        self.brut = 0
        self.debranche = False
        self.ferme = False
        self.lectures = 0
        self._impulsions = 0
        self._sck = False
        self._apres_lecture = False

    def _bit(self) -> bool:
        if self._impulsions == 0 or self._impulsions > 24:
            return False
        mot = self.brut & 0xFFFFFF
        return bool(mot >> (24 - self._impulsions) & 1)

    def horloge(self) -> float:
        return self.temps

    def horloge_ns(self) -> int:
        return round(self.temps * 1e9)

    def dormir(self, duree_s: float) -> None:
        self.temps += duree_s

    def dt(self) -> bool:
        if self.debranche:
            return True
        if self._apres_lecture:
            # La puce garde DT à 1 jusqu'à la mesure suivante : prête au coup d'après ici,
            # une fois SCK redescendu.
            if not self._sck:
                self._apres_lecture = False
            return True
        return self._bit()

    def sck(self, haut: bool) -> None:
        if haut and not self._sck and not self.debranche:
            self._impulsions += 1
            if self._impulsions == 25:
                self._impulsions = 0
                self._apres_lecture = True
                self.lectures += 1
        self._sck = haut

    def fermer(self) -> None:
        self.ferme = True


# ---------------------------------------------------------------------- RS485


class FauxTransmetteurModbus:
    """Un appareil Modbus RTU : des registres qu'on règle à la main."""

    def __init__(self) -> None:
        self.registres: dict[int, int] = {}
        self.debranche = False

    def repondre(self, demande: bytes) -> bytes:
        adresse, fonction = demande[0], demande[1]
        registre = int.from_bytes(demande[2:4], "big")
        nombre = int.from_bytes(demande[4:6], "big")
        if fonction not in (3, 4):
            reponse = bytes([adresse, fonction | 0x80, 1])
        elif any(r not in self.registres for r in range(registre, registre + nombre)):
            reponse = bytes([adresse, fonction | 0x80, 2])
        else:
            donnees = b"".join(
                (self.registres[r] & 0xFFFF).to_bytes(2, "big")
                for r in range(registre, registre + nombre)
            )
            reponse = bytes([adresse, fonction, len(donnees)]) + donnees
        return reponse + crc_modbus(reponse)


class FausseCartePesee:
    """Une carte de pesée RP2040 + HX711 du bus des pesées (même table que pesee/src/mesures.h).

    Chaque question trouve une mesure nouvelle (numéro + 1), sauf si `figee`."""

    def __init__(self) -> None:
        self.brut = 0
        self.numero = 0
        self.hx711_muet = False
        self.figee = False
        self.exemple = False
        self.par_seconde = 80
        self.trames_abimees = 0
        self.debranche = False
        self.questions = 0

    def repondre(self, demande: bytes) -> bytes:
        adresse, fonction = demande[0], demande[1]
        premier = int.from_bytes(demande[2:4], "big")
        nombre = int.from_bytes(demande[4:6], "big")
        self.questions += 1
        if not self.figee and not self.hx711_muet:
            self.numero = (self.numero + 1) & 0xFFFF
        registres = carte_pesee.encoder(
            carte_pesee.MesureCarte(
                brut=self.brut,
                numero=self.numero,
                age_ms=0 if not self.hx711_muet else 0xFFFF,
                hx711_muet=self.hx711_muet,
                exemple=self.exemple,
                par_seconde=0 if self.hx711_muet else self.par_seconde,
                trames_abimees=self.trames_abimees,
            )
        )
        if fonction not in (3, 4):
            reponse = bytes([adresse, fonction | 0x80, 1])
        elif nombre == 0 or premier + nombre > len(registres):
            reponse = bytes([adresse, fonction | 0x80, 2])
        else:
            donnees = b"".join(r.to_bytes(2, "big") for r in registres[premier : premier + nombre])
            reponse = bytes([adresse, fonction, len(donnees)]) + donnees
        return reponse + crc_modbus(reponse)


class FauxRs485:
    """Un fil RS485 (port série) avec des appareils à leur adresse."""

    def __init__(self) -> None:
        self.appareils: dict[int, FauxTransmetteurModbus | FausseCartePesee] = {}
        self.cable_coupe = False
        self._reponse = b""
        self.ouvertures = 0

    def ouvrir(self) -> "FauxRs485":
        if self.cable_coupe:
            raise OSError("faux RS485 : adaptateur débranché")
        self.ouvertures += 1
        self._reponse = b""
        return self

    def write(self, donnees: bytes) -> int:
        if self.cable_coupe:
            raise OSError("faux RS485 : adaptateur débranché")
        self._reponse = b""
        if len(donnees) == 8 and crc_modbus(donnees[:6]) == donnees[6:]:
            appareil = self.appareils.get(donnees[0])
            if appareil is not None and not appareil.debranche:
                self._reponse = appareil.repondre(donnees)
        return len(donnees)

    def read(self, nombre: int) -> bytes:
        if self.cable_coupe:
            raise OSError("faux RS485 : adaptateur débranché")
        morceau, self._reponse = self._reponse[:nombre], self._reponse[nombre:]
        return morceau

    def reset_input_buffer(self) -> None:
        self._reponse = b""

    def close(self) -> None:
        pass


# ----------------------------------------------------------- la fausse fabrique


class FausseFabrique:
    """Fabrique tout le faux matériel décrit par la liste, et le règle par les noms."""

    def __init__(self, liste: EntreesSorties) -> None:
        self.liste = liste
        self.branchements = tracer_branchements(liste)
        self.gpios: dict[str, FauxGpio] = {}
        self.bus: dict[str, FauxBusI2c] = {}
        self.rs485: dict[str, FauxRs485] = {}
        self.balances: dict[str, FauxHx711] = {}
        classes = {
            "sht31": FauxSht31,
            "ads1115": FauxAds1115,
            "pcf8574": FauxPcf8574,
            "mcp23017": FauxMcp23017,
        }
        for branchement in self.branchements.values():
            ressource = branchement.ressource
            if ressource[0] == "gpio":
                self.gpios.setdefault(ressource[1], FauxGpio())
            elif ressource[0] == "hx711":
                self.balances.setdefault(branchement.nom, FauxHx711())
            elif ressource[0] == "i2c":
                bus = self.bus.setdefault(ressource[1], FauxBusI2c())
                if ressource[2] not in bus.appareils:
                    bus.appareils[ressource[2]] = classes[ressource[3]]()
            else:
                rs485 = self.rs485.setdefault(ressource[1], FauxRs485())
                signal = liste.signaux[branchement.nom]
                assert signal.adresse is not None
                if signal.appareil == CARTE_PESEE:
                    rs485.appareils.setdefault(signal.adresse, FausseCartePesee())
                    continue
                assert signal.modbus is not None
                transmetteur = rs485.appareils.setdefault(signal.adresse, FauxTransmetteurModbus())
                transmetteur.registres.setdefault(signal.modbus.registre, 0)
        # Au départ, aucun capteur n'est actionné.
        for nom, branchement in self.branchements.items():
            if branchement.sorte == "entree":
                self.actionner(nom, False)

    # ------------------------------------------------ ce que demande Materiel

    def gpio(self, fichier: str) -> FauxGpio:
        return self.gpios.setdefault(fichier, FauxGpio())

    def bus_i2c(self, fichier: str) -> BusI2c:
        return self.bus.setdefault(fichier, FauxBusI2c())

    def port_serie(self, liaison: LiaisonUsbSerie) -> FauxRs485:
        for carte, rs485 in self.rs485.items():
            if self.liste.cartes[carte].liaison == liaison:
                return rs485.ouvrir()
        raise OSError(f"faux : aucun adaptateur n° « {liaison.numero_serie_usb} »")

    def hx711(self, fichier: str, dt: str, sck: str) -> Hx711:
        for nom, branchement in self.branchements.items():
            if branchement.ressource == ("hx711", fichier, dt, sck):
                faux = self.balances[nom]
                return Hx711(
                    faux, horloge_ns=faux.horloge_ns, horloge=faux.horloge, dormir=faux.dormir
                )
        raise OSError(f"faux : aucune carte de pesée sur {dt}, {sck}")

    # ------------------------------------------------ réglage par les noms

    def _branchement(self, nom: str, *sortes: str) -> Branchement:
        branchement = self.branchements.get(nom)
        if branchement is None or branchement.sorte not in sortes:
            raise KeyError(f"faux : « {nom} » n'est pas un signal de sorte {' ou '.join(sortes)}")
        return branchement

    def _appareil(self, branchement: Branchement):
        ressource = branchement.ressource
        if ressource[0] == "gpio":
            return self.gpios[ressource[1]]
        if ressource[0] == "hx711":
            return self.balances[branchement.nom]
        if ressource[0] == "i2c":
            return self.bus[ressource[1]].appareils[ressource[2]]
        signal = self.liste.signaux[branchement.nom]
        return self.rs485[ressource[1]].appareils[signal.adresse]

    def actionner(self, nom: str, actionne: bool = True) -> None:
        """Le capteur (entrée tout-ou-rien) est actionné, ou ne l'est plus."""
        branchement = self._branchement(nom, "entree")
        self._appareil(branchement).exterieur[branchement.broche] = branchement.niveau(actionne)

    def commande(self, nom: str) -> bool:
        """La sortie est-elle commandée ? (lue sur la broche, comme avec un voltmètre)"""
        branchement = self._branchement(nom, "sortie")
        return branchement.actif(self._appareil(branchement).niveau(branchement.broche))

    def regler(self, nom: str, valeur: float) -> None:
        """Mesure analogique ou Modbus, dans l'unité du signal."""
        branchement = self._branchement(nom, "mesure", "modbus")
        signal = self.liste.signaux[nom]
        appareil = self._appareil(branchement)
        if branchement.sorte == "modbus":
            assert signal.modbus is not None
            appareil.registres[signal.modbus.registre] = round(valeur / signal.modbus.echelle)
            return
        volts = valeur
        if signal.conversion is not None:
            (v0, v1), (y0, y1) = signal.conversion.volts, signal.conversion.valeurs
            volts = v0 + (valeur - y0) * (v1 - v0) / (y1 - y0)
        appareil.tensions[branchement.broche] = volts

    def regler_ambiance(self, nom: str, temperature_c: float, humidite_pct: float) -> None:
        appareil = self._appareil(self._branchement(nom, "ambiance"))
        appareil.temperature_c = temperature_c
        appareil.humidite_pct = humidite_pct

    def regler_pesee(self, nom: str, brut: int) -> None:
        """Mesure brute de la carte de pesée (nombre signé de 24 bits), HX711 ou carte RS485."""
        self._appareil(self._branchement(nom, "pesee")).brut = brut

    def carte_pesee(self, nom: str) -> FausseCartePesee:
        """La fausse carte de pesée du bus RS485 d'un signal (la figer, couper son HX711...)."""
        appareil = self._appareil(self._branchement(nom, "pesee"))
        if not isinstance(appareil, FausseCartePesee):
            raise KeyError(f"faux : « {nom} » n'est pas une carte de pesée du bus RS485")
        return appareil

    def debrancher(self, nom: str, debranche: bool = True) -> None:
        """La puce I2C, le transmetteur ou la carte de pesée du signal ne répond plus
        (ou de nouveau)."""
        branchement = self._branchement(
            nom, "mesure", "modbus", "ambiance", "entree", "sortie", "pesee"
        )
        if branchement.ressource[0] == "gpio":
            raise KeyError("faux : une broche GPIO du Pi ne se débranche pas")
        self._appareil(branchement).debranche = debranche
