"""Lecture d'un capteur de particules Sensirion SPS30 sur sa propre liaison série (SHDLC).

Le Pi lit les particules pour **attendre la fin de la purge** : la sécurité est câblée.

- Le capteur est démarré à la première lecture (« start measurement »), et à nouveau s'il dit
  qu'il ne mesure plus. S'il mesurait déjà (le Pi a redémarré, pas le capteur), c'est bon.
- Une trame à la somme fausse, coupée ou d'une autre commande est ignorée et comptée.
- Plus aucune mesure valable depuis `delai_muet_s` : le capteur est « muet » (CapteurMuet) et
  `lire` lève ErreurMateriel : le Nettoyage ne tient alors **jamais** la condition pour vraie.
- Une mesure qui n'est pas un nombre fini et positif est une trame abîmée, jamais une valeur.
"""

import math
import threading
import time
from collections.abc import Callable

from vidange import trame_sps30 as shdlc
from vidange.entrees_sorties import CapteurParticules
from vidange.materiel.modbus import PortSerie
from vidange.materiel.ozone import CapteurMuet
from vidange.materiel.puces import ErreurMateriel

# Au plus ce nombre d'octets lus pour une réponse (une réponse de mesure en fait au plus ~100
# avec les échappements) : protège contre un fil qui ne s'arrête pas de parler.
OCTETS_MAX_PAR_REPONSE = 400


class PasDeReponse(shdlc.ErreurTrame):
    """Rien reçu avant la fin du délai du port."""


class LecteurSps30:
    """Un capteur SPS30. Le port est ouvert à la première lecture, et rouvert après une erreur."""

    def __init__(
        self,
        ouvrir: Callable[[], PortSerie],
        reglage: CapteurParticules,
        nom: str = "particules",
        horloge: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ouvrir = ouvrir
        self.reglage = reglage
        self.nom = nom
        self._horloge = horloge
        self._port: PortSerie | None = None
        self._verrou = threading.Lock()
        self._demarre = False
        self._derniere: tuple[float, float] | None = None  # (valeur, moment d'arrivée)
        self._depuis = horloge()
        self.trames_ignorees = 0

    def lire(self) -> float:
        """La dernière mesure valable (µg/m³). Lève ErreurMateriel si elle manque : CapteurMuet
        quand plus rien de valable n'arrive depuis `delai_muet_s`."""
        with self._verrou:
            try:
                if self._port is None:
                    self._port = self._ouvrir()
                    self._port.reset_input_buffer()
                    self._demarre = False
                    self._depuis = self._horloge()
                if not self._demarre:
                    self._demarrer(self._port)
                if self._demarre:
                    self._interroger(self._port)
            except OSError as erreur:
                self._fermer()
                raise ErreurMateriel(f"{self.nom} : port série en panne ({erreur})") from None
            return self._mesure()

    # ---------------------------------------------------------------- échanges

    def _echanger(self, port: PortSerie, commande: int, donnees: bytes = b"") -> shdlc.Reponse:
        question = shdlc.construire_question(commande, donnees)
        port.reset_input_buffer()
        port.write(question)
        tampon = bytearray()
        while len(tampon) < OCTETS_MAX_PAR_REPONSE:
            morceau = port.read(max(1, getattr(port, "in_waiting", 0)))
            if not morceau:
                break
            tampon += morceau
            trames, _ = shdlc.decouper_trames(bytes(tampon))
            # L'adaptateur RS485 peut renvoyer ce que le Pi vient d'écrire (écho) : on l'ignore.
            trames = [t for t in trames if t != question]
            if trames:
                reponse = shdlc.decoder_reponse(trames[0])
                if reponse.commande != commande:
                    raise shdlc.ErreurTrame("réponse à une autre commande")
                return reponse
        raise PasDeReponse("aucune réponse")

    def _demarrer(self, port: PortSerie) -> None:
        try:
            reponse = self._echanger(port, shdlc.COMMANDE_DEMARRER, shdlc.DONNEES_DEMARRER)
        except PasDeReponse:
            return  # muet : _mesure() le dira après le délai
        except shdlc.ErreurTrame:
            self.trames_ignorees += 1
            return
        code = reponse.etat & shdlc.MASQUE_CODE_ERREUR
        # 0x43 (commande pas permise) : il mesure déjà.
        if code not in (0, 0x43):
            raise ErreurMateriel(f"{self.nom} : démarrage refusé ({self._texte_code(code)})")
        self._demarre = True

    def _interroger(self, port: PortSerie) -> None:
        try:
            reponse = self._echanger(port, shdlc.COMMANDE_LIRE)
            code = reponse.etat & shdlc.MASQUE_CODE_ERREUR
            if code == 0x43:
                # Il ne mesure plus (il a redémarré tout seul) : on le redémarre au tour suivant.
                self._demarre = False
                return
            if code:
                raise ErreurMateriel(f"{self.nom} : erreur du capteur ({self._texte_code(code)})")
            if not reponse.donnees:
                return  # pas de mesure nouvelle : la précédente reste valable un temps
            valeurs = shdlc.valeurs_mesurees(reponse.donnees)
            valeur = valeurs[shdlc.RANG_GRANDEUR[self.reglage.grandeur]]
            if not math.isfinite(valeur) or valeur < 0:
                raise shdlc.ErreurTrame("mesure qui n'est pas un nombre")
            self._derniere = (valeur, self._horloge())
        except PasDeReponse:
            return
        except shdlc.ErreurTrame:
            self.trames_ignorees += 1

    @staticmethod
    def _texte_code(code: int) -> str:
        return shdlc.ERREURS_CAPTEUR.get(code, f"code 0x{code:02x}")

    # ---------------------------------------------------------------- résultat

    def _mesure(self) -> float:
        maintenant = self._horloge()
        delai = self.reglage.delai_muet_s
        if self._derniere is None:
            if maintenant - self._depuis > delai:
                raise CapteurMuet(
                    f"{self.nom} : muet, aucune mesure valable depuis {delai:g} s (débranché, "
                    "pas alimenté, mauvaise vitesse ?)"
                )
            raise ErreurMateriel(f"{self.nom} : en attente de la première mesure")
        valeur, moment = self._derniere
        age = maintenant - moment
        if age > delai:
            raise CapteurMuet(f"{self.nom} : muet, aucune mesure valable depuis {age:.0f} s")
        return valeur

    def _fermer(self) -> None:
        if self._port is not None:
            try:
                self._port.close()
            except OSError:
                pass
            self._port = None
        self._demarre = False

    def fermer(self) -> None:
        with self._verrou:
            self._fermer()
