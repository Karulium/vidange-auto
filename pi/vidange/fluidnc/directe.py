"""Liaison directe avec un faux FluidNC, pour le simulateur (temps simulé, sans fil d'exécution).

    carte = FauxFluidnc(axes="XYZA", horloge=lambda: simulateur.temps)
    liaison = LiaisonDirecte("mycelium_lavage", carte)
    liaison.envoyer("$HY")      # comme Liaison.envoyer : la ligne part tout de suite
    liaison.etat                # demande l'état (« ? ») et lit tout ce que la carte a répondu

Elle a ce dont les gestes ont besoin de `Liaison` (envoyer, etat, nom), mais tout se passe au
moment de l'appel : le simulateur avance son heure, la carte se met à l'heure quand on lui parle.
"""

from collections import deque
from dataclasses import replace

from vidange.fluidnc import protocole
from vidange.fluidnc.faux import FauxFluidnc
from vidange.fluidnc.liaison import Commande, EtatCarte


class LiaisonDirecte:
    def __init__(self, nom: str, carte: FauxFluidnc) -> None:
        self.nom = nom
        self.carte = carte
        self._attente: deque[Commande] = deque()
        self._etat = EtatCarte(connectee=True)

    def envoyer(self, ligne: str) -> Commande:
        commande = Commande(ligne.strip())
        self._attente.append(commande)
        self.carte._recevoir(commande.donnees)
        self._lire()
        return commande

    @property
    def etat(self) -> EtatCarte:
        self.carte._recevoir(protocole.DEMANDE_ETAT)
        self._lire()
        return replace(self._etat, lignes_en_cours=len(self._attente))

    def _lire(self) -> None:
        self.carte.avancer()
        sorties = self.carte._sorties
        while sorties:
            ligne = sorties.popleft()
            sorte, numero = protocole.classer_ligne(ligne)
            if sorte == "etat":
                rapport = protocole.lire_rapport_etat(ligne)
                assert rapport is not None
                self._etat = replace(
                    self._etat,
                    etat=rapport.etat,
                    positions=rapport.positions,
                    entrees_actives=rapport.entrees_actives,
                    alarme=self._etat.alarme if rapport.etat.startswith("Alarm") else None,
                    rapports_recus=self._etat.rapports_recus + 1,
                )
            elif sorte in ("ok", "erreur") and self._attente:
                commande = self._attente.popleft()
                commande.rapports_a_la_reponse = self._etat.rapports_recus
                erreur = None if sorte == "ok" else protocole.decrire_erreur(numero or 0)
                commande._finir(erreur and f"refusée par la carte, {erreur}")
            elif sorte == "alarme":
                for commande in self._attente:
                    commande._finir(f"interrompue : {protocole.decrire_alarme(numero or 0)}")
                self._etat = replace(self._etat, etat="Alarm", alarme=numero)
