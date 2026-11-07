"""Faux matériel pour les tests et le simulateur : un faux de chaque capteur et de chaque carte.

Les faux imitent les puces au niveau de leurs octets (registres de l'ADS1115, somme de
contrôle du SHT31, trames Modbus...), pour que le vrai code de `puces.py` et `modbus.py`
soit testé lui aussi. Seules les broches GPIO du Pi sont imitées plus haut (`FauxGpio`).

    faux = FausseFabrique(liste)
    materiel = Materiel(liste, faux)
    faux.actionner("reed_panneau_poste_fut", True)   # le capteur est actionné
    faux.regler("vide_venturi", -40)                  # dans l'unité du signal
    faux.regler_ambiance("sht31_armoire", 28.5, 70)
    faux.regler_pesee("pesee_griffe", 1_234_567)     # mesure brute d'une pesée du bus RS485
    faux.regler("ozone_dedans", 0.85)                      # ppm : le faux ZE25-O3 envoie ses trames
    faux.capteur_ozone("ozone_dedans").muet = True         # capteur d'ozone : plus aucune trame
    faux.capteur_ozone("ozone_dedans").injecter(b"\xff\x00")  # octets de travers, à la main
    faux.regler("particules_dedans", 35.0)               # µg/m³ : le faux SPS30 répond en SHDLC
    faux.capteur_particules("particules_dedans").muet = True   # SPS30 : plus aucune réponse
    faux.regler("pression_enceinte", 9.0)                # Pa : le faux SDP810 sur le bus I2C
    faux.consigne("consigne_ventilateur").volts()        # dernière consigne 0-10 V reçue
    faux.commande("voyant_buzzer")                    # ce qu'a fait le programme
    faux.debrancher("sht31_armoire")                  # la puce ne répond plus
    faux.debrancher("pesee_fut")                      # la boîte du poste ne répond plus
    faux.carte_pesee("pesee_griffe").hx711_muet = True  # carte du bus RS485 : HX711 muet
    faux.carte_pesee("pesee_fut").radio_muette = True   # boîte du poste : radio muette
    faux.carte_pesee("pesee_fut").accu_mv = 3400        # boîte du poste : accu faible
    faux.carte_spray("carte_spray").grammes[0] = 120.0  # carte du spray : flacon 1, balances,
    faux.debrancher("carte_spray")                      # bras, pompes ; carte muette

Le faux suit le même plan que le vrai (niveau actif, contact au repos, tirage), à l'envers.
"""

import errno
import time
from collections.abc import Callable, Mapping
from dataclasses import replace

from vidange import trame_sdp810 as sdp
from vidange import trame_sps30 as shdlc
from vidange.entrees_sorties import (
    BOITE_POSTE_FUT,
    BROCHES_DES_PUCES,
    CARTE_SPRAY,
    PESEES_DU_BUS,
    CapteurOzone,
    CapteurParticules,
    EntreesSorties,
    LiaisonUsbSerie,
    SortiePwm,
)
from vidange.materiel import carte_pesee, carte_spray
from vidange.materiel.materiel import Branchement, tracer_branchements
from vidange.materiel.modbus import crc_modbus
from vidange.materiel.puces import Ads1115, BusI2c, ErreurMateriel, Tirage, crc_sht31
from vidange.trame_ze25 import trame_avec_valeur


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


class FauxSdp810(FauxAppareilI2c):
    """Un SDP810-125Pa : répond en mesure continue après la commande de démarrage."""

    # Facteur d'échelle de la fiche technique du SDP810-125Pa (le vrai capteur le donne lui-même).
    ECHELLE = 240
    ECHELLE_TEMPERATURE = 200

    def __init__(self) -> None:
        super().__init__()
        # Pression du côté « P » moins celle du côté « N » (Pa), comme la puce la voit.
        self.pascals = 0.0
        self.temperature_c = 25.0
        self.demarre = False
        self.abime = False
        self.sans_echelle = False

    def recevoir(self, donnees: bytes) -> None:
        if donnees == sdp.COMMANDE_DEMARRER:
            self.demarre = True
        elif donnees == sdp.COMMANDE_ARRETER:
            self.demarre = False

    def envoyer(self, nombre: int) -> bytes:
        if not self.demarre:
            raise _pas_de_reponse()  # le vrai répond NACK hors mesure continue
        brut = max(-32768, min(32767, round(self.pascals * self.ECHELLE)))
        mots = [
            brut.to_bytes(2, "big", signed=True),
            round(self.temperature_c * self.ECHELLE_TEMPERATURE).to_bytes(2, "big", signed=True),
            (0 if self.sans_echelle else self.ECHELLE).to_bytes(2, "big"),
        ]
        octets = b""
        for mot in mots:
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
        # Le boîtier du chariot (I2C), seulement sur la carte du plateau du remplissage : voir
        # brancher_boitier.
        self.boitier: FauxBoitierChariot | None = None

    def brancher_boitier(
        self, plages_deg: list[tuple[float, float]] | None = None
    ) -> "FauxBoitierChariot":
        """Donne à cette carte l'I2C du plateau du remplissage : une voie de servo par plage
        d'angle (min, max en degrés ; 3 voies de 0 à 270° par défaut). Rend le faux boîtier,
        pour le régler (distance du ToF, pannes...)."""
        self.boitier = FauxBoitierChariot(plages_deg or [(0, 270)] * 3)
        return self.boitier

    def repondre(self, demande: bytes) -> bytes:
        adresse, fonction = demande[0], demande[1]
        premier = int.from_bytes(demande[2:4], "big")
        nombre = int.from_bytes(demande[4:6], "big")
        self.questions += 1
        if fonction == 16:
            if self.boitier is None:
                reponse = bytes([adresse, fonction | 0x80, 1])
                return reponse + crc_modbus(reponse)
            valeurs = [int.from_bytes(demande[7 + 2 * i : 9 + 2 * i], "big") for i in range(nombre)]
            code = self.boitier.ecrire(premier, valeurs)
            reponse = demande[:6] if code == 0 else bytes([adresse, fonction | 0x80, code])
            return reponse + crc_modbus(reponse)
        if self._mesure_nouvelle():
            self.numero = (self.numero + 1) & 0xFFFF
        return self._repondre(adresse, fonction, premier, nombre, self._registres())

    def _mesure_nouvelle(self) -> bool:
        return not self.figee and not self.hx711_muet

    def _registres(self) -> list[int]:
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
        if self.boitier is not None:
            registres += carte_pesee.encoder_boitier(self.boitier.etat())
        return registres

    @staticmethod
    def _repondre(
        adresse: int, fonction: int, premier: int, nombre: int, registres: list[int]
    ) -> bytes:
        if fonction not in (3, 4):
            reponse = bytes([adresse, fonction | 0x80, 1])
        elif nombre == 0 or premier + nombre > len(registres):
            reponse = bytes([adresse, fonction | 0x80, 2])
        else:
            donnees = b"".join(r.to_bytes(2, "big") for r in registres[premier : premier + nombre])
            reponse = bytes([adresse, fonction, len(donnees)]) + donnees
        return reponse + crc_modbus(reponse)


class FauxBoitierChariot:
    """L'I2C de la carte du plateau du remplissage : PCA9685 (angles des servos) et VL6180X (même
    table que pesee/src/plateau.h, vidange.materiel.carte_pesee).

    Les angles sont des dixièmes de degré, sortie coupée au départ. Comme la vraie carte, elle
    refuse (exception 3) toute écriture dont un angle sort de la plage de sa voie, et ne change
    rien dans ce cas. À régler dans un test : `distance_mm` (None : pas de bonne mesure),
    `etat_tof`, `silence_pi_ms`, `pca9685_muette`, `tof_muet`; `redemarrer()` fait repartir la
    carte (compteur de démarrages changé, servos sortie coupée)."""

    def __init__(self, plages_deg: list[tuple[float, float]]) -> None:
        self.plages_dix = [(round(a * 10), round(b * 10)) for a, b in plages_deg]
        self.registres_angles = [carte_pesee.ANGLE_COUPE] * len(plages_deg)
        self.distance_mm: int | None = 50
        self.etat_tof = 0
        self.age_tof_ms = 20
        self.demarrages = 1
        self.pca9685_muette = False
        self.tof_muet = False
        self.aucun_ordre = True
        self.silence_pi_ms = 0
        self.echecs_i2c = 0
        self.ordres = 0
        # Plus d'ordre depuis ce temps : la carte garde les angles et le dit.
        self.silence_max_ms = 2000
        # Pour le simulateur (tête du micropore imaginaire) : la distance du ToF d'après les
        # angles des servos ; None : `distance_mm`.
        self.tof_selon_angles: Callable[[tuple[float | None, ...]], int | None] | None = None

    def redemarrer(self) -> None:
        """La carte repart (chien de garde, coupure) : compteur changé, servos sortie coupée."""
        self.demarrages = (self.demarrages + 1) & 0xFFFF
        self.registres_angles = [carte_pesee.ANGLE_COUPE] * len(self.registres_angles)
        self.aucun_ordre = True
        self.silence_pi_ms = 0

    def ecrire(self, premier: int, valeurs: list[int]) -> int:
        """Une écriture de registres : 0 si acceptée, sinon le code d'exception Modbus."""
        fin = carte_pesee.REGISTRE_ANGLES + len(self.registres_angles)
        if premier < carte_pesee.REGISTRE_ANGLES or premier + len(valeurs) > fin:
            return 2
        voie = premier - carte_pesee.REGISTRE_ANGLES
        for decalage, valeur in enumerate(valeurs):
            angle = carte_pesee.angle_du_registre(valeur)
            if angle is None:
                continue
            mini, maxi = self.plages_dix[voie + decalage]
            if not mini <= round(angle * 10) <= maxi:
                return 3
        for decalage, valeur in enumerate(valeurs):
            self.registres_angles[voie + decalage] = valeur
        self.aucun_ordre = False
        self.silence_pi_ms = 0
        self.ordres += 1
        return 0

    def etat(self) -> carte_pesee.BoitierChariot:
        angles = tuple(carte_pesee.angle_du_registre(v) for v in self.registres_angles)
        if self.tof_selon_angles is not None:
            self.distance_mm = self.tof_selon_angles(angles)
        return carte_pesee.BoitierChariot(
            distance_mm=None if self.tof_muet else self.distance_mm,
            etat_tof=carte_pesee.TOF_ETAT_MUET if self.tof_muet else self.etat_tof,
            age_tof_ms=self.age_tof_ms,
            demarrages=self.demarrages,
            pca9685_muette=self.pca9685_muette,
            tof_muet=self.tof_muet,
            aucun_ordre=self.aucun_ordre,
            pi_silencieux=not self.aucun_ordre and self.silence_pi_ms > self.silence_max_ms,
            pca9685_demarre_pas=False,
            echecs_i2c=self.echecs_i2c,
            silence_pi_ms=self.silence_pi_ms,
            angles_deg=angles,
        )

    @property
    def angles_deg(self) -> tuple[float | None, ...]:
        return self.etat().angles_deg


class FausseBoitePosteFut(FausseCartePesee):
    """La boîte du poste du fût (13 registres, signature 0x5046) et le plateau qu'elle entend.

    Chaque question trouve une trame nouvelle (numéro + 1), sauf si `figee` ou `radio_muette`
    (le plateau dort ou est trop loin : âge au plus haut, numéro qui ne bouge plus). `age_ms` :
    l'âge de la dernière trame quand la radio parle. `signature` : pour essayer une carte RP2040
    à l'adresse de la boîte."""

    def __init__(self) -> None:
        super().__init__()
        self.par_seconde = 2
        self.age_ms = 0
        self.radio_muette = False
        self.au_poste = True
        self.recharge_presente = True
        self.sur_usb = False
        self.accu_mv = 3900
        self.accu_pct = 80
        self.signal_dbm = -60
        self.trames_perdues = 0
        self.signature = carte_pesee.SIGNATURE_BOITE

    def _mesure_nouvelle(self) -> bool:
        return super()._mesure_nouvelle() and not self.radio_muette

    def _registres(self) -> list[int]:
        muette = self.radio_muette
        return carte_pesee.encoder(
            carte_pesee.MesureCarte(
                brut=self.brut,
                numero=self.numero,
                age_ms=0xFFFF if muette else self.age_ms,
                hx711_muet=self.hx711_muet,
                exemple=self.exemple,
                par_seconde=0 if muette or self.hx711_muet else self.par_seconde,
                trames_abimees=self.trames_abimees,
                radio_muette=muette,
                plateau=carte_pesee.Plateau(
                    au_poste=self.au_poste,
                    recharge_presente=self.recharge_presente,
                    sur_usb=self.sur_usb,
                    accu_mv=self.accu_mv,
                    accu_pct=self.accu_pct,
                    signal_dbm=self.signal_dbm,
                    trames_perdues=self.trames_perdues,
                ),
            ),
            signature=self.signature,
        )


class FausseCarteSpray:
    """La carte ESP32 n° 5 du spray (table : vidange.materiel.carte_spray, spray/README.md), avec
    4 fausses balances, un faux bras et ses fausses pompes. Le temps est celui de `horloge` :
    chaque question fait avancer la carte jusqu'à maintenant (pas de 0,05 s).

    Ses réglages sont ceux que le programme de la carte reçoit à la fabrication (machine.yaml →
    spray) : `appliquer(reglages.machine.spray)` les recopie. Pannes à la main : `debranche`
    (carte muette), `balance_muette[i]`, `balance_instable[i]`, `debit_g_s = 0` (tube pincé,
    flacon vide), `bras_bloque`, `capteur_en_panne`, `pousser_bras()`, `redemarrer()`."""

    PAS_S = 0.05

    def __init__(self) -> None:
        self.horloge: Callable[[], float] = time.monotonic
        self.debranche = False
        self.exemple = True
        # Réglages du programme de la carte (exemples ; `appliquer` les remplace).
        self.course_deg = 110.0
        self.vitesse_bras_deg_s = 90.0
        self.temps_max_bras_s = 3.0
        self.air_avant_s = 0.5
        self.temps_max_pompage_s = 15.0
        self.chasse_s = 4.5
        self.air_apres_s = 1.0
        self.nettoyage_pompe_s = 5.0
        self.sechage_s = 15.0
        self.silence_max_s = 2.0
        # Ce qui est dans la boîte.
        self.grammes = [400.0] * carte_spray.NB_FLACONS
        self.zero_brut = 0
        self.brut_par_g = 400.0
        self.balance_muette = [False] * carte_spray.NB_FLACONS
        self.balance_instable = [False] * carte_spray.NB_FLACONS
        self.debit_g_s = 1.0
        self.bras_bloque = False
        self.capteur_en_panne = False
        # Ce que la carte a reçu (pour les tests) : (code, paramètre 1, paramètre 2).
        self.ordres: list[tuple[int, int, int]] = []
        self.battements = 0
        self.questions = 0
        self.redemarrer()

    def appliquer(self, reglage) -> None:
        """Les réglages de machine.yaml → spray, comme le programme de la carte à sa
        fabrication (tâche 39 bis)."""
        self.course_deg = reglage.bras.course_deg[1]
        self.vitesse_bras_deg_s = reglage.bras.vitesse_deg_s
        self.temps_max_bras_s = reglage.bras.temps_max_s
        self.air_avant_s = reglage.dose.air_avant_s
        self.temps_max_pompage_s = reglage.dose.temps_max_pompage_s
        self.chasse_s = reglage.dose.chasse_s
        self.air_apres_s = reglage.dose.air_apres_s
        self.nettoyage_pompe_s = reglage.nettoyage.pompe_s
        self.sechage_s = reglage.nettoyage.sechage_s
        self.silence_max_s = reglage.liaison.silence_max_s

    def redemarrer(self) -> None:
        """La carte redémarre : origine perdue, tout arrêté, le bras où il est."""
        self.demarrages = getattr(self, "demarrages", 0) + 1
        self._t = self.horloge()
        self._dernier_message = -1e9
        self._dernier_battement = -1e9
        self.angle = getattr(self, "angle", 0.0)
        self.origine = False
        self.erreurs = 0
        self.silence = False
        self.arret = False
        self._cible: float | None = None
        self._debut_mouvement = 0.0
        self._mouvement = ""  # "origine", "sortir", "ranger"
        self._sorti_a: float | None = None
        self._capteur_vu = self._capteur()
        self.numero_ordre = 0
        self.suite = carte_spray.SUITE_AUCUN
        self.refus = 0
        self._numero_recu: int | None = None
        # Geste en cours : liste de (phase, durée) ; la phase « pompe » dure jusqu'à la dose.
        self._phases: list[tuple[str, float]] = []
        self._debut_phase = 0.0
        self._sorte_geste = ""  # "spray" ou "nettoyage"
        self.dose = carte_spray.Dose(0, 0.0, 0.0, 0.0, carte_spray.DOSE_AUCUNE, 0)
        self._dose_depart_g = 0.0
        self._debut_pompe = 0.0
        self.agitateurs_pct = 0
        self._fin_agitation = 0.0
        self.trames_abimees = 0

    def regler_horloge(self, horloge: Callable[[], float]) -> None:
        """Une autre horloge (tests, simulateur) : la carte repart de son heure."""
        self.horloge = horloge
        self._t = horloge()
        self._dernier_message = self._dernier_battement = self._t - 1e6

    def pousser_bras(self, angle: float = 15.0) -> None:
        """Quelqu'un pousse le bras rangé (sans ordre)."""
        self._avancer()
        self.angle = angle

    # ------------------------------------------------------------ le temps passe

    def _capteur(self) -> bool:
        return self.angle <= 0.5 and not self.capteur_en_panne

    def _occupee(self) -> bool:
        return bool(self._phases) or self._cible is not None

    def _avancer(self) -> None:
        maintenant = self.horloge()
        while self._t < maintenant - 1e-9:
            if not self._occupee() and (self.silence or not self._bras_dehors()):
                self._t = maintenant
                break
            self._t = min(self._t + self.PAS_S, maintenant)
            self._un_pas(self.PAS_S)
        if self.agitateurs_pct and maintenant >= self._fin_agitation:
            self.agitateurs_pct = 0
        vu = self._capteur()
        if self._capteur_vu and not vu and self._cible is None:
            self.erreurs |= carte_spray.ERREUR_BRAS_POUSSE
        self._capteur_vu = vu

    def _bras_dehors(self) -> bool:
        return not self._capteur()

    def _un_pas(self, dt: float) -> None:
        t = self._t
        if (self._phases or self._bras_dehors()) and not self.silence:
            if t - self._dernier_message > self.silence_max_s:
                # Le Pi s'est tu : pompe et air arrêtés, bras rangé.
                self.silence = True
                self._finir_geste(carte_spray.DOSE_INTERROMPUE)
                self._bouger("ranger", 0.0)
        if self._cible is not None:
            self._un_pas_du_bras(t, dt)
        if self._phases:
            self._un_pas_du_geste(t, dt)

    def _un_pas_du_bras(self, t: float, dt: float) -> None:
        assert self._cible is not None
        if not self.bras_bloque:
            ecart = self._cible - self.angle
            pas = self.vitesse_bras_deg_s * dt
            self.angle = (
                self._cible if abs(ecart) <= pas else self.angle + pas * (1 if ecart > 0 else -1)
            )
        if self._mouvement in ("origine", "ranger"):
            if self._capteur():
                self.angle = 0.0
                if self._mouvement == "origine":
                    self.origine = True
                self._fin_mouvement(carte_spray.SUITE_FAIT)
                self.erreurs &= ~(
                    carte_spray.ERREUR_BRAS_PAS_RANGE | carte_spray.ERREUR_BRAS_POUSSE
                )
                return
            if self.angle <= 0.0 and self._mouvement == "origine":
                # Pas encore vu : l'origine continue sous 0 (le bras peut être au-delà).
                self._cible = -self.course_deg
        elif abs(self.angle - self._cible) < 1e-6:
            self._sorti_a = self._cible
            self._fin_mouvement(carte_spray.SUITE_FAIT)
            return
        if t - self._debut_mouvement > self.temps_max_bras_s:
            bit = (
                carte_spray.ERREUR_BRAS_PAS_SORTI
                if self._mouvement == "sortir"
                else carte_spray.ERREUR_BRAS_PAS_RANGE
            )
            self.erreurs |= bit
            self._fin_mouvement(carte_spray.SUITE_ECHOUE)

    def _fin_mouvement(self, suite: int) -> None:
        self._cible = None
        self._mouvement = ""
        if self._phases:
            return
        self.suite = suite

    def _un_pas_du_geste(self, t: float, dt: float) -> None:
        phase, duree = self._phases[0]
        if phase == "pompe":
            n = self.dose.emplacement - 1
            self.grammes[n] -= self.debit_g_s * dt
            perdu = self._dose_depart_g - self.grammes[n]
            if self.balance_muette[n]:
                # Balance perdue pendant la dose : la carte arrête la pompe (comme le temps max).
                self._resultat_pompe(carte_spray.DOSE_TEMPS_MAX)
            elif perdu >= self.dose.demandee_g:
                self._resultat_pompe(carte_spray.DOSE_ATTEINTE)
            elif t - self._debut_pompe >= self.temps_max_pompage_s:
                self._resultat_pompe(carte_spray.DOSE_TEMPS_MAX)
            return
        if t - self._debut_phase >= duree - 1e-9:
            self._phases.pop(0)
            self._debut_phase = t
            if phase == "air" and self._phases and self._phases[0][0] == "pompe":
                self._debut_pompe = t
            if not self._phases:
                self._finir_geste(None)

    def _resultat_pompe(self, resultat: int) -> None:
        n = self.dose.emplacement - 1
        self.dose = replace(
            self.dose,
            perdue_g=self._dose_depart_g - self.grammes[n],
            duree_s=self._t - self._debut_pompe,
            resultat=resultat,
        )
        self._phases.pop(0)
        self._debut_phase = self._t

    def _finir_geste(self, resultat: int | None) -> None:
        """Fin d'un spray ou d'un nettoyage (resultat None), ou interruption (resultat : celui de
        la dose si elle était en cours)."""
        if self._sorte_geste == "":
            return
        if self._sorte_geste == "spray":
            if resultat is not None and self.dose.resultat == carte_spray.DOSE_EN_COURS:
                n = self.dose.emplacement - 1
                self.dose = replace(
                    self.dose,
                    perdue_g=self._dose_depart_g - self.grammes[n],
                    duree_s=self._t - self._debut_pompe if self._debut_pompe else 0.0,
                    resultat=resultat,
                )
            self.dose = replace(self.dose, numero=(self.dose.numero + 1) & 0xFFFF)
            if self.dose.resultat == carte_spray.DOSE_TEMPS_MAX and resultat is None:
                # Dose pas atteinte : chasse faite, la carte range le bras elle-même.
                self._bouger("ranger", 0.0)
        self._phases = []
        self._sorte_geste = ""
        self.suite = carte_spray.SUITE_FAIT if resultat is None else carte_spray.SUITE_ECHOUE

    def _bouger(self, mouvement: str, cible: float) -> None:
        self._mouvement = mouvement
        self._cible = cible
        self._sorti_a = None
        self._debut_mouvement = self._t

    # ------------------------------------------------------------ les ordres

    def _executer(self, code: int, p1: int, p2: int) -> None:
        self.ordres.append((code, p1, p2))
        self.suite, self.refus = carte_spray.SUITE_EN_COURS, 0
        self.arret = False
        erreurs_bras = (
            carte_spray.ERREUR_BRAS_PAS_RANGE
            | carte_spray.ERREUR_BRAS_POUSSE
            | carte_spray.ERREUR_PILOTE_BRAS
        )
        refus = 0
        if code == carte_spray.ORDRE_ORIGINE:
            if self._phases:
                refus = 5
            else:
                self.silence = False
                self._bouger("origine", 0.0)
        elif code == carte_spray.ORDRE_SORTIR:
            if not self.origine:
                refus = 3
            elif not 0 < p1 <= self.course_deg * 10:
                refus = 2
            elif self._t - self._dernier_battement > self.silence_max_s:
                refus = 4
            elif self._occupee():
                refus = 5
            elif self.erreurs & erreurs_bras:
                refus = 8
            else:
                self.silence = False
                self._bouger("sortir", p1 / 10)
        elif code == carte_spray.ORDRE_RANGER:
            if self._phases:
                self._finir_geste(carte_spray.DOSE_INTERROMPUE)
            self._bouger("ranger", 0.0)
        elif code in (carte_spray.ORDRE_SPRAY, carte_spray.ORDRE_NETTOYER):
            n = p1 - 1
            if code == carte_spray.ORDRE_SPRAY and (not 0 <= n < carte_spray.NB_FLACONS or p2 == 0):
                refus = 2
            elif self._occupee():
                refus = 5
            elif self._sorti_a is None:
                refus = 7
            elif code == carte_spray.ORDRE_SPRAY and (
                self.balance_muette[n] or self.balance_instable[n]
            ):
                refus = 6
            elif code == carte_spray.ORDRE_SPRAY:
                self._sorte_geste = "spray"
                self._dose_depart_g = self.grammes[n]
                self._debut_pompe = 0.0
                self.dose = carte_spray.Dose(
                    p1, p2 / 10, 0.0, 0.0, carte_spray.DOSE_EN_COURS, self.dose.numero
                )
                self._phases = [
                    ("air", self.air_avant_s),
                    ("pompe", 0.0),
                    ("chasse", self.chasse_s),
                    ("air_apres", self.air_apres_s),
                ]
                self._debut_phase = self._t
            else:
                self._sorte_geste = "nettoyage"
                self._phases = [
                    ("pompe_nettoyage", self.nettoyage_pompe_s),
                    ("chasse", self.sechage_s),
                    ("air_apres", self.air_apres_s),
                ]
                self._debut_phase = self._t
        elif code == carte_spray.ORDRE_AGITER:
            if p1 > 100:
                refus = 2
            else:
                self.agitateurs_pct = p1 if p2 else 0
                self._fin_agitation = self._t + p2
            self.suite = carte_spray.SUITE_FAIT
        elif code == carte_spray.ORDRE_ARRET:
            if self._phases:
                self._finir_geste(carte_spray.DOSE_INTERROMPUE)
            self._cible, self._mouvement = None, ""
            self.agitateurs_pct = 0
            self.arret = True
            self.suite = carte_spray.SUITE_FAIT
        elif code == carte_spray.ORDRE_EFFACER:
            self.erreurs &= ~0xFF00
            self.silence = False
            self.suite = carte_spray.SUITE_FAIT
        else:
            refus = 1
        if refus:
            self.suite, self.refus = carte_spray.SUITE_REFUSE, refus

    # ------------------------------------------------------------ le bus

    def _registres(self) -> list[int]:
        etat = (
            (carte_spray.ETAT_BRAS_RANGE if self._capteur() else 0)
            | (
                carte_spray.ETAT_BRAS_SORTI
                if self._sorti_a is not None and self._cible is None
                else 0
            )
            | (carte_spray.ETAT_BRAS_BOUGE if self._cible is not None else 0)
            | (carte_spray.ETAT_ORIGINE_FAITE if self.origine else 0)
            | (carte_spray.ETAT_SPRAY_EN_COURS if self._sorte_geste == "spray" else 0)
            | (carte_spray.ETAT_NETTOYAGE_EN_COURS if self._sorte_geste == "nettoyage" else 0)
            | (carte_spray.ETAT_AGITATEURS if self.agitateurs_pct else 0)
            | (carte_spray.ETAT_EXEMPLE if self.exemple else 0)
            | (carte_spray.ETAT_SILENCE_PI if self.silence else 0)
            | (carte_spray.ETAT_ARRET_IMMEDIAT if self.arret else 0)
        )
        erreurs = self.erreurs & 0xFF00
        for i in range(carte_spray.NB_FLACONS):
            if self.balance_muette[i]:
                erreurs |= carte_spray.ERREUR_BALANCE_MUETTE[i]
            if self.balance_instable[i]:
                erreurs |= carte_spray.ERREUR_BALANCE_INSTABLE[i]
        flacons = tuple(
            carte_spray.Flacon(
                brut=round(self.zero_brut + g * self.brut_par_g),
                grammes=0.0 if muette else g,
                muette=muette,
                instable=instable,
            )
            for g, muette, instable in zip(
                self.grammes, self.balance_muette, self.balance_instable, strict=True
            )
        )
        silence_ms = (self._t - self._dernier_message) * 1000
        return carte_spray.encoder(
            carte_spray.EtatSpray(
                version=carte_spray.VERSION,
                demarrages=self.demarrages,
                etat=etat,
                erreurs=erreurs,
                angle_deg=max(self.angle, 0.0),
                numero_ordre=self.numero_ordre,
                suite_ordre=self.suite,
                refus=self.refus,
                silence_pi_ms=int(max(0.0, min(silence_ms, 0xFFFF))),
                flacons=flacons,
                dose=self.dose,
                agitateurs_pct=self.agitateurs_pct,
                trames_abimees=self.trames_abimees,
            )
        )

    def repondre(self, demande: bytes) -> bytes:
        self.questions += 1
        self._avancer()
        adresse, fonction = demande[0], demande[1]
        premier = int.from_bytes(demande[2:4], "big")
        nombre = int.from_bytes(demande[4:6], "big")
        if fonction in (3, 4):
            return FausseCartePesee._repondre(adresse, fonction, premier, nombre, self._registres())
        if fonction != 16:
            reponse = bytes([adresse, fonction | 0x80, 1])
            return reponse + crc_modbus(reponse)
        valeurs = [int.from_bytes(demande[7 + 2 * i : 9 + 2 * i], "big") for i in range(nombre)]
        if premier < carte_spray.REGISTRE_BATTEMENT or premier + nombre > 105:
            reponse = bytes([adresse, fonction | 0x80, 2])
            return reponse + crc_modbus(reponse)
        self._dernier_message = self._t
        registres = dict(zip(range(premier, premier + nombre), valeurs, strict=True))
        if carte_spray.REGISTRE_BATTEMENT in registres:
            self._dernier_battement = self._t
            self.battements += 1
        if 104 in registres and registres[104] != self._numero_recu:
            self._numero_recu = self.numero_ordre = registres[104]
            self._executer(registres.get(101, 0), registres.get(102, 0), registres.get(103, 0))
        reponse = demande[:6]
        return reponse + crc_modbus(reponse)


class FauxCapteurOzone:
    """Un capteur d'ozone ZE25-O3 sur sa liaison série, vu comme un port (il fait aussi le port).

    En envoi automatique, une trame nouvelle arrive à chaque lecture (sauf `emission_automatique`
    éteinte ou `muet`) ; en question-réponse, il répond à la bonne question."""

    def __init__(self, reglage: CapteurOzone) -> None:
        self.reglage = reglage
        self.brut = 0
        self.muet = False
        self.emission_automatique = True
        self.cable_coupe = False
        self.ouvertures = 0
        self._tampon = bytearray()

    @property
    def debranche(self) -> bool:
        return self.muet

    @debranche.setter
    def debranche(self, valeur: bool) -> None:
        self.muet = valeur

    def trame(self) -> bytes:
        return trame_avec_valeur(self.brut, self.reglage.position_valeur)

    def injecter(self, octets: bytes) -> None:
        """Des octets arrivent au Pi, tels quels (trame abîmée, coupée...)."""
        self._tampon += octets

    def ouvrir(self) -> "FauxCapteurOzone":
        if self.cable_coupe:
            raise OSError("faux ozone : adaptateur débranché")
        self.ouvertures += 1
        self._tampon.clear()
        return self

    @property
    def in_waiting(self) -> int:
        if self.cable_coupe:
            raise OSError("faux ozone : adaptateur débranché")
        if self.reglage.mode == "envoi_automatique" and self.emission_automatique and not self.muet:
            self._tampon += self.trame()
        return len(self._tampon)

    def write(self, donnees: bytes) -> int:
        if self.cable_coupe:
            raise OSError("faux ozone : adaptateur débranché")
        if self.reglage.mode == "question_reponse" and not self.muet:
            if donnees == self.reglage.question:
                self._tampon += self.trame()
        return len(donnees)

    def read(self, nombre: int) -> bytes:
        if self.cable_coupe:
            raise OSError("faux ozone : adaptateur débranché")
        morceau = bytes(self._tampon[:nombre])
        del self._tampon[:nombre]
        return morceau

    def reset_input_buffer(self) -> None:
        self._tampon.clear()

    def close(self) -> None:
        pass


class FauxSps30:
    """Un capteur de particules SPS30 sur sa liaison série, vu comme un port (il fait aussi le
    port). Il parle SHDLC : il répond à « start measurement » et à « read measured values »."""

    def __init__(self, reglage: CapteurParticules) -> None:
        self.reglage = reglage
        # Concentration en masse (µg/m³) de la grandeur lue ; les autres sont différentes.
        self.valeur = 0.0
        self.muet = False
        self.cable_coupe = False
        self.demarre = False
        # Pas de mesure nouvelle : il répond « 0 octet de données ».
        self.sans_mesure_nouvelle = False
        # Un adaptateur RS485 qui renvoie ce que le Pi écrit.
        self.echo = False
        self.etat_force = 0
        # Chaque réponse arrive avec un octet changé (somme de contrôle fausse).
        self.abimer = False
        self.couper = False
        self.ouvertures = 0
        self._tampon = bytearray()

    @property
    def debranche(self) -> bool:
        return self.muet

    @debranche.setter
    def debranche(self, valeur: bool) -> None:
        self.muet = valeur

    def injecter(self, octets: bytes) -> None:
        """Des octets arrivent au Pi, tels quels (trame abîmée, coupée...)."""
        self._tampon += octets

    def ouvrir(self) -> "FauxSps30":
        if self.cable_coupe:
            raise OSError("faux SPS30 : adaptateur débranché")
        self.ouvertures += 1
        self._tampon.clear()
        return self

    def _valeurs(self) -> tuple[float, ...]:
        rang = shdlc.RANG_GRANDEUR[self.reglage.grandeur]
        return tuple(
            self.valeur if i == rang else self.valeur + 1000.0 + i
            for i in range(shdlc.NOMBRE_VALEURS)
        )

    def write(self, donnees: bytes) -> int:
        if self.cable_coupe:
            raise OSError("faux SPS30 : adaptateur débranché")
        if self.echo:
            self._tampon += donnees
        if self.muet:
            return len(donnees)
        try:
            question = shdlc.decoder_reponse(self._question_en_reponse(donnees))
        except shdlc.ErreurTrame:
            return len(donnees)
        reponse = self._repondre(question.commande, question.donnees)
        if self.abimer:
            abimee = bytearray(reponse)
            abimee[len(abimee) // 2] ^= 0xFF
            reponse = bytes(abimee)
        if self.couper:
            reponse = reponse[: len(reponse) // 2]
        self._tampon += reponse
        return len(donnees)

    def _repondre(self, commande: int, contenu: bytes) -> bytes:
        if commande == shdlc.COMMANDE_DEMARRER:
            if contenu != shdlc.DONNEES_DEMARRER:
                return shdlc.construire_reponse(commande, etat=0x04)
            if self.demarre:
                return shdlc.construire_reponse(commande, etat=0x43)
            self.demarre = True
            return shdlc.construire_reponse(commande)
        if commande == shdlc.COMMANDE_LIRE:
            if not self.demarre:
                return shdlc.construire_reponse(commande, etat=0x43)
            if self.sans_mesure_nouvelle:
                return shdlc.construire_reponse(commande, etat=self.etat_force)
            mesure = shdlc.donnees_de_mesure(self._valeurs())
            return shdlc.construire_reponse(commande, mesure, self.etat_force)
        return shdlc.construire_reponse(commande, etat=0x02)

    @staticmethod
    def _question_en_reponse(question: bytes) -> bytes:
        """Une question (adresse, commande, longueur, données) relue comme une réponse
        (adresse, commande, état = 0, longueur, données) pour la décoder avec le même code."""
        contenu = shdlc.retirer_echappements(question[1:-1])
        adresse, commande, longueur = contenu[0], contenu[1], contenu[2]
        donnees = contenu[3 : 3 + longueur]
        if adresse != shdlc.ADRESSE:
            raise shdlc.ErreurTrame("pas pour lui")
        if shdlc.somme_de_controle(contenu[:-1]) != contenu[-1]:
            raise shdlc.ErreurTrame("somme fausse")
        return shdlc.construire_reponse(commande, donnees)

    @property
    def in_waiting(self) -> int:
        if self.cable_coupe:
            raise OSError("faux SPS30 : adaptateur débranché")
        return len(self._tampon)

    def read(self, nombre: int) -> bytes:
        if self.cable_coupe:
            raise OSError("faux SPS30 : adaptateur débranché")
        morceau = bytes(self._tampon[:nombre])
        del self._tampon[:nombre]
        return morceau

    def reset_input_buffer(self) -> None:
        self._tampon.clear()

    def close(self) -> None:
        pass


class FausseSortiePwm:
    """Une sortie PWM imaginaire : garde les rapports cycliques reçus."""

    def __init__(self, reglage: SortiePwm) -> None:
        self.reglage = reglage
        self.rapports: list[float] = []
        self.en_panne = False
        self.ferme = False

    @property
    def debranche(self) -> bool:
        return self.en_panne

    @debranche.setter
    def debranche(self, valeur: bool) -> None:
        self.en_panne = valeur

    def regler(self, rapport: float) -> None:
        if self.en_panne:
            raise ErreurMateriel("faux PWM en panne")
        self.rapports.append(rapport)

    def volts(self) -> float | None:
        """La tension que le module donnerait en ce moment (None : jamais réglée)."""
        if not self.rapports:
            return None
        return self.rapports[-1] * self.reglage.pleine_echelle_v

    def fermer(self) -> None:
        self.ferme = True


class FauxRs485:
    """Un fil RS485 (port série) avec des appareils à leur adresse."""

    def __init__(self) -> None:
        self.appareils: dict[int, FauxTransmetteurModbus | FausseCartePesee | FausseCarteSpray] = {}
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
        lecture = len(donnees) == 8
        ecriture = len(donnees) > 9 and donnees[1] == 16 and len(donnees) == 9 + donnees[6]
        if (lecture or ecriture) and crc_modbus(donnees[:-2]) == donnees[-2:]:
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
        self.ozones: dict[str, FauxCapteurOzone] = {}
        # SPS30 : par carte (USB-RS485) ou par fichier (UART du Pi).
        self.particules: dict[str, FauxSps30] = {}
        self.pwms: dict[tuple[str, int], FausseSortiePwm] = {}
        classes = {
            "sdp810": FauxSdp810,
            "sht31": FauxSht31,
            "ads1115": FauxAds1115,
            "pcf8574": FauxPcf8574,
            "mcp23017": FauxMcp23017,
        }
        for branchement in self.branchements.values():
            ressource = branchement.ressource
            if ressource[0] == "gpio":
                self.gpios.setdefault(ressource[1], FauxGpio())
            elif ressource[0] == "i2c":
                bus = self.bus.setdefault(ressource[1], FauxBusI2c())
                if ressource[2] not in bus.appareils:
                    bus.appareils[ressource[2]] = classes[ressource[3]]()
            elif branchement.sorte == "ozone":
                reglage = liste.signaux[branchement.nom].ozone
                assert reglage is not None
                self.ozones.setdefault(ressource[1], FauxCapteurOzone(reglage))
            elif branchement.sorte == "particules":
                reglage_p = liste.signaux[branchement.nom].particules
                assert reglage_p is not None
                self.particules.setdefault(ressource[1], FauxSps30(reglage_p))
            elif branchement.sorte == "consigne":
                reglage_pwm = liste.signaux[branchement.nom].pwm
                assert reglage_pwm is not None
                self.pwms.setdefault(
                    (reglage_pwm.fichier, reglage_pwm.canal), FausseSortiePwm(reglage_pwm)
                )
            else:
                rs485 = self.rs485.setdefault(ressource[1], FauxRs485())
                signal = liste.signaux[branchement.nom]
                assert signal.adresse is not None
                if signal.appareil in PESEES_DU_BUS:
                    classe = (
                        FausseBoitePosteFut
                        if signal.appareil == BOITE_POSTE_FUT
                        else FausseCartePesee
                    )
                    rs485.appareils.setdefault(signal.adresse, classe())
                    continue
                if signal.appareil == CARTE_SPRAY:
                    rs485.appareils.setdefault(signal.adresse, FausseCarteSpray())
                    continue
        # Au départ, aucun capteur n'est actionné.
        for nom, branchement in self.branchements.items():
            if branchement.sorte == "entree":
                self.actionner(nom, False)

    # ------------------------------------------------ ce que demande Materiel

    def gpio(self, fichier: str) -> FauxGpio:
        return self.gpios.setdefault(fichier, FauxGpio())

    def bus_i2c(self, fichier: str) -> BusI2c:
        return self.bus.setdefault(fichier, FauxBusI2c())

    def port_uart(self, fichier: str, vitesse_bauds: int, delai_reponse_s: float) -> FauxSps30:
        if fichier not in self.particules:
            raise OSError(f"faux : aucun UART « {fichier} »")
        return self.particules[fichier].ouvrir()

    def sortie_pwm(self, reglage: SortiePwm) -> FausseSortiePwm:
        return self.pwms.setdefault((reglage.fichier, reglage.canal), FausseSortiePwm(reglage))

    def port_serie(self, liaison: LiaisonUsbSerie) -> FauxRs485 | FauxCapteurOzone | FauxSps30:
        for carte, ozone in self.ozones.items():
            if self.liste.cartes[carte].liaison == liaison:
                return ozone.ouvrir()
        for carte, capteur in self.particules.items():
            if carte in self.liste.cartes and self.liste.cartes[carte].liaison == liaison:
                return capteur.ouvrir()
        for carte, rs485 in self.rs485.items():
            if self.liste.cartes[carte].liaison == liaison:
                return rs485.ouvrir()
        raise OSError(f"faux : aucun adaptateur n° « {liaison.numero_serie_usb} »")

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
        if ressource[0] == "i2c":
            return self.bus[ressource[1]].appareils[ressource[2]]
        if branchement.sorte == "ozone":
            return self.ozones[ressource[1]]
        if branchement.sorte == "particules":
            return self.particules[ressource[1]]
        if branchement.sorte == "consigne":
            return self.pwms[(ressource[1], ressource[2])]
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
        """Mesure analogique, ozone en ppm, particules en µg/m³ ou pression en Pa (positive :
        l'enceinte plus haute que le conteneur), dans l'unité du signal."""
        branchement = self._branchement(nom, "mesure", "ozone", "particules", "pression")
        signal = self.liste.signaux[nom]
        appareil = self._appareil(branchement)
        if branchement.sorte == "ozone":
            assert signal.ozone is not None
            appareil.brut = round(valeur / signal.ozone.pas_ppm)
            return
        if branchement.sorte == "particules":
            appareil.valeur = valeur
            return
        if branchement.sorte == "pression":
            assert signal.pression is not None
            appareil.pascals = -valeur if signal.pression.inverser else valeur
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
        """Mesure brute d'une pesée du bus RS485 (nombre signé de 24 bits)."""
        self._appareil(self._branchement(nom, "pesee")).brut = brut

    def capteur_ozone(self, nom: str) -> FauxCapteurOzone:
        """Le faux capteur d'ozone d'un signal (le rendre muet, lui injecter des octets...)."""
        return self._appareil(self._branchement(nom, "ozone"))

    def capteur_particules(self, nom: str) -> FauxSps30:
        """Le faux SPS30 d'un signal (le rendre muet, lui injecter des octets...)."""
        return self._appareil(self._branchement(nom, "particules"))

    def capteur_pression(self, nom: str) -> FauxSdp810:
        """Le faux SDP810 d'un signal (abîmer sa somme de contrôle...)."""
        return self._appareil(self._branchement(nom, "pression"))

    def consigne(self, nom: str) -> FausseSortiePwm:
        """La fausse sortie PWM d'un signal (ses rapports reçus, `volts()`)."""
        return self._appareil(self._branchement(nom, "consigne"))

    def carte_pesee(self, nom: str) -> FausseCartePesee:
        """La fausse carte de pesée du bus RS485 d'un signal (la figer, couper son HX711...),
        ou la fausse boîte du poste du fût (FausseBoitePosteFut : radio, accu...)."""
        appareil = self._appareil(self._branchement(nom, "pesee"))
        if not isinstance(appareil, FausseCartePesee):
            raise KeyError(f"faux : « {nom} » n'est pas une carte de pesée du bus RS485")
        return appareil

    def carte_spray(self, nom: str = "carte_spray") -> FausseCarteSpray:
        """La fausse carte du spray d'un signal (balances, bras, pompes, carte muette)."""
        appareil = self._appareil(self._branchement(nom, "spray"))
        assert isinstance(appareil, FausseCarteSpray)
        return appareil

    def debrancher(self, nom: str, debranche: bool = True) -> None:
        """La puce I2C, le capteur d'ozone ou la carte de pesée du signal ne répond plus
        (ou de nouveau)."""
        branchement = self._branchement(
            nom,
            "mesure",
            "ozone",
            "ambiance",
            "entree",
            "sortie",
            "pesee",
            "particules",
            "pression",
            "consigne",
            "spray",
        )
        if branchement.ressource[0] == "gpio":
            raise KeyError("faux : une broche GPIO du Pi ne se débranche pas")
        self._appareil(branchement).debranche = debranche
