"""API du Pi (FastAPI) : état, alarmes, Go, Pause, historique, photos, vidéos, pilotage à
distance ; et la page web.

    services = Services(chef, registre, acquitter=bilans.acquitter, checklist=checklist.verifier,
                        cameras=cameras, pilote=pilote)
    app = creer_app(services, reglages.programme.api, comptes, actions)

Comptes (tâche 25) : chaque personne a un nom et un mot de passe (vidange/comptes), un rôle
(karulium, employe, visiteur), et se connecte une fois (POST /api/connexion) : un cookie signé
suit. CHAQUE route de l'API déclare le niveau minimum qu'elle demande : regarder (visiteur et
plus), produire (employé et plus : Go, lots, boutons de production), régler (karulium :
mises à jour, pilotage à distance, journal des actions). Une route sans niveau empêche le
démarrage (`verifier_roles_declares`). Les actions « produire » et « régler » sont notées au journal
des actions (qui, quand, quoi). Sans aucun compte, tout est refusé sauf la page qui explique comment
créer le premier. Une adresse hors des réseaux autorisés (réseau local, Tailscale : voir
programme.yaml) est refusée d'office, même avec le bon mot de passe.

Les ordres (Go, Pause, Reprise, acquittement) passent par le chef d'orchestre, comme ceux de
l'écran de l'armoire : l'API ne commande jamais un axe elle-même. Chaque ordre est noté au
journal avec l'adresse d'où il vient. Le pilotage à distance (tâche 12) passe par le pilote
(vidange/distance), qui a ses propres garde-fous ; pendant ce pilotage, Go et Reprise sont
refusés. Les mises à jour (tâche 13) passent par MisesAJour (vidange/mises_a_jour) : seulement
machine à l'arrêt ; pendant une mise à jour, Go, Reprise et pilotage à distance sont refusés.
Le Nettoyage (tâche 38) : état de l'enceinte, « ouvrir le store » (verrous seulement, jamais son
moteur), fermeture, éclairage, passer outre la purge, nuit UV-ozone.
Les lots (tâche 45 quater) : « Lot de seaux » (format, nombre, variété) et « Lot de bocaux »
(nombre) ne font que PROPOSER le lot (vidange.cycle.lancement) ; il part au Go donné sur l'écran
de l'armoire, devant la machine. L'API n'a pas de Go pour un lot.
"""

import hashlib
import ipaddress
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pydantic import BaseModel

from vidange import __version__
from vidange.air import Air
from vidange.api.acces import (
    COOKIE,
    Exige,
    JournalActions,
    LimiteConnexions,
    mot_du_niveau,
    verifier_roles_declares,
)
from vidange.cameras import Cameras, ErreurCamera
from vidange.chef import Chef, ErreurChef
from vidange.comptes import Comptes, Niveau
from vidange.distance import ErreurDistance, PiloteDistance
from vidange.entretien import Entretien, ErreurEntretien
from vidange.fiabilite.constats import Constat, pire
from vidange.journal import donner_journal
from vidange.mises_a_jour import ErreurMiseAJour, MisesAJour
from vidange.modifiables import ErreurModifiable, Modifiables
from vidange.nettoyage import ErreurNettoyage, Nettoyage
from vidange.poste_fut import ErreurPoste, PosteFut
from vidange.registre import ErreurRegistre, Registre
from vidange.reglages import ReglagesApi, ReglagesCarnet
from vidange.spray import Spray
from vidange.statistiques.calcul import ECHELLES, Statistiques
from vidange.vue3d import EnregistreurRejeu, ErreurRejeu, Vue3d

if TYPE_CHECKING:
    from vidange.cycle.lancement import Lancement
    from vidange.stockage.correction import Correction

journal = donner_journal("api")

PAGE = Path(__file__).resolve().parent / "page" / "index.html"
PAGE_AUCUN_COMPTE = Path(__file__).resolve().parent / "page" / "aucun-compte.html"
# Les fichiers fixes de la page (bibliothèque 3D copiée dans le dépôt, code de la vue 3D).
STATIQUE = Path(__file__).resolve().parent / "page" / "statique"
# L'appli installable (tâche 28 bis) : manifeste, service worker (modèle), icônes.
DOSSIER_PAGE = PAGE.parent
MANIFESTE = DOSSIER_PAGE / "manifeste.webmanifest"
SERVICE_WORKER = DOSSIER_PAGE / "sw.js"
ICONES = DOSSIER_PAGE / "icones"
# En-tête posé sur la vraie page : le service worker ne garde que celle-là (pas la page qui
# explique comment créer le premier compte).
MARQUE_COQUILLE = "X-Vidange-Coquille"


def version_coquille(dossier: Path = DOSSIER_PAGE) -> str:
    """Le numéro de version du cache du service worker : une empreinte du contenu de TOUS les
    fichiers de la page (page, manifeste, code, icônes, version du programme). Il change dès
    qu'un de ces fichiers change : le vieux cache est alors effacé, jamais une vieille page."""
    empreinte = hashlib.sha256(__version__.encode())
    fichiers = [dossier / "index.html", dossier / "manifeste.webmanifest", dossier / "sw.js"]
    fichiers += sorted((dossier / "statique").glob("*.js")) + sorted((dossier / "icones").glob("*"))
    for fichier in fichiers:
        if fichier.is_file():
            empreinte.update(fichier.relative_to(dossier).as_posix().encode())
            empreinte.update(fichier.read_bytes())
    return empreinte.hexdigest()[:12]


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
    # Poste du fût (None : pas de poste du fût).
    poste: PosteFut | None = None
    # Nettoyage : store, purge, nuit UV-ozone (None : pas de nettoyage).
    nettoyage: Nettoyage | None = None
    # Spray : carte n° 5, flacons, bras (None : pas de spray).
    spray: Spray | None = None
    # Air comprimé : compresseur, mise en pression, bidon de purge (None : pas d'air).
    air: Air | None = None
    # Entretien : compteurs, pièces d'usure, calendrier (None : pas d'entretien).
    entretien: Entretien | None = None
    # Lancer un lot : la page web propose, Go à l'écran (None : pas de lot possible).
    lancement: "Lancement | None" = None
    # Corriger l'inventaire du stockage : la page propose, Karulium confirme (None : pas possible).
    correction: "Correction | None" = None
    # Vue 3D en direct et rejeu d'incident (None : pas de vue 3D).
    vue3d: Vue3d | None = None
    rejeux: EnregistreurRejeu | None = None
    # Statistiques d'après le registre (None : pas de statistiques).
    statistiques: Statistiques | None = None
    # Réglages que la page a le droit de changer, avec garde-fous (None : aucun).
    modifiables: Modifiables | None = None
    # Réglages du carnet de bord (longueur d'une note, notes par page ; None : sans limite propre).
    carnet: ReglagesCarnet | None = None


class Tenir(BaseModel):
    """« Je tiens le bouton » : l'axe, le sens, et l'image que la page affiche en ce moment."""

    axe: str
    sens: int
    camera: str
    image: int


class ChoixProgramme(BaseModel):
    """Le fichier de programme (déjà envoyé au Pi) à écrire dans une carte."""

    fichier: str


class LotDeSeaux(BaseModel):
    """Le bouton « Lot de seaux » : format, nombre de seaux, variété de la semence."""

    format: str
    nombre: int
    variete: str


class LotDeBocaux(BaseModel):
    """Le bouton « Lot de bocaux » : nombre de bocaux vides."""

    nombre: int


class CorrectionStockage(BaseModel):
    """Une correction de l'inventaire : la place, son contenu (variété ou format) et le nombre."""

    place: str
    contenu: str | None = None
    nombre: int = 0


class Connexion(BaseModel):
    """Le formulaire de connexion de la page."""

    nom: str
    mot_de_passe: str


class NouvelleNote(BaseModel):
    """Une note du carnet de bord : le texte, et ce à quoi elle se rattache (si on veut)."""

    texte: str
    cycle: int | None = None
    seau: str | None = None
    alarme: int | None = None


class RaisonBarree(BaseModel):
    """Pourquoi une note du carnet est barrée."""

    raison: str


class NouvelleValeur(BaseModel):
    """La nouvelle valeur d'un réglage modifiable (nombre, ou « HH:MM » pour une heure)."""

    valeur: float | int | str


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
    """Pour le journal et le registre : la personne connectée et d'où elle vient."""
    adresse = requete.client.host if requete.client else "adresse inconnue"
    compte = getattr(requete.state, "compte", None)
    if compte is None:
        return f"page web ({adresse})"
    return f"page web ({compte.nom}, {adresse})"


def creer_app(
    services: Services, reglages: ReglagesApi, comptes: Comptes, actions: JournalActions
) -> FastAPI:
    """L'application web. `comptes` : le fichier des comptes (qui peut être vide : la page
    explique alors comment créer le premier compte). `actions` : le journal « qui a fait quoi »."""
    # Pas de pages de documentation automatiques : elles montreraient l'API sans clé.
    app = FastAPI(title="Vidange automatique", docs_url=None, redoc_url=None, openapi_url=None)
    chef, registre = services.chef, services.registre
    cameras, pilote = services.cameras, services.pilote
    mises_a_jour = services.mises_a_jour
    reseaux = list(reglages.reseaux_autorises)
    reglages_carnet = services.carnet
    page_carnet = reglages.lignes_max if reglages_carnet is None else reglages_carnet.notes_par_page
    texte_carnet_max = None if reglages_carnet is None else reglages_carnet.texte_max
    limite = LimiteConnexions(reglages.connexions_ratees_max, reglages.blocage_s)

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

    @app.exception_handler(ErreurChef)
    @app.exception_handler(ErreurRegistre)
    @app.exception_handler(ErreurDistance)
    @app.exception_handler(ErreurMiseAJour)
    @app.exception_handler(ErreurPoste)
    @app.exception_handler(ErreurNettoyage)
    @app.exception_handler(ErreurEntretien)
    async def refus(_: Request, erreur: Exception) -> JSONResponse:
        # Un ordre impossible maintenant (pas de Go attendu, alarme déjà acquittée...).
        return JSONResponse({"detail": str(erreur)}, status_code=409)

    @app.exception_handler(ErreurModifiable)
    async def refus_reglage(_: Request, erreur: ErreurModifiable) -> JSONResponse:
        return JSONResponse({"detail": str(erreur)}, status_code=erreur.statut)

    regarder = [Depends(Exige(Niveau.REGARDER, comptes, actions))]
    produire = [Depends(Exige(Niveau.PRODUIRE, comptes, actions))]
    regler = [Depends(Exige(Niveau.REGLER, comptes, actions))]
    # Le pilotage à distance envoie « je tiens le bouton » plusieurs fois par seconde : le
    # journal du pilote (vidange/distance) le note déjà : pas la peine de noyer celui des actions.
    regler_sans_trace = [Depends(Exige(Niveau.REGLER, comptes, actions, journaliser=False))]

    # ------------------------------------------------------------ la page web

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def page() -> HTMLResponse:
        # Sans aucun compte : seulement l'explication du premier compte.
        fichier = PAGE_AUCUN_COMPTE if comptes.vide else PAGE
        # no-cache : le navigateur redemande toujours la page au Pi (jamais une vieille version).
        entetes = {"Cache-Control": "no-cache"}
        if not comptes.vide:
            entetes[MARQUE_COQUILLE] = "1"
        return HTMLResponse(fichier.read_text(encoding="utf-8"), headers=entetes)

    # ------------------------------------------------------------ appli installable (tâche 28 bis)

    empreinte_coquille = version_coquille()

    @app.get("/sw.js", include_in_schema=False)
    def service_worker() -> Response:
        """Le service worker : il ne garde que la coquille de la page, jamais l'API. Son numéro
        de version change avec le contenu de la page. Le navigateur ne l'accepte qu'en HTTPS (ou
        sur « localhost ») : voir pi/systeme/essai-page-web-2.md."""
        texte = SERVICE_WORKER.read_text(encoding="utf-8").replace(
            "__VERSION__", empreinte_coquille
        )
        return Response(
            texte,
            media_type="text/javascript",
            headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"},
        )

    @app.get("/manifeste.webmanifest", include_in_schema=False)
    def manifeste() -> Response:
        return Response(
            MANIFESTE.read_text(encoding="utf-8"),
            media_type="application/manifest+json",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/icones/{nom}", include_in_schema=False)
    def icone(nom: str) -> FileResponse:
        fichier = ICONES / nom
        if "/" in nom or not fichier.is_file():
            raise HTTPException(404, "icône inconnue")
        return FileResponse(fichier, headers={"Cache-Control": "no-cache"})

    # ------------------------------------------------------------ vue 3D et rejeu (tâche 28)

    @app.get("/statique/{chemin:path}", dependencies=regarder, include_in_schema=False)
    def statique(chemin: str) -> FileResponse:
        # Les fichiers de la page (bibliothèque 3D, code de la vue), seulement dans ce dossier.
        fichier = (STATIQUE / chemin).resolve()
        if not fichier.is_relative_to(STATIQUE.resolve()) or not fichier.is_file():
            raise HTTPException(404, "fichier inconnu")
        return FileResponse(fichier)

    def la_vue() -> Vue3d:
        if services.vue3d is None:
            raise HTTPException(404, "pas de vue 3D sur ce programme")
        return services.vue3d

    @app.get("/api/vue3d/scene", dependencies=regarder)
    def vue3d_scene() -> dict[str, Any]:
        """Les boîtes et les zones à dessiner, venues de vue3d.yaml et machine.yaml."""
        return la_vue().scene()

    @app.get("/api/vue3d/positions", dependencies=regarder)
    def vue3d_positions() -> dict[str, Any]:
        """Les positions des axes (m, ou ° pour un axe tournant) et les zones tenues."""
        vue = la_vue()
        return {
            "heure": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "axes": vue.positions(),
            "zones_tenues": vue.zones_tenues(),
            "en_alarme": any(m.statut == "alarme" for m in chef.etat().modules),
        }

    def les_rejeux() -> EnregistreurRejeu:
        if services.rejeux is None:
            raise HTTPException(404, "pas de rejeu d'incident sur ce programme")
        return services.rejeux

    @app.get("/api/vue3d/rejeux", dependencies=regarder)
    def vue3d_rejeux() -> list[dict[str, Any]]:
        """Les alarmes qui ont un rejeu, de la plus récente à la plus ancienne."""
        vue, rejeux = la_vue(), les_rejeux()
        numeros = rejeux.numeros()[: vue.reglages.rejeu.alarmes_proposees]
        if not numeros:
            return []
        marques = ",".join("?" * len(numeros))
        return registre.lire(
            "SELECT id, quand, module, etape, message FROM alarmes "
            f"WHERE id IN ({marques}) ORDER BY id DESC",
            tuple(numeros),
        )

    @app.get("/api/vue3d/rejeux/{numero}", dependencies=regarder)
    def vue3d_rejeu(numero: int) -> dict[str, Any]:
        """Les positions des axes autour d'une alarme (format : vidange/vue3d/rejeu.py)."""
        try:
            return les_rejeux().lire(numero)
        except ErreurRejeu as erreur:
            raise HTTPException(404, str(erreur)) from None

    # ------------------------------------------------------------ statistiques (tâche 28 bis)

    @app.get("/api/statistiques", dependencies=regarder)
    def statistiques(par: str = "jour") -> dict[str, Any]:
        """Seaux, cycles, alarmes, marche et arrêt par jour, semaine ou mois (registre)."""
        if services.statistiques is None:
            raise HTTPException(404, "pas de statistiques sur ce programme")
        if par not in ECHELLES:
            raise HTTPException(422, f"« par » : {', '.join(ECHELLES)}")
        return services.statistiques.calculer(par)

    # ------------------------------------------------------------ carnet de bord (tâche 28 bis)

    @app.get("/api/carnet", dependencies=regarder)
    def carnet(
        reponse: Response,
        recherche: str | None = None,
        cycle: int | None = None,
        seau: str | None = None,
        alarme: int | None = None,
        barrees: bool = True,
        limite: int | None = Query(default=None, ge=1),
        avant: int | None = Query(default=None, ge=1),
    ) -> list[dict[str, Any]]:
        """Les notes, de la plus récente à la plus ancienne (« recherche » : un bout de texte ou
        le nom de l'auteur ; « avant » : page suivante). L'en-tête X-Notes-Par-Page dit la
        taille d'une page : une page pleine peut avoir une suite."""
        par_page = min(limite or page_carnet, reglages.lignes_max)
        reponse.headers["X-Notes-Par-Page"] = str(par_page)
        return registre.lire_carnet(recherche, cycle, seau, alarme, barrees, par_page, avant)

    @app.post("/api/carnet", dependencies=produire)
    def carnet_ecrire(note: NouvelleNote, requete: Request) -> dict[str, Any]:
        """Écrit une note (l'auteur est le compte connecté ; rattachée à un cycle, un seau ou une
        alarme si on le dit). Elle ne se supprime pas : on la barre."""
        numero = registre.noter_carnet(
            requete.state.compte.nom,
            note.texte,
            note.cycle,
            note.seau,
            note.alarme,
            texte_carnet_max,
        )
        return {"numero": numero}

    @app.post("/api/carnet/{numero}/barrer", dependencies=produire)
    def carnet_barrer(numero: int, choix: RaisonBarree, requete: Request) -> dict[str, Any]:
        """Barre une note (elle reste lisible : qui, quand, pourquoi)."""
        registre.barrer_note(numero, requete.state.compte.nom, choix.raison)
        return {"barree": numero}

    # ------------------------------------------------------------ réglages modifiables (28 bis)

    def les_modifiables() -> Modifiables:
        if services.modifiables is None:
            raise HTTPException(404, "pas de réglages modifiables sur ce programme")
        return services.modifiables

    @app.get("/api/reglages-modifiables", dependencies=regler_sans_trace)
    def reglages_modifiables() -> dict[str, Any]:
        """Les réglages que la page peut changer : valeur, bornes, unité, aide, redémarrage."""
        return les_modifiables().etat()

    @app.get("/api/reglages-modifiables/historique", dependencies=regler_sans_trace)
    def reglages_modifiables_historique() -> list[dict[str, Any]]:
        return les_modifiables().historique(limiter(None))

    def noter_changement(requete: Request, fait: dict[str, Any], motif: str) -> None:
        """Le journal des actions : qui, quand, avant, après."""
        compte = requete.state.compte
        actions.noter(
            qui=compte.nom,
            role=compte.role.nom,
            adresse=requete.client.host if requete.client else "adresse inconnue",
            niveau="réglage",
            reglage=fait["nom"],
            avant=fait["ancien"],
            apres=fait["nouveau"],
            motif=motif,
        )

    @app.post("/api/reglages-modifiables/retour/{numero}", dependencies=regler)
    def reglage_revenir(numero: int, requete: Request) -> dict[str, Any]:
        """Remet la valeur d'avant un changement (le dernier de ce réglage)."""
        fait = les_modifiables().revenir(numero, _qui(requete))
        noter_changement(requete, fait, f"retour avant le changement n° {numero}")
        return fait

    @app.post("/api/reglages-modifiables/{nom}", dependencies=regler)
    def reglage_changer(nom: str, choix: NouvelleValeur, requete: Request) -> dict[str, Any]:
        """Change un réglage de la liste : bornes, vérifications du démarrage, écriture sûre."""
        fait = les_modifiables().changer(nom, choix.valeur, _qui(requete))
        noter_changement(requete, fait, "changement")
        return fait

    # ------------------------------------------------------------ connexion (tâche 25)

    @app.post("/api/connexion")
    def connexion(choix: Connexion, requete: Request) -> JSONResponse:
        adresse = requete.client.host if requete.client else "adresse inconnue"
        if comptes.vide:
            raise HTTPException(503, "aucun compte : en créer un sur le Pi (« vidange compte »)")
        attente = limite.attente_s(adresse)
        if attente > 0:
            journal.warning("Connexion refusée : trop d'essais ratés depuis %s", adresse)
            raise HTTPException(
                429, f"trop d'essais ratés : réessayer dans {int(attente) + 1} secondes"
            )
        compte = comptes.verifier(choix.nom, choix.mot_de_passe)
        if compte is None:
            limite.rater(adresse)
            journal.warning("Connexion ratée pour « %s » depuis %s", choix.nom[:32], adresse)
            raise HTTPException(401, "nom ou mot de passe faux")
        limite.reussir(adresse)
        duree = reglages.session_h * 3600
        reponse = JSONResponse({"nom": compte.nom, "role": compte.role.nom})
        reponse.set_cookie(
            COOKIE,
            comptes.creer_session(compte, duree),
            max_age=int(duree),
            httponly=True,
            # « strict » : un autre site ouvert dans le navigateur ne peut pas envoyer d'ordre
            # avec ce cookie.
            samesite="strict",
        )
        journal.info("Connexion de %s (%s) depuis %s", compte.nom, compte.role.nom, adresse)
        actions.noter(qui=compte.nom, role=compte.role.nom, adresse=adresse, niveau="connexion")
        return reponse

    @app.post("/api/deconnexion")
    def deconnexion() -> JSONResponse:
        reponse = JSONResponse({"connecte": False})
        reponse.delete_cookie(COOKIE, httponly=True, samesite="strict")
        return reponse

    @app.get("/api/moi")
    def moi(requete: Request) -> dict[str, Any]:
        """Qui est connecté (la page s'en sert pour choisir quoi montrer)."""
        if comptes.vide:
            return {"aucun_compte": True, "connecte": False}
        compte = comptes.lire_session(requete.cookies.get(COOKIE))
        if compte is None:
            return {"aucun_compte": False, "connecte": False}
        return {
            "aucun_compte": False,
            "connecte": True,
            "nom": compte.nom,
            "role": compte.role.nom,
            "droits": [mot_du_niveau(n) for n in Niveau if compte.role.permet(n)],
        }

    @app.get("/api/actions", dependencies=regler_sans_trace)
    def actions_recentes() -> list[dict[str, Any]]:
        """Qui a fait quoi : les dernières actions « produire » et « régler » (récentes d'abord)."""
        return actions.dernieres(limiter(None))

    # ------------------------------------------------------------ état et check-list

    @app.get("/api/etat", dependencies=regarder)
    def etat() -> dict[str, Any]:
        etat_chef = chef.etat()
        return {
            "heure": datetime.now().astimezone().isoformat(timespec="seconds"),
            "version": __version__,
            "en_pause": etat_chef.en_pause,
            "modules": [asdict(module) for module in etat_chef.modules],
            "attendent_go": etat_chef.attendent_go,
            # Pourquoi aucun Go n'est accepté (objet encore tenu au redémarrage...), ou "".
            "go_empeche": etat_chef.go_empeche,
            "alarmes_ouvertes": registre.alarmes_ouvertes(),
            "rafraichir_s": reglages.rafraichir_s,
            "distance": pilote is not None and pilote.actif,
            "mise_a_jour": mises_a_jour is not None and mises_a_jour.en_cours,
            "poste_fut": None if services.poste is None else services.poste.etat().en_dict(),
            "nettoyage": None
            if services.nettoyage is None
            else services.nettoyage.etat().en_dict(),
            "air": None if services.air is None else services.air.etat().en_dict(),
            "lot": None if services.lancement is None else services.lancement.en_dict(),
        }

    @app.get("/api/checklist", dependencies=regarder)
    def checklist() -> dict[str, Any]:
        constats = list(services.checklist())
        return {
            "prete": pire(constats) != "bloquant",
            "niveau": pire(constats),
            "constats": [asdict(constat) for constat in constats],
        }

    # ------------------------------------------------------------ ordres

    @app.post("/api/pause", dependencies=produire)
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

    @app.post("/api/reprendre", dependencies=produire)
    def reprendre(requete: Request) -> dict[str, Any]:
        journal.info("Reprise demandée par la %s", _qui(requete))
        pas_pendant_le_pilotage("Reprise")
        chef.reprendre()
        return {"en_pause": False}

    @app.post("/api/go/{module}", dependencies=produire)
    def go(module: str, requete: Request) -> dict[str, Any]:
        journal.info("Go pour « %s » demandé par la %s", module, _qui(requete))
        pas_pendant_le_pilotage("Go")
        chef.donner_go(module)
        return {"go": module}

    # ------------------------------------------------------------ lots (tâche 45 quater)

    def le_lancement() -> "Lancement":
        if services.lancement is None:
            raise HTTPException(404, "pas de lancement de lot (programme principal pas prêt)")
        return services.lancement

    @app.get("/api/lot", dependencies=regarder)
    def lot() -> dict[str, Any]:
        return le_lancement().en_dict()

    @app.post("/api/lot/seaux", dependencies=produire)
    def lot_de_seaux(choix: LotDeSeaux, requete: Request) -> dict[str, Any]:
        """Propose le lot ; il part au Go de l'écran de l'armoire (refus : 409 et la raison)."""
        lancement = le_lancement()
        qui = _qui(requete)
        journal.info(
            "Lot de %d seaux %s (%s) demandé par la %s",
            choix.nombre,
            choix.format,
            choix.variete,
            qui,
        )
        pas_pendant_la_mise_a_jour("Lot de seaux")
        lancement.proposer_seaux(choix.format, choix.nombre, choix.variete, qui)
        return lancement.en_dict()

    @app.post("/api/lot/bocaux", dependencies=produire)
    def lot_de_bocaux(choix: LotDeBocaux, requete: Request) -> dict[str, Any]:
        lancement = le_lancement()
        qui = _qui(requete)
        journal.info("Lot de %d bocaux demandé par la %s", choix.nombre, qui)
        pas_pendant_la_mise_a_jour("Lot de bocaux")
        lancement.proposer_bocaux(choix.nombre, qui)
        return lancement.en_dict()

    @app.post("/api/lot/annuler", dependencies=produire)
    def lot_annuler(requete: Request) -> dict[str, Any]:
        lancement = le_lancement()
        lancement.annuler(_qui(requete))
        return lancement.en_dict()

    # ------------------------------------------------------- inventaire du stockage (45 quinquies)

    def la_correction() -> "Correction":
        if services.correction is None:
            raise HTTPException(404, "pas de correction de l'inventaire (stockage pas prêt)")
        return services.correction

    @app.get("/api/stockage", dependencies=regarder)
    def stockage_inventaire() -> dict[str, Any]:
        return la_correction().inventaire()

    @app.post("/api/stockage/correction", dependencies=produire)
    def stockage_proposer(choix: CorrectionStockage, requete: Request) -> dict[str, Any]:
        """Propose la correction (rien n'est écrit) ; refus : 409 et la raison."""
        correction = la_correction()
        pas_pendant_la_mise_a_jour("Correction de l'inventaire")
        correction.proposer(choix.place, choix.contenu, choix.nombre, _qui(requete))
        return correction.inventaire()

    @app.post("/api/stockage/confirmer", dependencies=produire)
    def stockage_confirmer(requete: Request) -> dict[str, Any]:
        """Le Go de Karulium : la correction proposée est écrite et notée au journal."""
        correction = la_correction()
        correction.confirmer(_qui(requete))
        return correction.inventaire()

    @app.post("/api/stockage/annuler", dependencies=produire)
    def stockage_annuler(requete: Request) -> dict[str, Any]:
        correction = la_correction()
        correction.annuler(_qui(requete))
        return correction.inventaire()

    # ------------------------------------------------------------ poste du fût

    def le_poste() -> PosteFut:
        if services.poste is None:
            raise HTTPException(404, "pas de poste du fût (machine.yaml → poste_fut)")
        return services.poste

    @app.get("/api/poste-fut", dependencies=regarder)
    def poste_fut() -> dict[str, Any]:
        return le_poste().etat().en_dict()

    @app.post("/api/poste-fut/pret", dependencies=produire)
    def poste_fut_pret(requete: Request) -> dict[str, Any]:
        poste = le_poste()
        poste.appuyer_pret(_qui(requete))
        return poste.etat().en_dict()

    # ------------------------------------------------------------ nettoyage

    def le_nettoyage() -> Nettoyage:
        if services.nettoyage is None:
            raise HTTPException(404, "pas de nettoyage (machine.yaml → nettoyage)")
        return services.nettoyage

    @app.get("/api/nettoyage", dependencies=regarder)
    def nettoyage_etat() -> dict[str, Any]:
        return le_nettoyage().etat().en_dict()

    @app.post("/api/nettoyage/{ordre}", dependencies=produire)
    def nettoyage_ordre(ordre: str, requete: Request) -> dict[str, Any]:
        """ouvrir, fermer, eclairage, eteindre, outre, nuit, nuit_maintenant, annuler_nuit."""
        nettoyage = le_nettoyage()
        qui = _qui(requete)
        journal.info("Nettoyage : « %s » demandé par la %s", ordre, qui)
        ordres: dict[str, Callable[[], None]] = {
            "ouvrir": lambda: nettoyage.demander_ouverture(qui),
            "fermer": lambda: nettoyage.demander_fermeture(qui),
            "eclairage": lambda: nettoyage.eclairage(True, qui),
            "eteindre": lambda: nettoyage.eclairage(False, qui),
            "outre": lambda: nettoyage.passer_outre(qui),
            "nuit": lambda: nettoyage.programmer_nuit(qui),
            "nuit_maintenant": lambda: nettoyage.programmer_nuit(qui, tout_de_suite=True),
            "annuler_nuit": lambda: nettoyage.annuler_nuit(qui),
        }
        if ordre not in ordres:
            raise HTTPException(404, f"ordre inconnu « {ordre} » ({', '.join(ordres)})")
        ordres[ordre]()
        return nettoyage.etat().en_dict()

    # ------------------------------------------------------------ air

    def l_air() -> Air:
        if services.air is None:
            raise HTTPException(404, "pas d'air comprimé (relais_compresseur absent de la liste)")
        return services.air

    @app.get("/api/air", dependencies=regarder)
    def air_etat() -> dict[str, Any]:
        return l_air().etat().en_dict()

    @app.post("/api/air/bidon_vide", dependencies=produire)
    def air_bidon_vide(requete: Request) -> dict[str, Any]:
        """L'opérateur a vidé le bidon de purge : le rappel repart de zéro."""
        air = l_air()
        air.bidon_vide(_qui(requete))
        return air.etat().en_dict()

    # ------------------------------------------------------------ entretien (tâche 26)

    def l_entretien() -> Entretien:
        if services.entretien is None:
            raise HTTPException(404, "pas d'entretien (entretien.yaml)")
        return services.entretien

    @app.get("/api/entretien", dependencies=regarder)
    def entretien_etat() -> dict[str, Any]:
        """Les compteurs, les pièces d'usure et ce qui est bientôt à faire."""
        return l_entretien().en_dict()

    @app.post("/api/entretien/{piece}/fait", dependencies=regler)
    def entretien_fait(piece: str, requete: Request) -> dict[str, Any]:
        """La pièce a été contrôlée ou changée : son usure repart de zéro (noté : qui, quand)."""
        entretien = l_entretien()
        if piece not in entretien.reglages.pieces:
            raise HTTPException(404, f"pièce « {piece} » inconnue (entretien.yaml → pieces)")
        journal.info("Entretien : « %s » fait, demandé par la %s", piece, _qui(requete))
        return entretien.fait(piece, _qui(requete)).en_dict()

    # ------------------------------------------------------------ spray

    def le_spray() -> Spray:
        if services.spray is None:
            raise HTTPException(404, "pas de spray (machine.yaml → spray)")
        return services.spray

    @app.get("/api/spray", dependencies=regarder)
    def spray_etat() -> dict[str, Any]:
        return le_spray().en_dict()

    @app.post("/api/spray/{ordre}", dependencies=produire)
    def spray_ordre(ordre: str, requete: Request, emplacement: int | None = None) -> dict[str, Any]:
        """sans_spray (choix après une erreur), cartouche (?emplacement=N : nouvelle cartouche
        confirmée), alcool_rempli (plein du flacon d'alcool fait)."""
        spray = le_spray()
        journal.info("Spray : « %s » demandé par la %s", ordre, _qui(requete))
        if ordre == "sans_spray":
            spray.continuer_sans_spray()
        elif ordre == "cartouche":
            if emplacement is None or not 1 <= emplacement <= 4:
                raise HTTPException(422, "cartouche : emplacement de 1 à 4 (?emplacement=N)")
            spray.confirmer_cartouche(emplacement)
        elif ordre == "alcool_rempli":
            spray.alcool_rempli()
        else:
            raise HTTPException(
                404, f"ordre inconnu « {ordre} » (sans_spray, cartouche, alcool_rempli)"
            )
        return spray.en_dict()

    # ------------------------------------------------------------ alarmes

    @app.get("/api/alarmes", dependencies=regarder)
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

    @app.post("/api/alarmes/{numero}/vue", dependencies=produire)
    def alarme_vue(numero: int, requete: Request) -> dict[str, Any]:
        """« J'ai vu » : l'alarme reste ouverte, mais les notifications ne la renvoient plus
        (escalade, tâche 27). Noté dans le journal des actions (qui, quand) et dans le registre."""
        premiere = registre.noter_alarme_vue(numero, _qui(requete))
        journal.info("Alarme n° %d vue par la %s", numero, _qui(requete))
        return {"vue": numero, "premiere_fois": premiere}

    @app.post("/api/alarmes/{numero}/acquitter", dependencies=produire)
    def acquitter(numero: int, requete: Request) -> dict[str, Any]:
        journal.info("Alarme n° %d acquittée par la %s", numero, _qui(requete))
        services.acquitter(numero, _qui(requete))
        return {"acquittee": numero}

    # ------------------------------------------------------------ historique

    @app.get("/api/historique", dependencies=regarder)
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

    @app.get("/api/historique/{cycle}", dependencies=regarder)
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

    @app.get("/api/photos", dependencies=regarder)
    def photos(
        cycle: int | None = None,
        seau: str | None = None,
        limite: int | None = Query(default=None, ge=1),
        avant: int | None = Query(default=None, ge=1),
    ) -> list[dict[str, Any]]:
        """Les dernières photos (d'un cycle, d'un seau), de la plus récente à la plus ancienne."""
        return lire_photos(cycle, seau, limite, avant)

    @app.get("/api/photos/{numero}", dependencies=regarder)
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

    @app.get("/api/cameras", dependencies=regarder)
    def liste_cameras() -> dict[str, Any]:
        if cameras is None:
            return {"cameras": [], "images_par_s": 0}
        return {"cameras": cameras.decrire(), "images_par_s": cameras.reglages.page_images_par_s}

    @app.get("/api/cameras/{nom}/image", dependencies=regarder)
    def image_camera(nom: str) -> Response:
        """La dernière image ; son numéro est dans l'en-tête « X-Image » (pilotage à distance)."""
        try:
            image = les_cameras().derniere(nom)
        except ErreurCamera as erreur:
            raise HTTPException(404, str(erreur)) from None
        if image is None:
            raise HTTPException(503, f"caméra « {nom} » : pas encore d'image")
        return jpeg(image.donnees, {"X-Image": str(image.numero)})

    @app.get("/api/clips", dependencies=regarder)
    def clips(
        limite: int | None = Query(default=None, ge=1), avant: str | None = None
    ) -> list[dict[str, Any]]:
        """Les clips des alarmes, du plus récent au plus ancien."""
        return les_cameras().lister_clips(limiter(limite), avant)

    @app.get("/api/clips/{clip}/{camera}", dependencies=regarder)
    def index_clip(clip: str, camera: str) -> dict[str, Any]:
        try:
            index = les_cameras().index_du_clip(clip, camera)
        except ErreurCamera as erreur:
            raise HTTPException(404, str(erreur)) from None
        return {"clip": clip, "camera": camera, "heures": [heure for *_, heure in index]}

    @app.get("/api/clips/{clip}/{camera}/{rang}", dependencies=regarder)
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

    @app.get("/api/distance", dependencies=regarder)
    def distance() -> dict[str, Any]:
        return le_pilote().etat()

    @app.post("/api/distance/activer", dependencies=regler)
    def activer(requete: Request) -> dict[str, Any]:
        pas_pendant_la_mise_a_jour("Pilotage à distance")
        le_pilote().activer(_qui(requete))
        return le_pilote().etat()

    @app.post("/api/distance/quitter", dependencies=regler)
    def quitter(requete: Request) -> dict[str, Any]:
        le_pilote().quitter(_qui(requete))
        return le_pilote().etat()

    @app.post("/api/distance/tenir", dependencies=regler_sans_trace)
    def tenir(ordre: Tenir, requete: Request) -> dict[str, Any]:
        le_pilote().tenir(_qui(requete), ordre.axe, ordre.sens, ordre.camera, ordre.image)
        return le_pilote().etat()

    @app.post("/api/distance/lacher", dependencies=regler_sans_trace)
    def lacher(requete: Request) -> dict[str, Any]:
        le_pilote().lacher(_qui(requete))
        return le_pilote().etat()

    @app.get("/api/distance/journal", dependencies=regarder)
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

    @app.get("/api/mises-a-jour", dependencies=regarder)
    def etat_mises_a_jour() -> dict[str, Any]:
        return les_mises_a_jour().etat()

    @app.post("/api/mises-a-jour/programmes", dependencies=regler)
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

    @app.post("/api/mises-a-jour/cartes/{carte}/programme", dependencies=regler)
    def programme_carte(carte: str, choix: ChoixProgramme, requete: Request) -> dict[str, Any]:
        les_mises_a_jour().ecrire_programme(carte, choix.fichier, _qui(requete))
        return les_mises_a_jour().etat()

    @app.post("/api/mises-a-jour/cartes/{carte}/reglages", dependencies=regler)
    def reglages_carte(carte: str, requete: Request) -> dict[str, Any]:
        les_mises_a_jour().envoyer_reglages(carte, _qui(requete))
        return les_mises_a_jour().etat()

    @app.post("/api/mises-a-jour/cartes/{carte}/revenir", dependencies=regler)
    def revenir_carte(carte: str, choix: ChoixCopie, requete: Request) -> dict[str, Any]:
        les_mises_a_jour().revenir_carte(carte, choix.copie, _qui(requete))
        return les_mises_a_jour().etat()

    @app.post("/api/mises-a-jour/accelerometre/programme", dependencies=regler)
    def programme_accelerometre(choix: ChoixProgramme, requete: Request) -> dict[str, Any]:
        les_mises_a_jour().ecrire_accelerometre(choix.fichier, _qui(requete))
        return les_mises_a_jour().etat()

    @app.post("/api/mises-a-jour/accelerometre/revenir", dependencies=regler)
    def revenir_accelerometre(choix: ChoixCopie, requete: Request) -> dict[str, Any]:
        les_mises_a_jour().revenir_accelerometre(choix.copie, _qui(requete))
        return les_mises_a_jour().etat()

    @app.post("/api/mises-a-jour/pi/chercher", dependencies=regler)
    def chercher_pi(requete: Request) -> dict[str, Any]:
        les_mises_a_jour().chercher_pi(_qui(requete))
        return les_mises_a_jour().etat()

    @app.post("/api/mises-a-jour/pi/installer", dependencies=regler)
    def installer_pi(requete: Request) -> dict[str, Any]:
        les_mises_a_jour().installer_pi(_qui(requete))
        return les_mises_a_jour().etat()

    @app.post("/api/mises-a-jour/pi/revenir", dependencies=regler)
    def revenir_pi(requete: Request) -> dict[str, Any]:
        les_mises_a_jour().revenir_pi(_qui(requete))
        return les_mises_a_jour().etat()

    # Une route sans niveau de droit déclaré empêche le démarrage.
    verifier_roles_declares(app)
    return app
