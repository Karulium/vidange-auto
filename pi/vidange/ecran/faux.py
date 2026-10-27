"""Un faux écran Nextion, pour les tests et le simulateur.

    ecran = FauxNextion()
    liaison = LiaisonEcran(reglages, ecran.ouvrir)
    ecran.page                      # « etat »
    ecran.texte("b_bandeau")        # « EN MARCHE »
    ecran.appuyer("b_go")           # comme un doigt sur le bouton
    ecran.redemarrer()              # coupure de courant de l'écran
    ecran.debrancher() / ecran.rebrancher()

Il comprend les ordres que le Pi envoie (page, attributs, sendme), refuse comme le vrai un
objet absent de la page (d'après pages.py) et répond à « sendme » par le numéro de la page.
"""

import threading

from vidange.ecran.pages import PAGES
from vidange.ecran.protocole import CODAGE, CODE_PAGE, FIN

OBJET_INCONNU = 0x02
PAGE_INCONNUE = 0x03
ORDRE_INCONNU = 0x00


class FauxNextion:
    def __init__(self, page: str = "etat") -> None:
        self._verrou = threading.Lock()
        self.page = page
        # Valeurs de la page affichée : « objet.attribut » → valeur (texte ou nombre).
        self.valeurs: dict[str, str | int] = {}
        self.ordres: list[str] = []
        self._a_lire = b""
        self._recu = b""
        self.branche = True
        self.muet = False
        self.ouvertures = 0

    # ------------------------------------------------------------ côté Pi (le « port »)

    def ouvrir(self) -> "FauxNextion":
        if not self.branche:
            raise OSError("fichier de l'UART introuvable")
        self.ouvertures += 1
        return self

    def write(self, donnees: bytes) -> int:
        if not self.branche:
            raise OSError("écran débranché")
        with self._verrou:
            self._recu += donnees
            while FIN in self._recu:
                ordre, _, self._recu = self._recu.partition(FIN)
                self._executer(ordre.decode(CODAGE))
        return len(donnees)

    def read(self, taille: int) -> bytes:
        if not self.branche:
            raise OSError("écran débranché")
        with self._verrou:
            morceau, self._a_lire = self._a_lire[:taille], self._a_lire[taille:]
            return morceau

    def close(self) -> None:
        pass

    # ------------------------------------------------------------ côté atelier

    def appuyer(self, bouton: str) -> None:
        """Un appui (touché puis relâché) : le bouton envoie « @nom »."""
        self._repondre(b"@" + bouton.encode(CODAGE))

    def redemarrer(self) -> None:
        """L'écran redémarre : il revient à la page 0 avec les valeurs de Nextion Editor."""
        with self._verrou:
            self.page = "etat"
            self.valeurs = {}
        self._repondre(b"\x00\x00\x00")
        self._repondre(b"\x88")

    def debrancher(self) -> None:
        self.branche = False

    def rebrancher(self) -> None:
        self.branche = True

    def texte(self, objet: str) -> str:
        return str(self.valeurs.get(f"{objet}.txt", ""))

    def couleur(self, objet: str) -> int | None:
        valeur = self.valeurs.get(f"{objet}.bco")
        return None if valeur is None else int(valeur)

    # ------------------------------------------------------------ interne

    def _repondre(self, contenu: bytes) -> None:
        if self.muet:
            return
        with self._verrou:
            self._a_lire += contenu + FIN

    def _erreur(self, code: int) -> None:
        if not self.muet:
            self._a_lire += bytes([code]) + FIN

    def _executer(self, ordre: str) -> None:
        self.ordres.append(ordre)
        if ordre == "sendme":
            if not self.muet:
                self._a_lire += bytes([CODE_PAGE, PAGES[self.page].numero]) + FIN
        elif ordre.startswith("page "):
            nom = ordre.removeprefix("page ")
            if nom not in PAGES:
                self._erreur(PAGE_INCONNUE)
                return
            self.page = nom
            self.valeurs = {}
        elif "=" in ordre and "." in ordre.split("=", 1)[0]:
            attribut, valeur = ordre.split("=", 1)
            objet = attribut.split(".", 1)[0]
            if objet not in {o.nom for o in PAGES[self.page].objets}:
                self._erreur(OBJET_INCONNU)
                return
            if valeur.startswith('"'):
                texte = valeur[1:-1].replace('\\"', '"').replace("\\\\", "\\")
                self.valeurs[attribut] = texte
            else:
                self.valeurs[attribut] = int(valeur)
        else:
            self._erreur(ORDRE_INCONNU)
