"""Protocole série de l'écran Nextion : ce que le Pi envoie, ce que l'écran renvoie.

Le Pi envoie des ordres en texte, chacun suivi de trois octets 0xFF :

    page etat
    t_mode.txt="Mode : Production"
    b_bandeau.bco=2016

L'écran renvoie des trames, elles aussi finies par trois 0xFF :
- un appui sur un bouton : « @nom » (le bouton l'envoie lui-même, avec le code de son
  événement « Touch Release » : voir nextion/pages.md) ;
- le numéro de la page affichée (réponse à « sendme ») ;
- « écran démarré » (mise sous tension ou redémarrage) ;
- un code d'erreur (ordre inconnu, objet absent de la page...).

Les textes sont envoyés en ISO-8859-1 (« latin-1 ») : les polices de Nextion Editor doivent
être générées dans ce codage, sinon les accents s'affichent mal.
"""

from dataclasses import dataclass

FIN = b"\xff\xff\xff"
# Début des trames « bouton » : 0x40 n'est aucun code de retour de Nextion.
DEBUT_APPUI = b"@"
CODAGE = "latin-1"

# Codes de retour de l'écran (un octet suivi de FIN).
CODE_TOUCHER = 0x65
CODE_PAGE = 0x66
CODE_DEMARRE = 0x88
CODE_PRET = 0x00  # « 00 00 00 FF FF FF » : l'écran vient de s'allumer
CODE_SUCCES = 0x01
CODE_VEILLE = 0x86
CODE_REVEIL = 0x87

ERREURS = {
    0x00: "ordre inconnu",
    0x02: "objet inconnu sur la page",
    0x03: "page inconnue",
    0x04: "image inconnue",
    0x05: "police inconnue",
    0x1A: "attribut ou variable inconnu",
    0x1B: "opération impossible",
    0x1C: "valeur impossible à donner",
    0x1E: "mauvais nombre de paramètres",
    0x20: "caractère d'échappement faux",
    0x23: "nom trop long",
    0x24: "tampon série de l'écran plein",
}

# Caractères absents de l'ISO-8859-1 que l'on remplace par un équivalent lisible.
REMPLACEMENTS = str.maketrans(
    {
        "’": "'",
        "‘": "'",
        "“": '"',
        "”": '"',
        "—": "-",
        "–": "-",
        "…": "...",
        "œ": "oe",
        "Œ": "OE",
        " ": " ",
        " ": " ",
    }
)


# ------------------------------------------------------------ envoi


def preparer_texte(texte: str) -> str:
    """Le texte tel que l'écran saura l'afficher (caractères remplacés, sans retour à la ligne)."""
    return " ".join(texte.translate(REMPLACEMENTS).split())


def ordre(texte: str) -> bytes:
    """Un ordre prêt à partir sur le fil."""
    return texte.encode(CODAGE, errors="replace") + FIN


def ordre_page(page: str) -> bytes:
    return ordre(f"page {page}")


def ordre_valeur(attribut: str, valeur: str | int) -> bytes:
    """« objet.attribut=valeur » : un texte entre guillemets, un nombre tel quel."""
    if isinstance(valeur, str):
        echappe = preparer_texte(valeur).replace("\\", "\\\\").replace('"', '\\"')
        return ordre(f'{attribut}="{echappe}"')
    return ordre(f"{attribut}={int(valeur)}")


def couleur_565(couleur: str) -> int:
    """« #RRGGBB » → le nombre de couleur de Nextion (16 bits : 5 rouge, 6 vert, 5 bleu)."""
    rouge, vert, bleu = (int(couleur[i : i + 2], 16) for i in (1, 3, 5))
    return ((rouge >> 3) << 11) | ((vert >> 2) << 5) | (bleu >> 3)


# ------------------------------------------------------------ réception


@dataclass(frozen=True)
class Appui:
    """Un bouton a été touché puis relâché."""

    bouton: str


@dataclass(frozen=True)
class NumeroPage:
    """La page affichée (réponse à « sendme »)."""

    numero: int


@dataclass(frozen=True)
class Demarrage:
    """L'écran vient de démarrer : il a tout oublié, il faut tout lui renvoyer."""


@dataclass(frozen=True)
class Retour:
    """Un autre code de l'écran : erreur, veille, réveil, appui sans code « prints »..."""

    code: int
    donnees: bytes = b""

    @property
    def erreur(self) -> str | None:
        return ERREURS.get(self.code) if not self.donnees else None


Trame = Appui | NumeroPage | Demarrage | Retour


def lire_trame(contenu: bytes) -> Trame | None:
    """Une trame reçue (sans ses trois 0xFF), ou None si elle est vide."""
    if not contenu:
        return None
    if contenu.startswith(DEBUT_APPUI):
        return Appui(contenu[1:].decode(CODAGE).strip())
    code, reste = contenu[0], contenu[1:]
    if code == CODE_PAGE and len(reste) == 1:
        return NumeroPage(reste[0])
    if code == CODE_DEMARRE and not reste:
        return Demarrage()
    if contenu == bytes([CODE_PRET] * 3):
        return Demarrage()
    return Retour(code, reste)


class Decodeur:
    """Découpe les octets reçus en trames (ils peuvent arriver par morceaux)."""

    # Au-delà, ce qui arrive n'est pas de l'écran (mauvaise vitesse, fil qui grésille) : on jette.
    TAILLE_MAX = 256

    def __init__(self) -> None:
        self._tampon = b""

    def ajouter(self, octets: bytes) -> list[Trame]:
        self._tampon += octets
        trames: list[Trame] = []
        while FIN in self._tampon:
            contenu, _, self._tampon = self._tampon.partition(FIN)
            trame = lire_trame(contenu)
            if trame is not None:
                trames.append(trame)
        if len(self._tampon) > self.TAILLE_MAX:
            self._tampon = b""
        return trames
