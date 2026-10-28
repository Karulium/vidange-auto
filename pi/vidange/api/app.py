"""API du Pi (FastAPI) : état, alarmes, Go, Pause, historique, photos, vidéos, pilotage à
distance ; et la page web.

    services = Services(chef, registre, acquitter=bilans.acquitter, checklist=checklist.verifier,
                        cameras=cameras, pilote=pilote)
    app = creer_app(services, reglages.programme.api, cle)

Toutes les adresses « /api/... » demandent la clé (en-tête « Authorization: Bearer <clé> »).
La page web (« / ») se charge sans clé : elle demande la clé une fois, la garde dans le
téléphone, et l'envoie à chaque appel. Une adresse hors des réseaux autorisés (réseau local,
Tailscale : voir programme.yaml) est refusée d'office, même avec la bonne clé.

Les ordres (Go, Pause, Reprise, acquittement) passent par le chef d'orchestre, comme ceux de
l'écran de l'armoire : l'API ne commande jamais un axe elle-même. Chaque ordre est noté au
journal avec l'adresse d'où il vient. Le pilotage à distance (tâche 12) passe par le pilote
(vidange/distance), qui a ses propres garde-fous ; pendant ce pilotage, Go et Reprise sont
refusés. Les mises à jour (tâche 13) passent par MisesAJour (vidange/mises_a_jour) : seulement
machine à l'arrêt ; pendant une mise à jour, Go, Reprise et pilotage à distance sont refusés.
"""

import hmac
import ipaddress
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pydantic import BaseModel

from vidange import __version__
from vidange.cameras import Cameras, ErreurCamera
from vidange.chef import Chef, ErreurChef
from vidange.distance import ErreurDistance, PiloteDistance
from vidange.fiabilite.constats import Constat, pire
from vidange.journal import donner_journal
from vidange.mises_a_jour import ErreurMiseAJour, MisesAJour
from vidange.registre import ErreurRegistre, Registre
from vidange.reglages import ReglagesApi

journal = donner_journal("api")

PAGE = Path(__file__).resolve().parent / "page" / "index.html"


@dataclass
class Services:
    """Ce que l'API montre et commande (les vrais morceaux du programme, ou ceux d'un test)."""

    chef: Chef
    registre: Registre
    # Acquitte une alarme du registre par son numéro, et le module du chef s'il est en alarme
    # (Bilans.acquitter) : (numéro, qui).
    acquitter: Callable[[int, str], None]
    # La check-list de démarrage, refaite à la demande (CheckList.verifier).
    checklist: Callable[[], Iterable[Constat]]
    # Vidéos et clips (None : pas de caméras), pilotage à distance (None : pas de pilote).
    cameras: Cameras | None = None
    pilote: PiloteDistance | None = None
    # Mises à jour des cartes et du Pi (None : pas de mises à jour).
    mises_a_jour: MisesAJour | None = None


class Tenir(BaseModel):
    """« Je tiens le bouton » : l'axe, le sens, et l'image que la page affiche en ce moment."""

    axe: str
    sens: int
    camera: str
    image: int


class ChoixProgramme(BaseModel):
    """Le fichier de programme (déjà envoyé au Pi) à écrire dans une carte."""

    fichier: str


class ChoixCopie(BaseModel):
    """La copie de la mémoire à remettre (None : la plus récente)."""

    copie: str | None = None


def _adresse(requete: Request) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    if requete.client is None:
        return None
    try:
        adresse = ipaddress.ip_address(requete.client.host)
    except ValueError:
        return None
    # Une adresse IPv4 vue par une prise IPv6 (« ::ffff:192.168.1.20 ») : on prend l'IPv4.
    if isinstance(adresse, ipaddress.IPv6Address) and adresse.ipv4_mapped is not None:
        return adresse.ipv4_mapped
    return adresse


def _qui(requete: Request) -> str:
    return f"page web ({requete.client.host if requete.client else 'adresse inconnue'})"


def creer_app(services: Services, reglages: ReglagesApi, cle: str) -> FastAPI:
    """L'application web. `cle` : la clé du fichier de secrets (jamais vide)."""
    if not cle:
        raise ValueError("l'API ne démarre pas sans clé")
    # Pas de pages de documentation automatiques : elles montreraient l'API sans clé.
    app = FastAPI(title="Vidange automatique", docs_url=None, redoc_url=None, openapi_url=None)
    chef, registre = services.chef, services.registre
    cameras, pilote = services.cameras, services.pilote
    mises_a_jour = services.mises_a_jour
    reseaux = list(reglages.reseaux_autorises)
    cle_attendue = cle.encode()

    def limiter(limite: int | None) -> int:
        return min(limite or reglages.lignes_max, reglages.lignes_max)

    # ------------------------------------------------------------ garde-fous

    @app.middleware("http")
    async def filtrer_reseaux(requete: Request, suite):
        adresse = _adresse(requete)
        if adresse is None or not any(adresse in reseau for reseau in reseaux):
            journal.warning("Accès refusé : adresse hors des réseaux autorisés (%s)", adresse)
            return JSONResponse(
                {"detail": "adresse hors des réseaux autorisés (programme.yaml → api)"},
                status_code=403,
            )
        return await suite(requete)

    def verifier_cle(requete: Request) -> None:
        entete = requete.headers.get("authorization", "")
        sorte, _, donnee = entete.partition(" ")
        if sorte.lower() != "bearer" or not hmac.compare_digest(donnee.encode(), cle_attendue):
            journal.warning("Clé de l'API absente ou fausse (%s)", _qui(requete))
            raise HTTPException(401, "clé de l'API absente ou fausse")

    @app.exception_handler(ErreurChef)
    @app.exception_handler(ErreurRegistre)
    @app.exception_handler(ErreurDistance)
    @app.exception_handler(ErreurMiseAJour)
    async def refus(_: Request, erreur: Exception) -> JSONResponse:
        # Un ordre impossible maintenant (pas de Go attendu, alarme déjà acquittée...).
        return JSONResponse({"detail": str(erreur)}, status_code=409)

    protege = [Depends(verifier_cle)]

    # ------------------------------------------------------------ la page web

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def page() -> HTMLResponse:
        return HTMLResponse(PAGE.read_text(encoding="utf-8"))

    # ------------------------------------------------------------ état et check-list

    @app.get("/api/etat", dependencies=protege)
    def etat() -> dict[str, Any]:
        etat_chef = chef.etat()
        return {
            "heure": datetime.now().astimezone().isoformat(timespec="seconds"),
            "version": __version__,
            "en_pause": etat_chef.en_pause,
            "modules": [asdict(module) for module in etat_chef.modules],
            "attendent_go": etat_chef.attendent_go,
            "alarmes_ouvertes": registre.alarmes_ouvertes(),
            "rafraichir_s": reglages.rafraichir_s,
            "distance": pilote is not None and pilote.actif,
            "mise_a_jour": mises_a_jour is not None and mises_a_jour.en_cours,
        }

    @app.get("/api/checklist", dependencies=protege)
    def checklist() -> dict[str, Any]:
        constats = list(services.checklist())
        return {
            "prete": pire(constats) != "bloquant",
            "niveau": pire(constats),
            "constats": [asdict(constat) for constat in constats],
        }

    # ------------------------------------------------------------ ordres

    @app.post("/api/pause", dependencies=protege)
    def pause(requete: Request) -> dict[str, Any]:
        journal.warning("Pause demandée par la %s", _qui(requete))
        chef.pause()
        return {"en_pause": True}

    def pas_pendant_le_pilotage(ordre: str) -> None:
        if pilote is not None and pilote.actif:
            raise ErreurDistance(f"{ordre} refusé : quitter d'abord le pilotage à distance")
        pas_pendant_la_mise_a_jour(ordre)

    def pas_pendant_la_mise_a_jour(ordre: str) -> None:
        if mises_a_jour is not None and mises_a_jour.en_cours:
            raise ErreurMiseAJour(f"{ordre} refusé : une mise à jour est en cours")

    @app.post("/api/reprendre", dependencies=protege)
    def reprendre(requete: Request) -> dict[str, Any]:
        journal.info("Reprise demandée par la %s", _qui(requete))
        pas_pendant_le_pilotage("Reprise")
        chef.reprendre()
        return {"en_pause": False}

    @app.post("/api/go/{module}", dependencies=protege)
    def go(module: str, requete: Request) -> dict[str, Any]:
        journal.info("Go pour « %s » demandé par la %s", module, _qui(requete))
        pas_pendant_le_pilotage("Go")
        chef.donner_go(module)
        return {"go": module}

    # ------------------------------------------------------------ alarmes

    @app.get("/api/alarmes", dependencies=protege)
    def alarmes(
        toutes: bool = False,
        limite: int | None = Query(default=None, ge=1),
        avant: int | None = Query(default=None, ge=1),
    ) -> list[dict[str, Any]]:
        """Les alarmes ouvertes ; avec « toutes », les dernières (même acquittées)."""
        if not toutes:
            return registre.alarmes_ouvertes()
        return registre.lire(
            "SELECT * FROM alarmes WHERE (? IS NULL OR id < ?) ORDER BY id DESC LIMIT ?",
            (avant, avant, limiter(limite)),
        )

    @app.post("/api/alarmes/{numero}/acquitter", dependencies=protege)
    def acquitter(numero: int, requete: Request) -> dict[str, Any]:
        journal.info("Alarme n° %d acquittée par la %s", numero, _qui(requete))
        services.acquitter(numero, _qui(requete))
        return {"acquittee": numero}

    # ------------------------------------------------------------ historique

    @app.get("/api/historique", dependencies=protege)
    def historique(
        limite: int | None = Query(default=None, ge=1),
        avant: int | None = Query(default=None, ge=1),
    ) -> list[dict[str, Any]]:
        """Les derniers cycles, du plus récent au plus ancien (« avant » : page suivante)."""
        return registre.lire(
            "SELECT c.*, f.code AS fut, "
            "(SELECT COUNT(*) FROM seaux_du_cycle s WHERE s.cycle_id = c.id) AS nombre_seaux "
            "FROM cycles c LEFT JOIN futs f ON f.id = c.fut_id "
            "WHERE (? IS NULL OR c.id < ?) ORDER BY c.id DESC LIMIT ?",
            (avant, avant, limiter(limite)),
        )

    @app.get("/api/historique/{cycle}", dependencies=protege)
    def detail_cycle(cycle: int) -> dict[str, Any]:
        """Tout ce que le registre sait d'un cycle."""
        lignes = registre.lire(
            "SELECT c.*, f.code AS fut FROM cycles c LEFT JOIN futs f ON f.id = c.fut_id "
            "WHERE c.id = ?",
            (cycle,),
        )
        if not lignes:
            raise HTTPException(404, f"cycle n° {cycle} inconnu")
        seaux = registre.lire(
            "SELECT sc.id, s.code AS seau, s.type_seau, sc.quand FROM seaux_du_cycle sc "
            "JOIN seaux s ON s.id = sc.seau_id WHERE sc.cycle_id = ? ORDER BY sc.id",
            (cycle,),
        )
        doses = registre.lire(
            "SELECT d.seau_du_cycle_id, b.code AS bocal, d.quantite_g, d.quand "
            "FROM doses_mycelium d JOIN bocaux b ON b.id = d.bocal_id "
            "JOIN seaux_du_cycle sc ON sc.id = d.seau_du_cycle_id "
            "WHERE sc.cycle_id = ? ORDER BY d.id",
            (cycle,),
        )
        for seau in seaux:
            seau["doses"] = [
                {cle: valeur for cle, valeur in dose.items() if cle != "seau_du_cycle_id"}
                for dose in doses
                if dose["seau_du_cycle_id"] == seau["id"]
            ]
        return {
            **lignes[0],
            "seaux": seaux,
            "etapes": registre.lire(
                "SELECT etape, debut, fin, duree_s, issue FROM etapes_faites "
                "WHERE cycle_id = ? ORDER BY id",
                (cycle,),
            ),
            "mesures": registre.lire(
                "SELECT m.quand, m.nom, m.valeur, m.unite, m.capteur, s.code AS seau "
                "FROM mesures m LEFT JOIN seaux s ON s.id = m.seau_id "
                "WHERE m.cycle_id = ? ORDER BY m.id LIMIT ?",
                (cycle, reglages.lignes_max),
            ),
            "photos": lire_photos(cycle=cycle),
            "alarmes": registre.lire(
                "SELECT * FROM alarmes WHERE cycle_id = ? ORDER BY id", (cycle,)
            ),
        }

    # ------------------------------------------------------------ photos

    def lire_photos(
        cycle: int | None = None,
        seau: str | None = None,
        limite: int | None = None,
        avant: int | None = None,
    ) -> list[dict[str, Any]]:
        return registre.lire(
            "SELECT p.id, p.quand, p.camera, p.remarque, p.cycle_id, f.code AS fut, "
            "s.code AS seau, b.code AS bocal FROM photos p "
            "LEFT JOIN futs f ON f.id = p.fut_id LEFT JOIN seaux s ON s.id = p.seau_id "
            "LEFT JOIN bocaux b ON b.id = p.bocal_id "
            "WHERE (? IS NULL OR p.cycle_id = ?) AND (? IS NULL OR s.code = ?) "
            "AND (? IS NULL OR p.id < ?) ORDER BY p.id DESC LIMIT ?",
            (cycle, cycle, seau, seau, avant, avant, limiter(limite)),
        )

    @app.get("/api/photos", dependencies=protege)
    def photos(
        cycle: int | None = None,
        seau: str | None = None,
        limite: int | None = Query(default=None, ge=1),
        avant: int | None = Query(default=None, ge=1),
    ) -> list[dict[str, Any]]:
        """Les dernières photos (d'un cycle, d'un seau), de la plus récente à la plus ancienne."""
        return lire_photos(cycle, seau, limite, avant)

    @app.get("/api/photos/{numero}", dependencies=protege)
    def photo(numero: int) -> FileResponse:
        """Le fichier de la photo (il reste sur le SSD, la base ne garde que son chemin)."""
        try:
            fichier = registre.chemin_photo(numero).resolve()
        except ErreurRegistre as erreur:
            raise HTTPException(404, str(erreur)) from None
        # Un chemin abîmé dans la base ne doit jamais faire sortir du dossier des photos.
        if not fichier.is_relative_to(registre.dossier_photos.resolve()) or not fichier.is_file():
            raise HTTPException(404, f"fichier de la photo n° {numero} introuvable")
        return FileResponse(fichier)

    # ------------------------------------------------------------ vidéos et clips

    def les_cameras() -> Cameras:
        if cameras is None:
            raise HTTPException(404, "pas de caméras (programme.yaml → cameras)")
        return cameras

    def jpeg(donnees: bytes, entetes: dict[str, str] | None = None) -> Response:
        return Response(
            donnees,
            media_type="image/jpeg",
            headers={"Cache-Control": "no-store", **(entetes or {})},
        )

    @app.get("/api/cameras", dependencies=protege)
    def liste_cameras() -> dict[str, Any]:
        if cameras is None:
            return {"cameras": [], "images_par_s": 0}
        return {"cameras": cameras.decrire(), "images_par_s": cameras.reglages.page_images_par_s}

    @app.get("/api/cameras/{nom}/image", dependencies=protege)
    def image_camera(nom: str) -> Response:
        """La dernière image ; son numéro est dans l'en-tête « X-Image » (pilotage à distance)."""
        try:
            image = les_cameras().derniere(nom)
        except ErreurCamera as erreur:
            raise HTTPException(404, str(erreur)) from None
        if image is None:
            raise HTTPException(503, f"caméra « {nom} » : pas encore d'image")
        return jpeg(image.donnees, {"X-Image": str(image.numero)})

    @app.get("/api/clips", dependencies=protege)
    def clips(
        limite: int | None = Query(default=None, ge=1), avant: str | None = None
    ) -> list[dict[str, Any]]:
        """Les clips des alarmes, du plus récent au plus ancien."""
        return les_cameras().lister_clips(limiter(limite), avant)

    @app.get("/api/clips/{clip}/{camera}", dependencies=protege)
    def index_clip(clip: str, camera: str) -> dict[str, Any]:
        try:
            index = les_cameras().index_du_clip(clip, camera)
        except ErreurCamera as erreur:
            raise HTTPException(404, str(erreur)) from None
        return {"clip": clip, "camera": camera, "heures": [heure for *_, heure in index]}

    @app.get("/api/clips/{clip}/{camera}/{rang}", dependencies=protege)
    def image_clip(clip: str, camera: str, rang: int) -> Response:
        try:
            return jpeg(les_cameras().image_du_clip(clip, camera, rang))
        except ErreurCamera as erreur:
            raise HTTPException(404, str(erreur)) from None

    # ------------------------------------------------------------ pilotage à distance

    def le_pilote() -> PiloteDistance:
        if pilote is None:
            raise HTTPException(404, "pas de pilotage à distance sur ce programme")
        return pilote

    @app.get("/api/distance", dependencies=protege)
    def distance() -> dict[str, Any]:
        return le_pilote().etat()

    @app.post("/api/distance/activer", dependencies=protege)
    def activer(requete: Request) -> dict[str, Any]:
        pas_pendant_la_mise_a_jour("Pilotage à distance")
        le_pilote().activer(_qui(requete))
        return le_pilote().etat()

    @app.post("/api/distance/quitter", dependencies=protege)
    def quitter(requete: Request) -> dict[str, Any]:
        le_pilote().quitter(_qui(requete))
        return le_pilote().etat()

    @app.post("/api/distance/tenir", dependencies=protege)
    def tenir(ordre: Tenir, requete: Request) -> dict[str, Any]:
        le_pilote().tenir(_qui(requete), ordre.axe, ordre.sens, ordre.camera, ordre.image)
        return le_pilote().etat()

    @app.post("/api/distance/lacher", dependencies=protege)
    def lacher(requete: Request) -> dict[str, Any]:
        le_pilote().lacher(_qui(requete))
        return le_pilote().etat()

    @app.get("/api/distance/journal", dependencies=protege)
    def journal_distance(
        limite: int | None = Query(default=None, ge=1),
        avant: int | None = Query(default=None, ge=1),
    ) -> list[dict[str, Any]]:
        """Les dernières actions du pilotage à distance (qui, quand, quoi)."""
        return registre.lire(
            "SELECT * FROM actions_distance WHERE (? IS NULL OR id < ?) ORDER BY id DESC LIMIT ?",
            (avant, avant, limiter(limite)),
        )

    # ------------------------------------------------------------ mises à jour

    def les_mises_a_jour() -> MisesAJour:
        if mises_a_jour is None:
            raise HTTPException(404, "pas de mises à jour sur ce programme")
        return mises_a_jour

    @app.get("/api/mises-a-jour", dependencies=protege)
    def etat_mises_a_jour() -> dict[str, Any]:
        return les_mises_a_jour().etat()

    @app.post("/api/mises-a-jour/programmes", dependencies=protege)
    async def recevoir_programme(nom: str, requete: Request) -> dict[str, Any]:
        """Un fichier de programme (.bin) envoyé tel quel dans le corps de la requête."""
        maj = les_mises_a_jour()
        taille_max = int(maj.reglages.cartes.taille_max_mo * 1024 * 1024)
        annoncee = requete.headers.get("content-length", "")
        if annoncee.isdigit() and int(annoncee) > taille_max:
            raise HTTPException(413, f"fichier trop gros (plus de {taille_max} octets)")
        contenu = await requete.body()
        journal.info("Programme « %s » envoyé par la %s", nom, _qui(requete))
        return maj.recevoir_programme(nom, contenu)

    @app.post("/api/mises-a-jour/cartes/{carte}/programme", dependencies=protege)
    def programme_carte(carte: str, choix: ChoixProgramme, requete: Request) -> dict[str, Any]:
        les_mises_a_jour().ecrire_programme(carte, choix.fichier, _qui(requete))
        return les_mises_a_jour().etat()

    @app.post("/api/mises-a-jour/cartes/{carte}/reglages", dependencies=protege)
    def reglages_carte(carte: str, requete: Request) -> dict[str, Any]:
        les_mises_a_jour().envoyer_reglages(carte, _qui(requete))
        return les_mises_a_jour().etat()

    @app.post("/api/mises-a-jour/cartes/{carte}/revenir", dependencies=protege)
    def revenir_carte(carte: str, choix: ChoixCopie, requete: Request) -> dict[str, Any]:
        les_mises_a_jour().revenir_carte(carte, choix.copie, _qui(requete))
        return les_mises_a_jour().etat()

    @app.post("/api/mises-a-jour/pi/chercher", dependencies=protege)
    def chercher_pi(requete: Request) -> dict[str, Any]:
        les_mises_a_jour().chercher_pi(_qui(requete))
        return les_mises_a_jour().etat()

    @app.post("/api/mises-a-jour/pi/installer", dependencies=protege)
    def installer_pi(requete: Request) -> dict[str, Any]:
        les_mises_a_jour().installer_pi(_qui(requete))
        return les_mises_a_jour().etat()

    @app.post("/api/mises-a-jour/pi/revenir", dependencies=protege)
    def revenir_pi(requete: Request) -> dict[str, Any]:
        les_mises_a_jour().revenir_pi(_qui(requete))
        return les_mises_a_jour().etat()

    return app
