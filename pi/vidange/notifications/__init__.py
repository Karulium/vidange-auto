"""Notifications sur le téléphone (tâche 27) : alertes, fin de fût, résumé du soir, escalade.

Elles INFORMENT, elles ne protègent personne : la sécurité est câblée, jamais dans le logiciel.
"""

from vidange.notifications.notificateur import Notificateur, en_heures_calmes

__all__ = ["Notificateur", "en_heures_calmes"]
