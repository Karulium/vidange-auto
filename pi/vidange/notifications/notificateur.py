"""Le notificateur : il regarde le registre et met dans la file d'envoi ce qui doit aller sur le
téléphone (ntfy, Telegram). Il ne commande rien et la machine ne l'attend jamais.

Ce qu'il annonce, tout vient du registre (rien n'est inventé) :
- chaque alarme (module, étape, message, « quoi faire ») : 60 ;
- la fin d'un fût, le nettoyage à faire, une pièce d'usure « à faire » (tâche 26) : 61 ;
  le « calcul conseillé » n'existe pas encore dans le code : `annoncer("calcul_conseille", ...)`
  est prêt pour le jour où il existera ;
- le résumé du soir : 62 ;
- l'escalade : une alarme urgente que personne n'a « vue » (bouton « J'ai vu » de la page web) ni
  effacée est renvoyée en priorité haute, puis envoyée aussi à la 2ᵉ liste de destinataires : 63.

Le niveau de chaque sorte (urgent, normal, info) est dans programme.yaml. La nuit (heures calmes),
seuls les urgents partent ; les autres attendent la fin des heures calmes (ils restent « pas encore
traités » dans le registre, donc ils survivent à un redémarrage).

Ce qui a été traité (envoyé, ou volontairement laissé de côté) est noté dans la table
« notifications_faites » : jamais deux fois le même message, même après une coupure.
Sans aucun canal allumé (secrets vides), les choses sont notées comme traitées sans rien envoyer :
les notifications parlent du présent, pas de ce qui s'est passé avant qu'on les règle.
"""

import json
import threading
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from vidange.entretien import Entretien
from vidange.envois.facteur import Facteur
from vidange.envois.telephone import CANAUX
from vidange.fiabilite.constats import lancer_boucle
from vidange.journal import donner_journal
from vidange.registre import Registre
from vidange.registre.base import heure, maintenant
from vidange.reglages import ReglagesNotifications, minutes_du_jour

journal = donner_journal("notifications")

# Noms des messages du programme (leur niveau est dans programme.yaml → notifications → niveaux).
FIN_FUT = "fin_fut"
NETTOYAGE_A_FAIRE = "nettoyage_a_faire"
ENTRETIEN_A_FAIRE = "entretien_a_faire"
CALCUL_CONSEILLE = "calcul_conseille"
RESUME_SOIR = "resume_soir"


def en_heures_calmes(reglages: ReglagesNotifications, moment: datetime) -> bool:
    """Vrai si `moment` (heure locale du Pi) est dans les heures calmes."""
    debut = minutes_du_jour(reglages.heures_calmes.debut)
    fin = minutes_du_jour(reglages.heures_calmes.fin)
    if debut == fin:
        return False
    local = moment.astimezone()
    minute = local.hour * 60 + local.minute
    if debut < fin:
        return debut <= minute < fin
    return minute >= debut or minute < fin


def _hhmm(texte: str) -> str:
    return datetime.fromisoformat(texte).astimezone().strftime("%H:%M")


class Notificateur:
    def __init__(
        self,
        registre: Registre,
        reglages: ReglagesNotifications,
        facteur: Facteur,
        entretien: Entretien | None = None,
        horloge: Callable[[], datetime] = maintenant,
    ) -> None:
        self.registre = registre
        self.reglages = reglages
        self.facteur = facteur
        self.entretien = entretien
        self._horloge = horloge
        self._mis_en_file = 0

    # ------------------------------------------------------------ canaux et niveaux

    def canaux_actifs(self) -> list[str]:
        return [canal for canal in CANAUX if self.facteur.expediteurs.get(canal) is not None]

    def _canaux_renfort(self) -> list[str]:
        return [
            canal
            for canal in self.canaux_actifs()
            if getattr(self.facteur.expediteurs[canal], "a_renfort", lambda: False)()
        ]

    def niveau(self, sorte: str, etape: str | None = None) -> str:
        """Niveau d'une sorte : « module.etape », puis « module », puis le niveau par défaut."""
        niveaux = self.reglages.niveaux
        if etape and f"{sorte}.{etape}" in niveaux:
            return niveaux[f"{sorte}.{etape}"]
        return niveaux.get(sorte, self.reglages.niveau_defaut)

    def _liens(self) -> str:
        liens = [
            f"{nom} : {lien}"
            for nom, lien in (
                ("Page (Wi-Fi de l'atelier)", self.reglages.lien_page),
                ("Page (Tailscale)", self.reglages.lien_tailscale),
            )
            if lien
        ]
        return "\n".join(liens)

    # ------------------------------------------------------------ mise en file

    def _mettre_en_file(
        self,
        cle: str,
        niveau: str,
        titre: str,
        texte: str,
        canaux: list[str] | None = None,
        groupe: str = "principal",
        rappel: bool = False,
        alarme: int | None = None,
    ) -> bool:
        """Un message par canal dans la file d'envoi, puis la chose est notée « traitée ».
        Rend vrai si un message est parti dans la file."""
        canaux = self.canaux_actifs() if canaux is None else canaux
        if not canaux:
            journal.info("Aucun canal de notification allumé : « %s » non envoyé.", cle)
            self.registre.noter_notification_faite(cle)
            return False
        lien = self.reglages.lien_page or self.reglages.lien_tailscale
        contenu = json.dumps(
            {
                "niveau": niveau,
                "titre": titre,
                "texte": f"{texte}\n{self._liens()}".strip(),
                "lien": lien,
                "groupe": groupe,
                "rappel": rappel,
                "prevu_le": heure(self._horloge()),
                "annuler_si_vue": alarme,
            },
            ensure_ascii=False,
        )
        for canal in canaux:
            self.registre.ajouter_envoi(canal, "message", cle, contenu=contenu)
        self.registre.noter_notification_faite(cle)
        journal.info(
            "Notification « %s » (%s) mise dans la file : %s", cle, niveau, ", ".join(canaux)
        )
        self._mis_en_file += 1
        return True

    def _peut_partir(self, niveau: str) -> bool:
        """La nuit, seuls les urgents partent."""
        return niveau == "urgent" or not en_heures_calmes(self.reglages, self._horloge())

    def annoncer(self, sorte: str, cle: str, titre: str, texte: str) -> bool:
        """Annonce un message du programme (exemple : « calcul_conseille ») : niveau de sa sorte,
        heures calmes, une seule fois par `cle`. Rend vrai s'il est parti dans la file."""
        if self.registre.notification_faite(cle) is not None:
            return False
        niveau = self.niveau(sorte)
        if not self._peut_partir(niveau):
            return False
        if self._mettre_en_file(cle, niveau, titre, texte):
            self.facteur.tournee()
            return True
        return False

    # ------------------------------------------------------------ alarmes (60) et escalade (63)

    def _alarmes_recentes(self) -> list[dict[str, Any]]:
        depuis = self._horloge() - timedelta(days=self.reglages.chercher_jours)
        return self.registre.lire(
            "SELECT * FROM alarmes WHERE quand >= ? ORDER BY id", (heure(depuis),)
        )

    @staticmethod
    def texte_alarme(alarme: dict[str, Any]) -> str:
        etape = f" (étape « {alarme['etape']} »)" if alarme["etape"] else ""
        texte = (
            f"Alarme n° {alarme['id']} de « {alarme['module']} »{etape} à "
            f"{_hhmm(alarme['quand'])} : {alarme['message']}"
        )
        if alarme["quoi_faire"]:
            texte += f"\nQuoi faire : {alarme['quoi_faire']}"
        return texte

    def _alarmes(self) -> None:
        for alarme in self._alarmes_recentes():
            cle = f"alarme:{alarme['id']}"
            if self.registre.notification_faite(cle) is not None:
                continue
            if alarme["acquittee_le"]:
                # Effacée avant que le message parte : plus rien à dire.
                self.registre.noter_notification_faite(cle)
                continue
            niveau = self.niveau(alarme["module"], alarme["etape"])
            if not self._peut_partir(niveau):
                continue
            titre = ("URGENT : " if niveau == "urgent" else "") + f"alarme {alarme['module']}"
            self._mettre_en_file(cle, niveau, titre, self.texte_alarme(alarme), alarme=alarme["id"])

    def _escalade(self) -> None:
        reglages = self.reglages.escalade
        for alarme in self._alarmes_recentes():
            if alarme["acquittee_le"] or alarme["vue_le"]:
                continue
            if self.niveau(alarme["module"], alarme["etape"]) != "urgent":
                continue
            cle = f"alarme:{alarme['id']}"
            premier = self.registre.notification_faite(cle)
            if premier is None:
                continue
            attente_min = (self._horloge() - datetime.fromisoformat(premier)).total_seconds() / 60
            if attente_min >= reglages.rappel_apres_min:
                self._rappel(alarme, cle, attente_min)
            if attente_min >= reglages.renfort_apres_min:
                self._renfort(alarme, cle, attente_min)

    def _suite(self, alarme: dict[str, Any], attente_min: float) -> str:
        return (
            f"Pas vue depuis {attente_min:.0f} min. Ouvrir la page et appuyer sur « J'ai vu » "
            f"(ou corriger et acquitter).\n{self.texte_alarme(alarme)}"
        )

    def _rappel(self, alarme: dict[str, Any], cle: str, attente_min: float) -> None:
        cle_rappel = f"{cle}:rappel"
        if self.registre.notification_faite(cle_rappel) is not None:
            return
        self._mettre_en_file(
            cle_rappel,
            "urgent",
            f"RAPPEL URGENT : alarme {alarme['module']}",
            self._suite(alarme, attente_min),
            rappel=True,
            alarme=alarme["id"],
        )

    def _renfort(self, alarme: dict[str, Any], cle: str, attente_min: float) -> None:
        cle_renfort = f"{cle}:renfort"
        if self.registre.notification_faite(cle_renfort) is not None:
            return
        canaux = self._canaux_renfort()
        if not canaux:
            journal.info("Alarme n° %d : pas de 2ᵉ liste de destinataires remplie.", alarme["id"])
            self.registre.noter_notification_faite(cle_renfort)
            return
        self._mettre_en_file(
            cle_renfort,
            "urgent",
            f"URGENT, personne n'a vu : alarme {alarme['module']}",
            self._suite(alarme, attente_min),
            canaux=canaux,
            groupe="renfort",
            rappel=True,
            alarme=alarme["id"],
        )

    # ------------------------------------------------------------ fût, nettoyage, entretien (61)

    def _futs_finis(self) -> list[dict[str, Any]]:
        depuis = self._horloge() - timedelta(days=self.reglages.chercher_jours)
        return self.registre.lire(
            "SELECT c.id, c.fin, f.code AS fut, "
            "(SELECT COUNT(*) FROM seaux_du_cycle WHERE cycle_id = c.id) AS seaux "
            "FROM cycles c LEFT JOIN futs f ON f.id = c.fut_id "
            "WHERE c.module = ? AND c.issue = 'termine' AND c.fin >= ? ORDER BY c.id",
            (self.reglages.evenements.module_fut, heure(depuis)),
        )

    def _fin_de_fut(self) -> None:
        for cycle in self._futs_finis():
            cle = f"fut:{cycle['id']}"
            if self.registre.notification_faite(cle) is not None:
                continue
            niveau = self.niveau(FIN_FUT)
            if not self._peut_partir(niveau):
                continue
            fut = f"Fût {cycle['fut']}" if cycle["fut"] else "Le fût"
            texte = f"{fut} vidé à {_hhmm(cycle['fin'])} : {cycle['seaux']} seau(x) rempli(s)."
            self._mettre_en_file(cle, niveau, "Fin de fût", texte)

    def _nettoyage_a_faire(self) -> None:
        evenements = self.reglages.evenements
        for cycle in self._futs_finis():
            cle = f"nettoyage:{cycle['id']}"
            if self.registre.notification_faite(cle) is not None:
                continue
            marques = ", ".join("?" for _ in evenements.modules_nettoyage)
            commence = self.registre.lire(
                f"SELECT id FROM cycles WHERE module IN ({marques}) AND debut >= ? LIMIT 1",
                (*evenements.modules_nettoyage, cycle["fin"]),
            )
            if commence:
                self.registre.noter_notification_faite(cle)
                continue
            fin = datetime.fromisoformat(cycle["fin"])
            attente_min = (self._horloge() - fin).total_seconds() / 60
            niveau = self.niveau(NETTOYAGE_A_FAIRE)
            if attente_min < evenements.nettoyage_apres_min or not self._peut_partir(niveau):
                continue
            fut = f"Le fût {cycle['fut']}" if cycle["fut"] else "Le fût"
            self._mettre_en_file(
                cle,
                niveau,
                "Nettoyage à faire",
                f"{fut} est vidé depuis {attente_min:.0f} min et aucun nettoyage n'a commencé. "
                "Lancer le nettoyage de la machine.",
            )

    def _entretien(self) -> None:
        if self.entretien is None:
            return
        for piece in self.entretien.etat():
            if piece.niveau != "a_faire":
                continue
            # La clé change à chaque « Fait » (nouveau point de départ) : la pièce qui s'use de
            # nouveau sera annoncée de nouveau.
            cle = f"entretien:{piece.nom}:{piece.depuis}"
            if self.registre.notification_faite(cle) is not None:
                continue
            niveau = self.niveau(ENTRETIEN_A_FAIRE)
            if not self._peut_partir(niveau):
                continue
            exemple = " (limite d'exemple)" if piece.exemple else ""
            self._mettre_en_file(
                cle,
                niveau,
                "Entretien à faire",
                f"{piece.description} : {piece.usure:g} sur {piece.limite:g} {piece.unite}"
                f"{exemple}. {piece.a_faire}",
            )

    # ------------------------------------------------------------ résumé du soir (62)

    def texte_resume(self, maintenant_: datetime) -> str:
        """Le résumé de la journée, d'après le registre seulement."""
        debut = heure(maintenant_.astimezone().replace(hour=0, minute=0, second=0, microsecond=0))
        seaux = self.registre.lire(
            "SELECT COUNT(*) AS n, COUNT(DISTINCT cycle_id) AS cycles FROM seaux_du_cycle "
            "WHERE quand >= ?",
            (debut,),
        )[0]
        futs = self.registre.lire(
            "SELECT COUNT(*) AS n FROM cycles WHERE module = ? AND issue = 'termine' AND fin >= ?",
            (self.reglages.evenements.module_fut, debut),
        )[0]["n"]
        alarmes = self.registre.lire("SELECT * FROM alarmes WHERE quand >= ? ORDER BY id", (debut,))
        lignes = [f"Résumé du {maintenant_.astimezone().strftime('%d/%m/%Y')} :"]
        if seaux["n"]:
            lignes.append(f"- Seaux remplis : {seaux['n']} (en {seaux['cycles']} cycle(s)).")
        else:
            lignes.append("- Aucun seau rempli.")
        lignes.append(f"- Fûts vidés : {futs}.")
        if alarmes:
            ouvertes = sum(1 for a in alarmes if not a["acquittee_le"])
            lignes.append(f"- Alarmes : {len(alarmes)} ({ouvertes} encore ouverte(s)).")
            maximum = self.reglages.resume_soir.alarmes_max
            for alarme in alarmes[-maximum:]:
                lignes.append(
                    f"  {_hhmm(alarme['quand'])} {alarme['module']} : {alarme['message']}"
                )
            if len(alarmes) > maximum:
                lignes.append(f"  (et {len(alarmes) - maximum} plus ancienne(s))")
        else:
            lignes.append("- Aucune alarme.")
        demain = self._a_faire_demain()
        if demain:
            lignes.append("À faire demain :")
            lignes += [f"- {ligne}" for ligne in demain]
        else:
            lignes.append("À faire demain : rien de prévu par le logiciel.")
        return "\n".join(lignes)

    def _a_faire_demain(self) -> list[str]:
        if self.entretien is None:
            return []
        lignes = []
        for piece in self.entretien.etat():
            if piece.niveau == "ok":
                continue
            quoi = "à faire" if piece.niveau == "a_faire" else "bientôt à faire"
            lignes.append(f"Entretien, {quoi} : {piece.description}. {piece.a_faire}")
        return lignes

    def _resume(self) -> None:
        reglages = self.reglages.resume_soir
        if not reglages.actif:
            return
        maintenant_ = self._horloge()
        local = maintenant_.astimezone()
        minute = local.hour * 60 + local.minute
        debut = minutes_du_jour(reglages.heure)
        if not debut <= minute < debut + reglages.retard_max_h * 60:
            return
        cle = f"resume:{local.date().isoformat()}"
        if self.registre.notification_faite(cle) is not None:
            return
        niveau = self.niveau(RESUME_SOIR)
        if not self._peut_partir(niveau):
            return
        self._mettre_en_file(cle, niveau, "Résumé du soir", self.texte_resume(maintenant_))

    # ------------------------------------------------------------ boucle

    def tour(self) -> int:
        """Un passage : rend le nombre de messages mis dans la file. Les messages partent tout de
        suite (sans attendre le prochain tour du facteur)."""
        self._mis_en_file = 0
        self.registre.effacer_notifications_faites(
            self._horloge() - timedelta(days=self.reglages.garder_traites_jours)
        )
        for etape in (
            self._alarmes,
            self._escalade,
            self._fin_de_fut,
            self._nettoyage_a_faire,
            self._entretien,
            self._resume,
        ):
            try:
                etape()
            except Exception:
                # Un morceau qui plante ne doit pas empêcher les autres d'annoncer.
                journal.exception("Notifications : « %s » a échoué", etape.__name__)
        if self._mis_en_file:
            self.facteur.tournee()
        return self._mis_en_file

    def demarrer(self, arret: threading.Event) -> threading.Thread:
        return lancer_boucle("notifications", self.reglages.periode_s, self.tour, arret)
