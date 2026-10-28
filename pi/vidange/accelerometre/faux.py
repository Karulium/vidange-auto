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
"""

import threading

from vidange.accelerometre.protocole import (
    HISTORIQUE_CHOCS,
    NOMS_REGLAGES,
    Decodeur,
    lire_champs,
    reglages_pour_rp2040,
    trame,
)
from vidange.reglages import ReglagesAccelerometre


class FauxRp2040:
    def __init__(self, reglages: ReglagesAccelerometre) -> None:
        self._verrou = threading.Lock()
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
        self._decodeur = Decodeur()
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
                if self.muet:
                    continue
                reponse = trame(self._repondre(question))
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
        return "ERREUR commande inconnue"
