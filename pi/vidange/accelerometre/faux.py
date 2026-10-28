"""Un faux RP2040 d'accéléromètre au bout du fil série unique, pour les tests.

    rp2040 = FauxRp2040(reglages.accelerometre)
    liaison = LiaisonAccelerometre(reglages.accelerometre, rp2040.ouvrir, registre)
    rp2040.choc(3.2, duree_ms=12)        # un choc fini
    rp2040.choc(2.0, fini=False)         # un choc qui dure encore
    rp2040.panne = 0x02                  # capteur absent
    rp2040.redemarrer(chien=True)        # redémarrage (par le chien de garde)
    rp2040.debrancher() / rp2040.rebrancher()
    rp2040.abimer = 1                    # la prochaine réponse arrive abîmée (CRC faux)

Il répond comme le programme du RP2040 (accelerometre/src/liaison.c), et le Pi entend aussi
ce qu'il envoie lui-même (même fil), comme sur la vraie machine.

Il a aussi un faux chargeur (accelerometre/src/chargeur_protocole.c) : la question CHARGEUR
le fait redémarrer dedans, LANCER relance le programme. Le programme installé est un fichier
« accelerometre.bin » (fiche puis programme) :

    rp2040.installe                      # le fichier installé (None : rien, b"" : abîmé)
    rp2040.mode                          # "programme" ou "chargeur"
    rp2040.panne_ecriture = 1            # la prochaine page est refusée (écriture ratée)
"""

import threading

from vidange.accelerometre.fichier_programme import (
    FICHE_TAILLE,
    ErreurFichier,
    Fiche,
    assembler,
    crc32,
    lire_fichier,
)
from vidange.accelerometre.protocole import (
    HISTORIQUE_CHOCS,
    LIGNE_MAX_CHARGEUR,
    NOMS_REGLAGES,
    Decodeur,
    lire_champs,
    reglages_pour_rp2040,
    trame,
)
from vidange.reglages import ReglagesAccelerometre

# Comme accelerometre/plan_memoire.cmake, avec 2 Mio de flash.
ADRESSE_PROGRAMME = 0x10009000
PLACE = 2 * 1024 * 1024 - 0x9000
PAGE = 256


def faux_fichier(nom: str = "origine", taille: int = 3000) -> bytes:
    """Un fichier de programme pour les essais (fiche puis programme)."""
    graine = sum(nom.encode())
    programme = bytes((i * 7 + graine) % 256 for i in range(taille))
    return assembler(programme, ADRESSE_PROGRAMME, nom)


class FauxRp2040:
    def __init__(self, reglages: ReglagesAccelerometre, installe: bytes | None = None) -> None:
        self._verrou = threading.Lock()
        self.installe: bytes | None = faux_fichier() if installe is None else installe
        self.mode = "programme"
        self.fil = reglages.broches.fil_serie
        self.sortie_ok = reglages.broches.sortie_ok
        self.redemarrages = 0
        self.panne_ecriture = 0
        self._debut: Fiche | None = None  # DEBUT reçu
        self._ecrit = bytearray()
        self._silence = 0  # questions sans réponse (redémarrage en cours)
        self.reglages = reglages_pour_rp2040(reglages)
        self.t_ms = 1000
        self.panne = 0
        self.pannes_vues = 0
        self.en_choc = False
        self.max_mg = 80
        self.chien = False
        self.chocs: list[dict[str, int]] = []
        self.branche = True
        self.muet = False
        self.abimer = 0
        self.questions: list[str] = []
        self.ouvertures = 0
        self._decodeur = Decodeur(LIGNE_MAX_CHARGEUR)
        self._sortie = b""

    # ------------------------------------------------------------ côté essais

    def choc(self, pic_g: float, duree_ms: int = 10, fini: bool = True) -> None:
        with self._verrou:
            self.t_ms += 100
            self.chocs.append(
                {"t_ms": self.t_ms, "duree_ms": duree_ms, "pic_mg": round(pic_g * 1000)}
            )
            self.en_choc = not fini

    def finir_choc(self) -> None:
        self.en_choc = False

    def redemarrer(self, chien: bool = False) -> None:
        with self._verrou:
            self.t_ms = 500
            self.chocs = []
            self.en_choc = False
            self.chien = chien
            self.pannes_vues = 0

    def debrancher(self) -> None:
        self.branche = False

    def rebrancher(self) -> None:
        self.branche = True

    # ------------------------------------------------------------ port série

    def ouvrir(self) -> "FauxRp2040":
        if not self.branche:
            raise OSError("pas de port série")
        self.ouvertures += 1
        return self

    def write(self, donnees: bytes) -> int:
        if not self.branche:
            raise OSError("câble débranché")
        with self._verrou:
            self._sortie += donnees  # écho : le Pi s'entend lui-même
            for question in self._decodeur.ajouter(donnees):
                self.questions.append(question)
                if self.muet or self._silence > 0:
                    self._silence = max(0, self._silence - 1)
                    continue
                if self.mode == "chargeur":
                    texte = self._repondre_chargeur(question)
                else:
                    texte = self._repondre(question)
                reponse = trame(texte, LIGNE_MAX_CHARGEUR)
                self._apres(texte)
                if self.abimer > 0:
                    self.abimer -= 1
                    reponse = reponse[:2] + b"#" + reponse[3:]
                self._sortie += reponse
        return len(donnees)

    def read(self, taille: int) -> bytes:
        if not self.branche:
            raise OSError("câble débranché")
        with self._verrou:
            donnees, self._sortie = self._sortie[:taille], self._sortie[taille:]
            return donnees

    def reset_input_buffer(self) -> None:
        with self._verrou:
            self._sortie = b""

    def close(self) -> None:
        pass

    # ------------------------------------------------------------ réponses

    def _repondre(self, question: str) -> str:
        self.t_ms += 10
        self.pannes_vues |= self.panne
        mot, _, suite = question.partition(" ")
        if question == "ETAT":
            ok = self.panne == 0 and not self.en_choc
            max_mg, self.max_mg = self.max_mg, 0
            return (
                f"ETAT t_ms={self.t_ms} ok={int(ok)} choc={int(self.en_choc)} "
                f"pannes={self.panne} vues={self.pannes_vues} max_mg={max_mg} "
                f"chocs={len(self.chocs)} perdues=0 chien={int(self.chien)} contredit=0"
            )
        if mot == "CHOC" and suite.isdigit():
            numero = int(suite)
            if (
                numero < 1
                or numero > len(self.chocs)
                or len(self.chocs) - numero >= HISTORIQUE_CHOCS
            ):
                return f"CHOC n={numero} absent=1"
            choc = self.chocs[numero - 1]
            fini = int(numero < len(self.chocs) or not self.en_choc)
            return (
                f"CHOC n={numero} t_ms={choc['t_ms']} duree_ms={choc['duree_ms']} "
                f"pic_mg={choc['pic_mg']} fini={fini}"
            )
        if question == "REGLAGES":
            return "REGLAGES " + " ".join(f"{nom}={self.reglages[nom]}" for nom in NOMS_REGLAGES)
        if mot == "REGLER":
            _, champs = lire_champs(question)
            if sorted(champs) != sorted(NOMS_REGLAGES):
                return "REGLER refuse réglage inconnu ou écrit deux fois"
            if int(champs["seuil_mg"]) >= int(champs["pleine_echelle_g"]) * 1000:
                return "REGLER refuse seuil : plus que 0 et moins que la pleine échelle"
            self.reglages = dict(champs)
            return "REGLER ok"
        if question == "VERSION":
            fiche = self._fiche()
            if fiche is None:
                return "VERSION fiche=absente"
            return f"VERSION nom={fiche.nom} taille={fiche.taille} crc={fiche.crc:08X}"
        if question == "CHARGEUR":
            return "CHARGEUR redemarre"
        return "ERREUR commande inconnue"

    # ------------------------------------------------------------ chargeur

    def _fiche(self) -> Fiche | None:
        try:
            return Fiche.lire(self.installe or b"")
        except ErreurFichier:
            return None

    def _etat_programme(self) -> str:
        if not self.installe:
            return "absent" if self.installe is None else "abime"
        try:
            lire_fichier(self.installe)
        except ErreurFichier:
            return "abime"
        return "bon"

    def _apres(self, reponse: str) -> None:
        """Ce que le RP2040 fait après avoir répondu (redémarrer)."""
        if reponse == "CHARGEUR redemarre":
            self.mode = "chargeur"
            self._redemarrer()
        elif reponse == "LANCER ok":
            self.mode = "programme"
            self._redemarrer()

    def _redemarrer(self) -> None:
        self.redemarrages += 1
        self.t_ms = 500
        self.chocs = []
        self.en_choc = False
        self.chien = False
        self._debut = None
        self._silence = 1  # la question qui suit arrive pendant le redémarrage

    def _repondre_chargeur(self, question: str) -> str:
        mot, _, suite = question.partition(" ")
        if question == "CHARGEUR":
            texte = (
                f"CHARGEUR pret version=1 fil={self.fil} sortie_ok={self.sortie_ok} "
                f"place={PLACE} programme={self._etat_programme()}"
            )
            fiche = self._fiche()
            if fiche is not None and self._debut is None:
                texte += (
                    f" adresse={fiche.adresse:08X} taille={fiche.taille} crc={fiche.crc:08X} "
                    f"nom={fiche.nom}"
                )
            return texte
        if mot == "DEBUT":
            _, champs = lire_champs(question)
            try:
                fiche = Fiche(
                    int(champs["adresse"], 16),
                    int(champs["taille"]),
                    int(champs["crc"], 16),
                    champs["nom"],
                )
            except (KeyError, ValueError):
                return "DEBUT refuse il faut adresse, taille, crc et nom"
            if fiche.adresse != ADRESSE_PROGRAMME:
                return (
                    f"DEBUT refuse programme fabriqué pour l'adresse {fiche.adresse:08X}, "
                    f"pas {ADRESSE_PROGRAMME:08X}"
                )
            if not 0 < fiche.taille <= PLACE:
                return f"DEBUT refuse taille de 1 à {PLACE} octets"
            self.installe = None
            self._debut = fiche
            self._ecrit = bytearray()
            return "DEBUT ok"
        if mot == "ECRIRE":
            numero_texte, _, hexa = suite.partition(" ")
            if self._debut is None:
                return "ECRIRE refuse pas de DEBUT"
            numero = int(numero_texte)
            page = bytes.fromhex(hexa)
            debut = numero * PAGE
            if numero + 1 == len(self._ecrit) // PAGE + (len(self._ecrit) % PAGE > 0):
                if bytes(self._ecrit[debut : debut + PAGE]) == page:
                    return f"ECRIRE ok n={numero}"
            if debut != len(self._ecrit):
                return f"ECRIRE refuse page attendue {len(self._ecrit) // PAGE}"
            if len(page) != min(PAGE, self._debut.taille - debut):
                return f"ECRIRE refuse page {numero} : mauvaise longueur"
            if self.panne_ecriture > 0:
                self.panne_ecriture -= 1
                return "ECRIRE refuse écriture ratée"
            self._ecrit += page
            return f"ECRIRE ok n={numero}"
        if question == "FIN":
            debut = self._debut
            if debut is None:
                return "FIN refuse pas de DEBUT"
            if len(self._ecrit) < debut.taille:
                return f"FIN refuse il manque des pages ({len(self._ecrit) // PAGE} écrites)"
            self._debut = None
            lu = crc32(bytes(self._ecrit))
            if lu != debut.crc:
                return f"FIN refuse contrôle faux ({lu:08X} au lieu de {debut.crc:08X})"
            self.installe = debut.octets() + bytes(self._ecrit)
            return f"FIN ok crc={lu:08X}"
        if mot == "LIRE":
            numero = int(suite)
            octets = (self.installe or b"")[FICHE_TAILLE:]
            if numero >= PLACE // PAGE:
                return "LIRE refuse page hors de la zone"
            page = octets[numero * PAGE : (numero + 1) * PAGE]
            page += b"\xff" * (PAGE - len(page))
            return f"LIRE n={numero} {page.hex().upper()}"
        if question == "LANCER":
            if self._etat_programme() == "bon" and self._debut is None:
                return "LANCER ok"
            return "LANCER refuse pas de programme bon"
        return "ERREUR chargeur"
