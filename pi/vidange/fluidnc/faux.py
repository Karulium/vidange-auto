"""Faux FluidNC : une carte imaginaire pour les tests et le simulateur.

Il répond comme une vraie carte : « ok » / « error:N » à chaque ligne, rapport d'état à « ? »,
pause « ! », reprise « ~ », réinitialisation Ctrl-X, alarmes, déblocage « $X ».
Les positions avancent avec le temps, à la vitesse demandée (F, ou la vitesse rapide pour G0),
en ligne droite et sans accélération.

Comme une vraie carte, il a :
- un tampon de réception limité : s'il reçoit plus que sa taille sans avoir répondu, il le note
  (« debordement ») ; une vraie carte perdrait des caractères ;
- une file de mouvements limitée : quand elle est pleine, la ligne suivante attend
  (et son « ok » aussi).

On peut simuler : une alarme, un câble coupé puis rebranché, une carte muette, un redémarrage.

Les valeurs par défaut sont celles d'une carte imaginaire, pas de la vraie machine.
"""

import re
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from vidange.fluidnc import protocole

BIENVENUE = "Grbl 3.7 [FluidNC faux (simulateur) '$' for help]"

_MOT = re.compile(r"([A-Z])\s*([-+]?(?:\d+\.?\d*|\.\d+))")
_COMMENTAIRE = re.compile(r"\([^)]*\)|;.*$")


@dataclass
class _Bloc:
    """Un mouvement (cible) ou une attente (duree) dans la file de la carte."""

    cible: dict[str, float] | None = None
    vitesse_mm_min: float = 0.0
    duree_s: float = 0.0
    prise_origine: bool = False


class _ErreurLigne(Exception):
    def __init__(self, numero: int) -> None:
        self.numero = numero


class FauxFluidnc:
    def __init__(
        self,
        axes: str = "XYZ",
        vitesse_rapide_mm_min: float = 6000.0,
        taille_tampon: int = 128,
        taille_file: int = 16,
        horloge: Callable[[], float] = time.monotonic,
        delai_lecture_s: float = 0.01,
        en_alarme_au_depart: bool = False,
    ) -> None:
        if not axes or not set(axes) <= set(protocole.LETTRES_AXES):
            raise ValueError(f"axes : lettres parmi {protocole.LETTRES_AXES}")
        self.axes = axes
        self.vitesse_rapide_mm_min = vitesse_rapide_mm_min
        self.taille_tampon = taille_tampon
        self.taille_file = taille_file
        self.delai_lecture_s = delai_lecture_s
        self._horloge = horloge
        self._verrou = threading.RLock()
        self._nouveau = threading.Condition(self._verrou)

        self.positions = {axe: 0.0 for axe in axes}
        self.etat = "Alarm" if en_alarme_au_depart else "Idle"
        self.en_pause = False
        # Ce qui a été simulé ou constaté, pour les tests.
        self.debordement = False
        self.plus_grand_tampon = 0
        self.lignes_recues: list[str] = []
        # Simulations.
        self.cable_coupe = False
        self.muet = False
        # Change à chaque coupure : un port ouvert avant une coupure reste mort.
        self._branchement = 0

        self._tampon = b""
        self._file: deque[_Bloc] = deque()
        self._attente_ok: _Bloc | None = None
        self._sorties: deque[str] = deque()
        self._absolu = True
        self._mode_mouvement = 0
        self._vitesse_mm_min: float | None = None
        self._vitesse_actuelle = 0.0
        self._dernier = horloge()

    # ------------------------------------------------------------ côté câble

    def ouvrir(self) -> "FauxPort":
        """Ce que fait le Pi en ouvrant le port USB. Échoue si le câble est coupé."""
        with self._verrou:
            if self.cable_coupe:
                raise OSError("faux FluidNC : câble coupé, port introuvable")
            return FauxPort(self)

    def _recevoir(self, donnees: bytes) -> None:
        with self._verrou:
            self._verifier_cable()
            self.avancer()
            for octet in donnees:
                caractere = chr(octet)
                if caractere in protocole.CARACTERES_TEMPS_REEL:
                    self._temps_reel(caractere)
                else:
                    self._tampon += bytes([octet])
            self.plus_grand_tampon = max(self.plus_grand_tampon, len(self._tampon))
            if len(self._tampon) > self.taille_tampon:
                self.debordement = True
            self.avancer()
            self._nouveau.notify_all()

    def _lire_ligne(self, port: "FauxPort") -> bytes:
        fin = time.monotonic() + self.delai_lecture_s
        with self._verrou:
            while True:
                self._verifier_cable(port)
                self.avancer()
                if self._sorties and not self.muet:
                    return (self._sorties.popleft() + "\r\n").encode("ascii")
                reste = fin - time.monotonic()
                if reste <= 0:
                    return b""
                self._nouveau.wait(min(reste, 0.005))

    def _verifier_cable(self, port: "FauxPort | None" = None) -> None:
        if self.cable_coupe or (port is not None and port.branchement != self._branchement):
            raise OSError("faux FluidNC : câble coupé")

    # ------------------------------------------------------------ simulations

    def couper_cable(self) -> None:
        """Le câble est arraché : le port ne répond plus, ce qui était en route est perdu.

        La carte, elle, continue ses mouvements déjà acceptés.
        """
        with self._verrou:
            self.cable_coupe = True
            self._branchement += 1
            self._tampon = b""
            self._sorties.clear()
            self._nouveau.notify_all()

    def rebrancher(self) -> None:
        with self._verrou:
            self.cable_coupe = False

    def declencher_alarme(self, numero: int = 1) -> None:
        """Alarme (fin de course touchée...) : tout s'arrête, la file est vidée."""
        with self._verrou:
            self.avancer()
            self._sorties.append(f"ALARM:{numero}")
            self._arreter_tout(repondre=True)
            self.etat = "Alarm"
            self._nouveau.notify_all()

    def redemarrer(self) -> None:
        """La carte redémarre seule (coupure de son alimentation...) : position perdue."""
        with self._verrou:
            self._arreter_tout()
            self._tampon = b""
            self.positions = {axe: 0.0 for axe in self.axes}
            self.etat = "Alarm"
            self._sorties.append(BIENVENUE)
            self._nouveau.notify_all()

    @property
    def en_mouvement(self) -> bool:
        with self._verrou:
            self.avancer()
            return bool(self._file)

    # ------------------------------------------------------------ fonctionnement

    def avancer(self) -> None:
        """Met la carte à l'heure : mouvements, puis lignes reçues qui peuvent être traitées."""
        with self._verrou:
            maintenant = self._horloge()
            reste = maintenant - self._dernier
            self._dernier = maintenant
            while True:
                self._traiter_lignes()
                utilise = self._deplacer(max(reste, 0.0))
                if utilise is None:
                    break
                reste -= utilise
            if not self._file and self.etat in ("Run", "Home"):
                self.etat = "Idle"
                self._vitesse_actuelle = 0.0

    def _deplacer(self, duree: float) -> float | None:
        """Fait avancer le premier bloc pendant au plus « duree ».

        Rend le temps utilisé, ou None si rien n'a bougé (file vide, pause, alarme).
        """
        if not self._file or self.en_pause or self.etat == "Alarm":
            return None
        bloc = self._file[0]
        self.etat = "Home" if bloc.prise_origine else "Run"
        if bloc.cible is None:
            self._vitesse_actuelle = 0.0
            utilise = min(duree, bloc.duree_s)
            bloc.duree_s -= utilise
            fini = bloc.duree_s <= 0
        else:
            ecarts = {axe: bloc.cible[axe] - self.positions[axe] for axe in bloc.cible}
            distance = sum(ecart**2 for ecart in ecarts.values()) ** 0.5
            self._vitesse_actuelle = bloc.vitesse_mm_min
            besoin = distance / (bloc.vitesse_mm_min / 60)
            utilise = min(duree, besoin)
            fini = utilise >= besoin
            if fini:
                self.positions.update(bloc.cible)
            else:
                for axe, ecart in ecarts.items():
                    self.positions[axe] += ecart * utilise / besoin
        if not fini:
            return utilise if utilise > 0 else None
        self._file.popleft()
        if bloc is self._attente_ok:
            self._attente_ok = None
            self._sorties.append("ok")
        if not self._file:
            self.etat = "Idle"
            self._vitesse_actuelle = 0.0
        return utilise

    def _traiter_lignes(self) -> None:
        while self._attente_ok is None and len(self._file) < self.taille_file:
            ligne_brute, separateur, reste = self._tampon.partition(b"\n")
            if not separateur:
                return
            self._tampon = reste
            ligne = ligne_brute.decode("ascii", errors="replace").strip()
            self.lignes_recues.append(ligne)
            try:
                self._executer(ligne)
            except _ErreurLigne as erreur:
                self._sorties.append(f"error:{erreur.numero}")

    def _executer(self, ligne: str) -> None:
        if ligne.startswith("$"):
            self._commande_dollar(ligne)
            return
        if self.etat == "Alarm":
            raise _ErreurLigne(9)
        texte = _COMMENTAIRE.sub("", ligne).upper().replace(" ", "")
        mots = _MOT.findall(texte)
        if "".join(lettre + nombre for lettre, nombre in mots) != texte:
            raise _ErreurLigne(2)
        cible: dict[str, float] = {}
        attente = None
        for lettre, nombre in mots:
            valeur = float(nombre)
            if lettre == "G" and valeur in (0, 1):
                self._mode_mouvement = int(valeur)
            elif lettre == "G" and valeur == 4:
                attente = 0.0
            elif lettre == "G" and valeur in (90, 91):
                self._absolu = valeur == 90
            elif lettre == "G" and valeur in (17, 21, 94):
                pass
            elif lettre == "P" and attente is not None:
                attente = valeur
            elif lettre == "F":
                if valeur <= 0:
                    raise _ErreurLigne(23)
                self._vitesse_mm_min = valeur
            elif lettre in self.axes:
                cible[lettre] = valeur
            elif lettre == "M":
                pass
            else:
                raise _ErreurLigne(20)
        if attente is not None:
            # G4 attend d'abord la fin des mouvements d'avant, puis la durée : « ok » à la fin.
            bloc = _Bloc(duree_s=attente)
            self._file.append(bloc)
            self._attente_ok = bloc
            return
        if cible:
            if self._mode_mouvement == 1 and self._vitesse_mm_min is None:
                raise _ErreurLigne(22)
            # Point de départ : la fin du dernier mouvement de la file, sinon la position actuelle.
            depart = dict(self.positions)
            for bloc in self._file:
                if bloc.cible is not None:
                    depart = dict(bloc.cible)
            for axe, valeur in cible.items():
                depart[axe] = valeur if self._absolu else depart[axe] + valeur
            if self._mode_mouvement == 0:
                vitesse = self.vitesse_rapide_mm_min
            else:
                assert self._vitesse_mm_min is not None
                vitesse = self._vitesse_mm_min
            self._file.append(_Bloc(cible=depart, vitesse_mm_min=vitesse))
        self._sorties.append("ok")

    def _commande_dollar(self, ligne: str) -> None:
        commande = ligne.upper()
        if commande == protocole.DEBLOCAGE:
            if self.etat == "Alarm":
                self.etat = "Idle"
                self._sorties.append("[MSG:Caution: Unlocked]")
            self._sorties.append("ok")
        elif commande == protocole.PRISE_ORIGINE:
            if self._file:
                raise _ErreurLigne(8)
            self.etat = "Home"
            bloc = _Bloc(
                cible={axe: 0.0 for axe in self.axes},
                vitesse_mm_min=self.vitesse_rapide_mm_min,
                prise_origine=True,
            )
            self._file.append(bloc)
            self._attente_ok = bloc
        else:
            # Les autres commandes « $ » (réglages, aide) : acceptées sans rien faire.
            self._sorties.append("ok")

    def _temps_reel(self, caractere: str) -> None:
        if caractere == "?":
            self.avancer()
            self._sorties.append(self._rapport())
        elif caractere == "!":
            if self._file and self.etat != "Alarm":
                self.en_pause = True
        elif caractere == "~":
            self.en_pause = False
        elif caractere == "\x18":
            if self._file and self.etat != "Alarm":
                # Arrêt brutal pendant un mouvement : la position n'est plus sûre.
                self._arreter_tout()
                self.etat = "Alarm"
                self._sorties.append("ALARM:3")
            else:
                self._arreter_tout()
            self._tampon = b""
            self._sorties.append(BIENVENUE)

    def _arreter_tout(self, repondre: bool = False) -> None:
        """Vide la file. « repondre » : la ligne qui attendait (G4, $H) reçoit quand même « ok »,
        comme sur Grbl après une alarme ; pas après une réinitialisation (tout est oublié)."""
        self._file.clear()
        if self._attente_ok is not None and repondre:
            self._sorties.append("ok")
        self._attente_ok = None
        self.en_pause = False
        self._vitesse_actuelle = 0.0
        if self.etat in ("Run", "Home"):
            self.etat = "Idle"

    def _rapport(self) -> str:
        if self.etat == "Alarm":
            etat = "Alarm"
        elif self.en_pause:
            etat = "Hold:0"
        else:
            etat = self.etat
        positions = ",".join(f"{self.positions[axe]:.3f}" for axe in self.axes)
        vitesse = 0 if self.en_pause else self._vitesse_actuelle
        return f"<{etat}|MPos:{positions}|FS:{vitesse:g},0>"


class FauxPort:
    """Le port série vu par le Pi, branché sur un faux FluidNC."""

    def __init__(self, carte: FauxFluidnc) -> None:
        self.carte = carte
        self.branchement = carte._branchement
        self.ferme = False

    def write(self, donnees: bytes) -> int:
        if self.ferme:
            raise OSError("faux FluidNC : port fermé")
        with self.carte._verrou:
            self.carte._verifier_cable(self)
            self.carte._recevoir(donnees)
        return len(donnees)

    def readline(self) -> bytes:
        if self.ferme:
            raise OSError("faux FluidNC : port fermé")
        return self.carte._lire_ligne(self)

    def close(self) -> None:
        self.ferme = True
