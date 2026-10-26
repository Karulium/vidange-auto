"""API du Pi (FastAPI) : état, alarmes, Go, Pause, historique, photos ; et la page web.

    services = Services(chef, registre, acquitter=bilans.acquitter, checklist=checklist.verifier)
    app = creer_app(services, reglages.programme.api, cle)

Toutes les adresses « /api/... » demandent la clé (en-tête « Authorization: Bearer <clé> »).
La page web (« / ») se charge sans clé : elle demande la clé une fois, la garde dans le
téléphone, et l'envoie à chaque appel. Une adresse hors des réseaux autorisés (réseau local,
Tailscale : voir programme.yaml) est refusée d'office, même avec la bonne clé.

Les ordres (Go, Pause, Reprise, acquittement) passent par le chef d'orchestre, comme ceux de
l'écran de l'armoire : l'API ne commande jamais un axe elle-même. Chaque ordre est noté au
journal avec l'adresse d'où il vient. Le pilotage à distance (tâche 12) aura ses propres
garde-fous.
"""

import hmac
import ipaddress
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from vidange import __version__
from vidange.chef import Chef, ErreurChef
from vidange.fiabilite.constats import Constat, pire
from vidange.journal import donner_journal
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

    @app.post("/api/reprendre", dependencies=protege)
    def reprendre(requete: Request) -> dict[str, Any]:
        journal.info("Reprise demandée par la %s", _qui(requete))
        chef.reprendre()
        return {"en_pause": False}

    @app.post("/api/go/{module}", dependencies=protege)
    def go(module: str, requete: Request) -> dict[str, Any]:
        journal.info("Go pour « %s » demandé par la %s", module, _qui(requete))
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

    return app
