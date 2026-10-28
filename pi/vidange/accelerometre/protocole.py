"""Protocole du fil série unique entre le Pi et le RP2040 de l'accéléromètre.

Le même que `accelerometre/src/liaison.h` (voir ce fichier pour la liste des questions).
Une trame = une ligne de texte, « * », le contrôle CRC-16 du texte (4 chiffres
hexadécimaux), « \\n » : « ETAT*F09B\\n ». Le Pi pose une question, le RP2040 répond.
"""

from dataclasses import dataclass

from vidange.reglages import LIGNE_MAX_LIAISON, ReglagesAccelerometre

CODAGE = "utf-8"
FIN = b"\n"
# Plus longue trame du chargeur (accelerometre/src/liaison_trame.h, LIAISON_TRAME_MAX) : une page
# de 256 octets du programme, en hexadécimal.
LIGNE_MAX_CHARGEUR = 560

# Les réglages que le Pi peut envoyer, dans l'ordre de la réponse REGLAGES.
NOMS_REGLAGES = (
    "pleine_echelle_g",
    "mesures_par_seconde",
    "axes",
    "seuil_mg",
    "duree_min_ms",
    "maintien_ms",
    "constante_fond_ms",
    "sans_mesure_ms",
    "erreurs_lecture_max",
    "figee_ms",
    "reessai_ms",
)

# Nombre de chocs que le RP2040 garde (accelerometre/src/detecteur.h).
HISTORIQUE_CHOCS = 16

# Les pannes du RP2040, en bits (accelerometre/src/detecteur.h), la plus importante d'abord.
PANNES = (
    (0x01, "réglages faux"),
    (0x02, "capteur absent"),
    (0x04, "autotest raté"),
    (0x08, "lectures I2C ratées"),
    (0x10, "plus de mesure"),
    (0x20, "mesure figée"),
)


class ErreurProtocole(Exception):
    """Une réponse mal formée."""


def crc(texte: bytes) -> int:
    """CRC-16 CCITT (polynôme 0x1021, départ 0xFFFF)."""
    valeur = 0xFFFF
    for octet in texte:
        valeur ^= octet << 8
        for _ in range(8):
            valeur = ((valeur << 1) ^ 0x1021) if valeur & 0x8000 else valeur << 1
            valeur &= 0xFFFF
    return valeur


def trame(texte: str, taille_max: int = LIGNE_MAX_LIAISON) -> bytes:
    """La trame d'un texte, prête à partir sur le fil."""
    octets = texte.encode(CODAGE)
    resultat = octets + f"*{crc(octets):04X}".encode() + FIN
    if len(resultat) > taille_max:
        raise ErreurProtocole(f"trame trop longue ({len(resultat)} octets)")
    return resultat


def verifier_ligne(ligne: bytes) -> str | None:
    """Le texte d'une ligne reçue (sans « \\n »), ou None si son contrôle est faux."""
    ligne = ligne.rstrip(b"\r")
    if len(ligne) < 5 or ligne[-5:-4] != b"*":
        return None
    try:
        lu = int(ligne[-4:].decode("ascii"), 16)
    except (UnicodeDecodeError, ValueError):
        return None
    texte = ligne[:-5]
    if crc(texte) != lu:
        return None
    try:
        return texte.decode(CODAGE)
    except UnicodeDecodeError:
        return None


class Decodeur:
    """Assemble les octets reçus en lignes au contrôle bon."""

    def __init__(self, taille_max: int = LIGNE_MAX_CHARGEUR) -> None:
        self._reste = b""
        self._taille_max = taille_max
        self.refusees = 0

    def ajouter(self, octets: bytes) -> list[str]:
        self._reste += octets
        *lignes, self._reste = self._reste.split(FIN)
        if len(self._reste) > self._taille_max:
            self._reste = b""
            self.refusees += 1
        textes = []
        for ligne in lignes:
            if not ligne.strip(b"\r"):
                continue
            texte = verifier_ligne(ligne)
            if texte is None:
                self.refusees += 1
            else:
                textes.append(texte)
        return textes


def lire_champs(texte: str) -> tuple[str, dict[str, str]]:
    """« ETAT ok=1 chocs=3 » → ("ETAT", {"ok": "1", "chocs": "3"})."""
    mot, _, suite = texte.partition(" ")
    champs = {}
    for morceau in suite.split():
        nom, egal, valeur = morceau.partition("=")
        if not egal:
            raise ErreurProtocole(f"champ mal formé « {morceau} » dans « {texte} »")
        champs[nom] = valeur
    return mot, champs


def _entier(champs: dict[str, str], nom: str, texte: str) -> int:
    try:
        return int(champs[nom])
    except (KeyError, ValueError):
        raise ErreurProtocole(f"« {nom} » manque ou est mal écrit dans « {texte} »") from None


@dataclass(frozen=True)
class EtatRp2040:
    """Réponse à ETAT."""

    t_ms: int  # temps depuis le démarrage du RP2040
    ok: bool
    en_choc: bool
    pannes: int
    pannes_vues: int
    max_mg: int  # le plus fort depuis la question ETAT d'avant
    chocs: int
    mesures_perdues: int
    redemarre_par_chien: bool
    sortie_contredit: bool

    @classmethod
    def lire(cls, texte: str) -> "EtatRp2040":
        mot, champs = lire_champs(texte)
        if mot != "ETAT":
            raise ErreurProtocole(f"réponse inattendue « {texte} »")

        def entier(nom: str) -> int:
            return _entier(champs, nom, texte)

        return cls(
            t_ms=entier("t_ms"),
            ok=entier("ok") == 1,
            en_choc=entier("choc") == 1,
            pannes=entier("pannes"),
            pannes_vues=entier("vues"),
            max_mg=entier("max_mg"),
            chocs=entier("chocs"),
            mesures_perdues=entier("perdues"),
            redemarre_par_chien=entier("chien") == 1,
            sortie_contredit=entier("contredit") == 1,
        )


@dataclass(frozen=True)
class Choc:
    """Réponse à CHOC n (un choc absent : trop vieux, ou pas encore arrivé)."""

    numero: int
    absent: bool
    t_ms: int = 0
    duree_ms: int = 0
    pic_mg: int = 0
    fini: bool = False

    @classmethod
    def lire(cls, texte: str) -> "Choc":
        mot, champs = lire_champs(texte)
        if mot != "CHOC":
            raise ErreurProtocole(f"réponse inattendue « {texte} »")
        numero = _entier(champs, "n", texte)
        if champs.get("absent") == "1":
            return cls(numero, absent=True)
        return cls(
            numero,
            absent=False,
            t_ms=_entier(champs, "t_ms", texte),
            duree_ms=_entier(champs, "duree_ms", texte),
            pic_mg=_entier(champs, "pic_mg", texte),
            fini=_entier(champs, "fini", texte) == 1,
        )


def texte_pannes(pannes: int) -> str:
    """Les pannes en clair, la plus importante d'abord."""
    noms = [nom for bit, nom in PANNES if pannes & bit]
    return ", ".join(noms) if noms else "aucune"


def reglages_pour_rp2040(reglages: ReglagesAccelerometre) -> dict[str, str]:
    """Les réglages de accelerometre.yaml, comme le RP2040 les écrit (réponse REGLAGES)."""
    capteur, choc, panne = reglages.capteur, reglages.choc, reglages.panne
    return {
        "pleine_echelle_g": str(capteur.pleine_echelle_g),
        "mesures_par_seconde": str(capteur.mesures_par_seconde),
        # Toujours dans l'ordre x, y, z, comme le RP2040.
        "axes": "".join(axe for axe in "xyz" if axe in capteur.axes),
        "seuil_mg": str(round(choc.seuil_g * 1000)),
        "duree_min_ms": str(choc.duree_min_ms),
        "maintien_ms": str(choc.maintien_ms),
        "constante_fond_ms": str(choc.constante_fond_ms),
        "sans_mesure_ms": str(panne.sans_mesure_ms),
        "erreurs_lecture_max": str(panne.erreurs_lecture_max),
        "figee_ms": str(panne.figee_ms),
        "reessai_ms": str(panne.reessai_ms),
    }


def lire_reglages(texte: str) -> dict[str, str]:
    """Réponse à REGLAGES → {nom: valeur}."""
    mot, champs = lire_champs(texte)
    if mot != "REGLAGES":
        raise ErreurProtocole(f"réponse inattendue « {texte} »")
    manquants = [nom for nom in NOMS_REGLAGES if nom not in champs]
    if manquants:
        raise ErreurProtocole(f"réglages absents de la réponse : {', '.join(manquants)}")
    return champs


def question_regler(valeurs: dict[str, str]) -> str:
    return "REGLER " + " ".join(f"{nom}={valeurs[nom]}" for nom in NOMS_REGLAGES)
