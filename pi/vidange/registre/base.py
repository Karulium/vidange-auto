"""Le registre : base SQLite de tout ce que la machine a fait.

    registre = Registre(donnees / "registre.sqlite", donnees / "photos")
    cycle = registre.commencer_cycle("vidange", fut="F3")
    registre.ajouter_seau(cycle, "S1293", bocal="B327")
    registre.noter_mesure("poids_seau", 6.2, "kg", capteur="balance", cycle=cycle, seau="S1293")
    registre.noter_etape(cycle, "descendre", debut, duree_s=12.4)
    registre.noter_photo(donnees / "photos" / "2026-10-26" / "dose.jpg", seau="S1293")
    registre.finir_cycle(cycle)

Les fûts, seaux, bocaux et Pétri sont désignés par le code de leur QR ; un code jamais vu
est ajouté tout seul. Les photos restent en fichiers sur le SSD : la base garde leur chemin.

À l'ouverture : la base est vérifiée, puis montée à la version du programme (voir montees.py),
après une copie de l'ancienne. Une base abîmée, ou plus récente que le programme, empêche
de démarrer avec un message qui dit quoi faire.

Une seule connexion, protégée par un verrou : on peut écrire depuis plusieurs fils (chef, API).
Chaque écriture est sur le disque avant de rendre la main (une coupure ne perd que l'écriture
en cours).
"""

import json
import os
import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from vidange.journal import donner_journal
from vidange.registre.montees import MONTEES, VERSION

journal = donner_journal("registre")

Sorte = Literal["fut", "seau", "bocal", "petri"]
# Sorte d'objet → sa table.
TABLES: dict[str, str] = {"fut": "futs", "seau": "seaux", "bocal": "bocaux", "petri": "petris"}
# Toutes les tables, dans l'ordre où les montrer.
TOUTES_LES_TABLES = (
    "futs",
    "seaux",
    "bocaux",
    "petris",
    "cycles",
    "seaux_du_cycle",
    "etapes_faites",
    "mesures",
    "photos",
    "alarmes",
    "reglages_appliques",
)


class ErreurRegistre(Exception):
    """Base illisible, trop récente, ou écriture refusée."""


def maintenant() -> datetime:
    return datetime.now().astimezone()


def _table(sorte: str) -> str:
    if sorte not in TABLES:
        raise ErreurRegistre(f"sorte d'objet inconnue « {sorte} » (sortes : {', '.join(TABLES)})")
    return TABLES[sorte]


def heure(moment: datetime) -> str:
    """Une heure telle qu'on l'écrit dans la base."""
    if moment.tzinfo is None:
        moment = moment.astimezone()
    return moment.isoformat(timespec="seconds")


class Registre:
    def __init__(
        self,
        chemin: Path,
        dossier_photos: Path,
        horloge: Callable[[], datetime] = maintenant,
    ) -> None:
        self.chemin = chemin
        self.dossier_photos = dossier_photos
        self._horloge = horloge
        self._verrou = threading.RLock()
        chemin.parent.mkdir(parents=True, exist_ok=True)
        dossier_photos.mkdir(parents=True, exist_ok=True)
        try:
            self._cnx = sqlite3.connect(chemin, isolation_level=None, check_same_thread=False)
        except sqlite3.Error as erreur:
            raise ErreurRegistre(
                f"base du registre impossible à ouvrir ({chemin}) : {erreur}"
            ) from None
        try:
            self._preparer()
        except Exception:
            self._cnx.close()
            raise

    # ------------------------------------------------------------ ouverture

    def _preparer(self) -> None:
        cnx = self._cnx
        cnx.row_factory = sqlite3.Row
        try:
            verdict = cnx.execute("PRAGMA quick_check").fetchone()[0]
            # WAL : on peut lire (API, copie de secours) pendant qu'on écrit.
            cnx.execute("PRAGMA journal_mode = WAL")
            # FULL : chaque écriture est sur le disque avant de rendre la main.
            cnx.execute("PRAGMA synchronous = FULL")
            cnx.execute("PRAGMA foreign_keys = ON")
            cnx.execute("PRAGMA busy_timeout = 5000")
        except sqlite3.DatabaseError as erreur:
            raise ErreurRegistre(self._abimee(str(erreur))) from None
        if verdict != "ok":
            raise ErreurRegistre(self._abimee(verdict))
        self._monter()

    def _abimee(self, detail: str) -> str:
        return (
            f"base du registre abîmée ({self.chemin}) : {detail}. Quoi faire : arrêter le "
            "programme, mettre ce fichier de côté et le remplacer par la dernière copie de "
            "secours (dossier « sauvegardes »), renommée « registre.sqlite »."
        )

    @property
    def version(self) -> int:
        return self._cnx.execute("PRAGMA user_version").fetchone()[0]

    def _monter(self) -> None:
        version = self.version
        if version > VERSION:
            raise ErreurRegistre(
                f"la base du registre ({self.chemin}) est en version {version}, plus récente "
                f"que ce programme (version {VERSION} au plus). Quoi faire : remettre le "
                "programme à jour, ou revenir à la copie de la base faite avant la montée."
            )
        if version == VERSION:
            return
        if version > 0:
            copie = self.chemin.with_name(f"{self.chemin.stem}-avant-version-{version + 1}.sqlite")
            self.copier_vers(copie)
            journal.info("Copie de la base avant sa montée de version : %s", copie)
        for numero in range(version + 1, VERSION + 1):
            try:
                with self._ecriture():
                    for instruction in MONTEES[numero - 1]:
                        self._cnx.execute(instruction)
                    self._cnx.execute(f"PRAGMA user_version = {numero}")
            except sqlite3.Error as erreur:
                raise ErreurRegistre(
                    f"montée de la base du registre en version {numero} ratée ({erreur}) ; "
                    f"la base est restée en version {numero - 1}, intacte. Quoi faire : revenir "
                    "à la version d'avant du programme et signaler l'erreur."
                ) from None
            journal.info("Base du registre montée en version %d (%s).", numero, self.chemin)

    def fermer(self) -> None:
        with self._verrou:
            self._cnx.close()

    # ------------------------------------------------------------ outils

    @contextmanager
    def _ecriture(self) -> Iterator[sqlite3.Connection]:
        """Un bloc d'écritures : tout est enregistré, ou rien (en cas d'erreur)."""
        with self._verrou:
            self._cnx.execute("BEGIN IMMEDIATE")
            try:
                yield self._cnx
            except sqlite3.IntegrityError as erreur:
                self._cnx.execute("ROLLBACK")
                raise ErreurRegistre(f"écriture refusée par le registre : {erreur}") from None
            except BaseException:
                self._cnx.execute("ROLLBACK")
                raise
            self._cnx.execute("COMMIT")

    def _quand(self, moment: datetime | None = None) -> str:
        return heure(moment or self._horloge())

    def _id_objet(self, cnx: sqlite3.Connection, sorte: Sorte, code: str | None) -> int | None:
        """L'identifiant d'un objet d'après son code, ajouté s'il n'existait pas."""
        if code is None:
            return None
        table = _table(sorte)
        code = code.strip()
        if not code:
            raise ErreurRegistre(f"code de {sorte} vide")
        ligne = cnx.execute(f"SELECT id FROM {table} WHERE code = ?", (code,)).fetchone()
        if ligne is not None:
            return ligne[0]
        return cnx.execute(
            f"INSERT INTO {table} (code, cree_le) VALUES (?, ?)", (code, self._quand())
        ).lastrowid

    def _objets(
        self, cnx: sqlite3.Connection, codes: dict[Sorte, str | None]
    ) -> dict[str, int | None]:
        """Codes des objets cités → colonnes « fut_id », « seau_id »... d'une ligne."""
        return {f"{sorte}_id": self._id_objet(cnx, sorte, code) for sorte, code in codes.items()}

    def _inserer(self, cnx: sqlite3.Connection, table: str, valeurs: dict[str, Any]) -> int:
        colonnes = ", ".join(valeurs)
        trous = ", ".join("?" for _ in valeurs)
        curseur = cnx.execute(
            f"INSERT INTO {table} ({colonnes}) VALUES ({trous})", tuple(valeurs.values())
        )
        return curseur.lastrowid

    # ------------------------------------------------------------ objets

    def objet(self, sorte: Sorte, code: str, **champs: Any) -> int:
        """Trouve un objet par son code (ou l'ajoute) et met à jour les champs donnés
        (exemple : registre.objet("seau", "S1293", type_seau="opaque_10l"))."""
        with self._ecriture() as cnx:
            ident = self._id_objet(cnx, sorte, code)
            if champs:
                table = TABLES[sorte]
                colonnes = cnx.execute(f"PRAGMA table_info({table})")
                permis = {ligne["name"] for ligne in colonnes} - {"id", "code", "cree_le"}
                inconnus = sorted(set(champs) - permis)
                if inconnus:
                    raise ErreurRegistre(
                        f"champ inconnu pour un {sorte} : {', '.join(inconnus)} "
                        f"(champs : {', '.join(sorted(permis))})"
                    )
                reglage = ", ".join(f"{nom} = ?" for nom in champs)
                cnx.execute(f"UPDATE {table} SET {reglage} WHERE id = ?", (*champs.values(), ident))
            assert ident is not None
            return ident

    def trouver(self, sorte: Sorte, code: str) -> dict[str, Any] | None:
        """La fiche d'un objet d'après son code, ou None s'il n'est pas connu."""
        lignes = self.lire(f"SELECT * FROM {_table(sorte)} WHERE code = ?", (code.strip(),))
        return lignes[0] if lignes else None

    # ------------------------------------------------------------ cycles et étapes

    def commencer_cycle(
        self, module: str, fut: str | None = None, remarque: str | None = None
    ) -> int:
        with self._ecriture() as cnx:
            return self._inserer(
                cnx,
                "cycles",
                {
                    "module": module,
                    "debut": self._quand(),
                    "remarque": remarque,
                    **self._objets(cnx, {"fut": fut}),
                },
            )

    def finir_cycle(self, cycle: int, issue: Literal["termine", "abandonne"] = "termine") -> None:
        with self._ecriture() as cnx:
            curseur = cnx.execute(
                "UPDATE cycles SET fin = ?, issue = ? WHERE id = ? AND fin IS NULL",
                (self._quand(), issue, cycle),
            )
            if curseur.rowcount != 1:
                raise ErreurRegistre(f"cycle n° {cycle} inconnu ou déjà fini")

    def cycles_en_cours(self) -> list[dict[str, Any]]:
        """Les cycles pas encore finis (après une coupure : ceux à reprendre ou à clore)."""
        return self.lire("SELECT * FROM cycles WHERE fin IS NULL ORDER BY id")

    def ajouter_seau(self, cycle: int, seau: str, bocal: str | None = None) -> int:
        """Un seau rempli pendant ce cycle. Si `bocal` est donné, une dose de ce bocal
        (quantité inconnue) est notée aussi ; sinon, utiliser ajouter_dose."""
        with self._ecriture() as cnx:
            seau_du_cycle = self._inserer(
                cnx,
                "seaux_du_cycle",
                {"cycle_id": cycle, "quand": self._quand(), **self._objets(cnx, {"seau": seau})},
            )
            if bocal is not None:
                self._inserer_dose(cnx, seau_du_cycle, bocal, None)
            return seau_du_cycle

    def ajouter_dose(self, seau_du_cycle: int, bocal: str, quantite_g: float | None = None) -> int:
        """Une dose de mycélium versée dans un seau (plusieurs doses et bocaux possibles)."""
        with self._ecriture() as cnx:
            return self._inserer_dose(cnx, seau_du_cycle, bocal, quantite_g)

    def _inserer_dose(
        self, cnx: sqlite3.Connection, seau_du_cycle: int, bocal: str, quantite_g: float | None
    ) -> int:
        return self._inserer(
            cnx,
            "doses_mycelium",
            {
                "seau_du_cycle_id": seau_du_cycle,
                "quantite_g": quantite_g,
                "quand": self._quand(),
                **self._objets(cnx, {"bocal": bocal}),
            },
        )

    def noter_etape(
        self,
        cycle: int,
        etape: str,
        debut: datetime,
        duree_s: float,
        issue: Literal["faite", "alarme", "abandonnee"] = "faite",
        fin: datetime | None = None,
    ) -> int:
        """Une étape faite : début, fin (maintenant par défaut), durée sans les pauses."""
        with self._ecriture() as cnx:
            return self._inserer(
                cnx,
                "etapes_faites",
                {
                    "cycle_id": cycle,
                    "etape": etape,
                    "debut": heure(debut),
                    "fin": self._quand(fin),
                    "duree_s": duree_s,
                    "issue": issue,
                },
            )

    # ------------------------------------------------------------ mesures et photos

    def noter_mesure(
        self,
        nom: str,
        valeur: float,
        unite: str,
        capteur: str | None = None,
        cycle: int | None = None,
        fut: str | None = None,
        seau: str | None = None,
        bocal: str | None = None,
        petri: str | None = None,
        quand: datetime | None = None,
    ) -> int:
        with self._ecriture() as cnx:
            return self._inserer(
                cnx,
                "mesures",
                {
                    "quand": self._quand(quand),
                    "nom": nom,
                    "valeur": valeur,
                    "unite": unite,
                    "capteur": capteur,
                    "cycle_id": cycle,
                    **self._objets(cnx, {"fut": fut, "seau": seau, "bocal": bocal, "petri": petri}),
                },
            )

    def noter_photo(
        self,
        fichier: Path,
        camera: str | None = None,
        remarque: str | None = None,
        cycle: int | None = None,
        fut: str | None = None,
        seau: str | None = None,
        bocal: str | None = None,
        petri: str | None = None,
        quand: datetime | None = None,
    ) -> int:
        """Note une photo déjà enregistrée dans le dossier des photos (la base garde son chemin)."""
        fichier = Path(fichier).resolve()
        try:
            chemin = fichier.relative_to(self.dossier_photos.resolve())
        except ValueError:
            raise ErreurRegistre(
                f"photo hors du dossier des photos ({self.dossier_photos}) : {fichier}"
            ) from None
        if not fichier.is_file():
            raise ErreurRegistre(f"photo introuvable : {fichier}")
        with self._ecriture() as cnx:
            return self._inserer(
                cnx,
                "photos",
                {
                    "quand": self._quand(quand),
                    "chemin": chemin.as_posix(),
                    "camera": camera,
                    "remarque": remarque,
                    "cycle_id": cycle,
                    **self._objets(cnx, {"fut": fut, "seau": seau, "bocal": bocal, "petri": petri}),
                },
            )

    def chemin_photo(self, photo: int) -> Path:
        """Le fichier d'une photo notée."""
        lignes = self.lire("SELECT chemin FROM photos WHERE id = ?", (photo,))
        if not lignes:
            raise ErreurRegistre(f"photo n° {photo} inconnue")
        return self.dossier_photos / lignes[0]["chemin"]

    # ------------------------------------------------------------ alarmes et réglages

    def noter_alarme(
        self,
        module: str,
        message: str,
        quoi_faire: str | None = None,
        etape: str | None = None,
        cycle: int | None = None,
        bilan: str | None = None,
    ) -> int:
        """`bilan` : chemin du fichier de bilan de l'alarme, relatif au dossier des données."""
        with self._ecriture() as cnx:
            return self._inserer(
                cnx,
                "alarmes",
                {
                    "quand": self._quand(),
                    "module": module,
                    "etape": etape,
                    "message": message,
                    "quoi_faire": quoi_faire,
                    "cycle_id": cycle,
                    "bilan": bilan,
                },
            )

    def alarmes_ouvertes(self) -> list[dict[str, Any]]:
        """Les alarmes pas encore acquittées, de la plus vieille à la plus récente."""
        return self.lire("SELECT * FROM alarmes WHERE acquittee_le IS NULL ORDER BY id")

    def acquitter_alarme(self, alarme: int, qui: str) -> None:
        with self._ecriture() as cnx:
            curseur = cnx.execute(
                "UPDATE alarmes SET acquittee_le = ?, acquittee_par = ? "
                "WHERE id = ? AND acquittee_le IS NULL",
                (self._quand(), qui, alarme),
            )
            if curseur.rowcount != 1:
                raise ErreurRegistre(f"alarme n° {alarme} inconnue ou déjà acquittée")

    def noter_reglage(
        self,
        qui: str,
        fichier: str,
        reglage: str,
        ancien: Any,
        nouveau: Any,
        raison: str | None = None,
    ) -> int:
        """Un réglage changé (exemple : fichier « machine.yaml », réglage « durees.vidange_max »).
        Les valeurs sont gardées en JSON ; None = le réglage n'existait pas (ou plus)."""

        def en_json(valeur: Any) -> str | None:
            return None if valeur is None else json.dumps(valeur, ensure_ascii=False)

        with self._ecriture() as cnx:
            return self._inserer(
                cnx,
                "reglages_appliques",
                {
                    "quand": self._quand(),
                    "qui": qui,
                    "fichier": fichier,
                    "reglage": reglage,
                    "ancien": en_json(ancien),
                    "nouveau": en_json(nouveau),
                    "raison": raison,
                },
            )

    # ------------------------------------------------------------ lecture et copie

    def lire(self, requete: str, valeurs: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        """Lignes d'une requête SELECT, chacune en dictionnaire (pour les écrans, l'API...)."""
        with self._verrou:
            return [dict(ligne) for ligne in self._cnx.execute(requete, valeurs).fetchall()]

    def compter(self) -> dict[str, int]:
        """Nombre de lignes de chaque table."""
        with self._verrou:
            return {
                table: self._cnx.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in TOUTES_LES_TABLES
            }

    def copier_vers(self, cible: Path) -> None:
        """Copie complète et cohérente de la base, même pendant que la machine écrit.

        La copie est vérifiée, puis mise à sa place d'un seul coup : il n'existe jamais
        de copie à moitié écrite sous le nom final.
        """
        cible.parent.mkdir(parents=True, exist_ok=True)
        provisoire = cible.with_name(cible.name + ".nouveau")
        provisoire.unlink(missing_ok=True)
        copie = sqlite3.connect(provisoire, isolation_level=None)
        try:
            with self._verrou:
                self._cnx.backup(copie)
            # La copie est un seul fichier, lisible sans rien à côté.
            copie.execute("PRAGMA journal_mode = DELETE")
            verdict = copie.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            copie.close()
        if verdict != "ok":
            provisoire.unlink(missing_ok=True)
            raise ErreurRegistre(f"copie de la base ratée ({cible}) : {verdict}")
        with provisoire.open("rb") as fichier:
            os.fsync(fichier.fileno())
        os.replace(provisoire, cible)
        dossier = os.open(cible.parent, os.O_RDONLY)
        try:
            os.fsync(dossier)
        finally:
            os.close(dossier)
