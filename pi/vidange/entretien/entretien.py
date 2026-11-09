"""Pièces d'usure et calendrier d'entretien : où en est chaque pièce, et quand la changer.

    entretien = Entretien(reglages.entretien, compteurs, registre)
    entretien.etat()                       # une ligne par pièce (page « Maintenance »)
    entretien.fait("vanne_vide", "page web (karulium, 192.168.1.20)")   # pièce remise à neuf
    entretien.constats()                   # pour la check-list de démarrage
    entretien.demarrer(arret)              # surveille en fond, écrit au journal

Chaque pièce de entretien.yaml dit quel compteur la fait vieillir (un axe, un actionneur, le
nombre de seaux, ou le temps qui passe) et sa limite. Les compteurs ne sont jamais remis à zéro :
une pièce garde un POINT DE DÉPART (la valeur du compteur au dernier « fait ») ; son usure est la
différence. Une pièce nouvelle dans le fichier de réglages part de zéro à ce moment-là.

Alertes : « bientôt » quand l'usure dépasse (100 - avance_pourcent) % de la limite, « à faire » à la
limite. Dans la check-list (niveau « attention », JAMAIS « bloquant ») et au journal. L'entretien
informe, il n'arrête pas la machine : un compteur peut se tromper, et la sécurité est câblée.
"""

import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Literal

from vidange.entretien.compteurs import Compteurs, heure_iso
from vidange.fiabilite.constats import Constat, lancer_boucle
from vidange.journal import donner_journal
from vidange.registre import Registre
from vidange.registre.base import heure
from vidange.reglages import GENRES_AXE, PieceEntretien, ReglagesEntretien

journal = donner_journal("entretien")

SUJET = "entretien"
FICHIER_REGISTRE = "entretien"
Niveau = Literal["ok", "bientot", "a_faire"]
SECONDES_PAR_JOUR = 86400

UNITES = {
    "mouvements": "mouvements",
    "heures": "h",
    "manoeuvres": "manœuvres",
    "seaux": "seaux",
    "jours": "jours",
}


class ErreurEntretien(Exception):
    """Un ordre d'entretien impossible (pièce inconnue...)."""


@dataclass(frozen=True)
class EtatPiece:
    nom: str
    description: str
    # Ce qui la fait vieillir, en clair (« distance de pont_x »).
    compteur: str
    # Usure depuis le dernier « fait », limite, et unité des deux.
    usure: float
    limite: float
    unite: str
    pourcent: float
    niveau: Niveau
    a_faire: str
    # La limite est un exemple (entretien.yaml → exemple).
    exemple: bool
    depuis: str | None
    fait_par: str | None

    def en_dict(self) -> dict[str, Any]:
        return asdict(self)


class Entretien:
    def __init__(
        self,
        reglages: ReglagesEntretien,
        compteurs: Compteurs,
        registre: Registre | None = None,
        maintenant: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.reglages = reglages
        self.compteurs = compteurs
        self.registre = registre
        self._maintenant = maintenant
        self._verrou = threading.RLock()
        # Dernier niveau écrit au journal pour chaque pièce (une alerte n'est écrite qu'une fois).
        self._niveaux_vus: dict[str, Niveau] = {}
        for nom in reglages.pieces:
            self._depart(nom)

    # ------------------------------------------------------------ points de départ

    def _valeur_brute(self, piece: PieceEntretien) -> float:
        compteur = piece.compteur
        if compteur.de is None:
            return 0.0
        if compteur.genre in GENRES_AXE:
            return self.compteurs.valeur_axe(compteur.de, compteur.genre)
        return float(self.compteurs.valeur_actionneur(compteur.de))

    def _depart(self, nom: str) -> dict[str, Any]:
        """Le point de départ de la pièce ; une pièce nouvelle part d'aujourd'hui."""
        with self._verrou:
            depart = self.compteurs.departs.get(nom)
            if depart is None:
                depart = {
                    "valeur": self._valeur_brute(self.reglages.pieces[nom]),
                    "date": heure_iso(self._maintenant()),
                    "fait_le": None,
                    "fait_par": None,
                }
                self.compteurs.changer_depart(nom, depart)
            return depart

    # ------------------------------------------------------------ l'état

    def _usure(self, piece: PieceEntretien, depart: dict[str, Any]) -> float:
        genre = piece.compteur.genre
        if genre == "jours":
            ecoule = self._maintenant().astimezone() - datetime.fromisoformat(depart["date"])
            return max(ecoule.total_seconds() / SECONDES_PAR_JOUR, 0.0)
        if genre == "seaux":
            if self.registre is None:
                return 0.0
            ligne = self.registre.lire(
                "SELECT COUNT(*) AS n FROM seaux_du_cycle WHERE quand > ?", (depart["date"],)
            )
            return float(ligne[0]["n"])
        return max(self._valeur_brute(piece) - float(depart["valeur"]), 0.0)

    def _niveau(self, usure: float, limite: float) -> Niveau:
        if usure >= limite:
            return "a_faire"
        if usure >= limite * (1 - self.reglages.alerte.avance_pourcent / 100):
            return "bientot"
        return "ok"

    def _unite(self, piece: PieceEntretien) -> str:
        compteur = piece.compteur
        if compteur.genre == "distance" and compteur.de is not None:
            return self.compteurs.unite_axe(compteur.de)
        return UNITES[compteur.genre]

    @staticmethod
    def _decrire_compteur(piece: PieceEntretien) -> str:
        compteur = piece.compteur
        if compteur.de is None:
            return {"seaux": "nombre de seaux remplis", "jours": "temps qui passe"}[compteur.genre]
        quoi = {
            "distance": "distance parcourue",
            "mouvements": "mouvements",
            "heures": "heures de marche",
            "manoeuvres": "manœuvres",
        }[compteur.genre]
        return f"{quoi} de « {compteur.de} »"

    def etat_piece(self, nom: str) -> EtatPiece:
        piece = self.reglages.pieces.get(nom)
        if piece is None:
            raise ErreurEntretien(
                f"pièce « {nom} » inconnue (pièces : {', '.join(self.reglages.pieces)})"
            )
        depart = self._depart(nom)
        usure = self._usure(piece, depart)
        return EtatPiece(
            nom=nom,
            description=piece.description,
            compteur=self._decrire_compteur(piece),
            usure=round(usure, 3),
            limite=piece.limite,
            unite=self._unite(piece),
            pourcent=round(100 * usure / piece.limite, 1),
            niveau=self._niveau(usure, piece.limite),
            a_faire=piece.a_faire,
            exemple=piece.exemple or self.reglages.exemple,
            depuis=depart["date"],
            fait_par=depart.get("fait_par"),
        )

    def etat(self) -> list[EtatPiece]:
        """Toutes les pièces, les plus urgentes d'abord."""
        gravite = {"a_faire": 0, "bientot": 1, "ok": 2}
        pieces = [self.etat_piece(nom) for nom in self.reglages.pieces]
        return sorted(pieces, key=lambda p: (gravite[p.niveau], -p.pourcent))

    def en_dict(self) -> dict[str, Any]:
        """Pour la page web : les pièces, et les compteurs de chaque axe et actionneur."""
        pieces = self.etat()
        return {
            "exemple": self.reglages.exemple,
            "avance_pourcent": self.reglages.alerte.avance_pourcent,
            "a_faire": [p.nom for p in pieces if p.niveau == "a_faire"],
            "bientot": [p.nom for p in pieces if p.niveau == "bientot"],
            "pieces": [p.en_dict() for p in pieces],
            "compteurs": self.compteurs.instantane(),
        }

    # ------------------------------------------------------------ « fait »

    def fait(self, nom: str, qui: str) -> EtatPiece:
        """La pièce a été contrôlée ou changée : son usure repart de zéro. Noté au journal et dans
        le registre (qui, quand, ce qu'elle avait). Les compteurs à vie ne changent pas."""
        avant = self.etat_piece(nom)
        piece = self.reglages.pieces[nom]
        maintenant = self._maintenant()
        with self._verrou:
            self.compteurs.changer_depart(
                nom,
                {
                    "valeur": self._valeur_brute(piece),
                    "date": heure_iso(maintenant),
                    "fait_le": heure(maintenant),
                    "fait_par": qui,
                },
            )
            self._niveaux_vus[nom] = "ok"
        journal.info(
            "Entretien fait : « %s » remise à zéro par %s (usure avant : %g %s sur %g)",
            avant.description,
            qui,
            avant.usure,
            avant.unite,
            avant.limite,
        )
        if self.registre is not None:
            self.registre.noter_reglage(
                qui,
                FICHIER_REGISTRE,
                nom,
                {"usure": avant.usure, "unite": avant.unite},
                {"usure": 0, "unite": avant.unite},
                f"entretien fait : {avant.description}",
            )
        return self.etat_piece(nom)

    # ------------------------------------------------------------ alertes

    def constats(self) -> list[Constat]:
        """Pour la check-list. Jamais bloquant : l'entretien informe, il n'arrête rien."""
        constats: list[Constat] = []
        if self.compteurs.erreur_lecture:
            constats.append(
                Constat(
                    SUJET,
                    "attention",
                    self.compteurs.erreur_lecture + " : les compteurs repartent de zéro",
                    "Les usures gardées sont perdues : revoir à la main les pièces proches de "
                    "leur limite (la copie de secours garde l'ancien fichier).",
                )
            )
        for piece in self.etat():
            if piece.niveau == "ok":
                continue
            sujet = f"{SUJET} : {piece.description}"
            decrit = f"{piece.usure:g} sur {piece.limite:g} {piece.unite} ({piece.pourcent:g} %)"
            if piece.exemple:
                decrit += ", limite d'exemple"
            if piece.niveau == "a_faire":
                constats.append(
                    Constat(
                        sujet, "attention", f"à faire : limite atteinte, {decrit}", piece.a_faire
                    )
                )
            else:
                constats.append(
                    Constat(sujet, "attention", f"bientôt à faire : {decrit}", piece.a_faire)
                )
        if not constats:
            constats.append(Constat(SUJET, "ok", "aucune pièce proche de sa limite"))
        return constats

    def surveiller(self) -> None:
        """Écrit au journal une alerte quand une pièce passe à « bientôt » puis à « à faire »
        (une seule fois par passage)."""
        for piece in self.etat():
            avant = self._niveaux_vus.get(piece.nom, "ok")
            self._niveaux_vus[piece.nom] = piece.niveau
            if piece.niveau == avant or piece.niveau == "ok":
                continue
            quoi = "À FAIRE" if piece.niveau == "a_faire" else "bientôt à faire"
            journal.warning(
                "Entretien %s : « %s », %g sur %g %s (%g %%)%s. %s",
                quoi,
                piece.description,
                piece.usure,
                piece.limite,
                piece.unite,
                piece.pourcent,
                " (limite d'exemple)" if piece.exemple else "",
                piece.a_faire,
            )

    def demarrer(self, arret: threading.Event) -> threading.Thread:
        return lancer_boucle(
            "surveillance_entretien",
            self.reglages.compteurs.ecriture_periode_s,
            self.surveiller,
            arret,
        )
