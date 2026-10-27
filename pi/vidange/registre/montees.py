"""Montées de version de la base du registre.

La base porte son numéro de version (« PRAGMA user_version »). Au démarrage, le programme
applique, dans l'ordre, chaque montée qui manque. Chaque montée se fait d'un seul bloc :
une coupure pendant une montée laisse la base à la version d'avant, intacte.

Pour changer la base plus tard : **ne jamais modifier une montée déjà livrée**, en ajouter
une nouvelle à la fin de MONTEES (exemple : « ALTER TABLE seaux ADD COLUMN couleur TEXT »).

Les heures sont du texte ISO 8601 avec le décalage horaire (« 2026-10-26T14:03:12-04:00 »).
Les codes des fûts, seaux, bocaux et Pétri sont ceux de leur QR (« S1293 », « B327 »...).
"""

# Version 1 : le registre de départ.
_VERSION_1 = (
    # Les objets suivis, reconnus par le code de leur QR.
    """
    CREATE TABLE futs (
        id INTEGER PRIMARY KEY,
        code TEXT NOT NULL UNIQUE,
        cree_le TEXT NOT NULL,
        remarque TEXT
    )
    """,
    """
    CREATE TABLE seaux (
        id INTEGER PRIMARY KEY,
        code TEXT NOT NULL UNIQUE,
        cree_le TEXT NOT NULL,
        -- Type de seau (nom dans machine.yaml), pour sa tare.
        type_seau TEXT,
        remarque TEXT
    )
    """,
    """
    CREATE TABLE bocaux (
        id INTEGER PRIMARY KEY,
        code TEXT NOT NULL UNIQUE,
        cree_le TEXT NOT NULL,
        remarque TEXT
    )
    """,
    """
    CREATE TABLE petris (
        id INTEGER PRIMARY KEY,
        code TEXT NOT NULL UNIQUE,
        cree_le TEXT NOT NULL,
        remarque TEXT
    )
    """,
    # Un cycle = un passage d'un module du chef (vidange d'un fût, lavage...).
    """
    CREATE TABLE cycles (
        id INTEGER PRIMARY KEY,
        module TEXT NOT NULL,
        debut TEXT NOT NULL,
        fin TEXT,
        -- termine, abandonne ; vide tant que le cycle tourne.
        issue TEXT CHECK (issue IN ('termine', 'abandonne')),
        fut_id INTEGER REFERENCES futs (id),
        remarque TEXT
    )
    """,
    # Les seaux remplis pendant un cycle.
    """
    CREATE TABLE seaux_du_cycle (
        id INTEGER PRIMARY KEY,
        cycle_id INTEGER NOT NULL REFERENCES cycles (id),
        seau_id INTEGER NOT NULL REFERENCES seaux (id),
        quand TEXT NOT NULL,
        UNIQUE (cycle_id, seau_id)
    )
    """,
    # Le mycélium versé dans chaque seau : plusieurs doses possibles, de plusieurs bocaux (un bocal
    # fini en cours de seau, ou un plan d'essais) ; quantité vide si elle n'est pas mesurée.
    """
    CREATE TABLE doses_mycelium (
        id INTEGER PRIMARY KEY,
        seau_du_cycle_id INTEGER NOT NULL REFERENCES seaux_du_cycle (id),
        bocal_id INTEGER NOT NULL REFERENCES bocaux (id),
        quantite_g REAL CHECK (quantite_g IS NULL OR quantite_g >= 0),
        quand TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE etapes_faites (
        id INTEGER PRIMARY KEY,
        cycle_id INTEGER NOT NULL REFERENCES cycles (id),
        etape TEXT NOT NULL,
        debut TEXT NOT NULL,
        fin TEXT NOT NULL,
        -- Durée du geste en secondes (sans le temps des pauses).
        duree_s REAL NOT NULL CHECK (duree_s >= 0),
        issue TEXT NOT NULL CHECK (issue IN ('faite', 'alarme', 'abandonnee'))
    )
    """,
    # Une mesure peut se rattacher à un cycle et/ou à un objet (poids d'un seau, dose...).
    """
    CREATE TABLE mesures (
        id INTEGER PRIMARY KEY,
        quand TEXT NOT NULL,
        nom TEXT NOT NULL,
        valeur REAL NOT NULL,
        unite TEXT NOT NULL,
        -- Le capteur qui a mesuré (nom de la liste des entrées/sorties) : on peut ainsi
        -- écarter les mesures d'un capteur qui s'est révélé faux.
        capteur TEXT,
        cycle_id INTEGER REFERENCES cycles (id),
        fut_id INTEGER REFERENCES futs (id),
        seau_id INTEGER REFERENCES seaux (id),
        bocal_id INTEGER REFERENCES bocaux (id),
        petri_id INTEGER REFERENCES petris (id)
    )
    """,
    # Les photos restent en fichiers sur le SSD : la base ne garde que leur chemin,
    # relatif au dossier des photos.
    """
    CREATE TABLE photos (
        id INTEGER PRIMARY KEY,
        quand TEXT NOT NULL,
        chemin TEXT NOT NULL UNIQUE,
        camera TEXT,
        remarque TEXT,
        cycle_id INTEGER REFERENCES cycles (id),
        fut_id INTEGER REFERENCES futs (id),
        seau_id INTEGER REFERENCES seaux (id),
        bocal_id INTEGER REFERENCES bocaux (id),
        petri_id INTEGER REFERENCES petris (id)
    )
    """,
    """
    CREATE TABLE alarmes (
        id INTEGER PRIMARY KEY,
        quand TEXT NOT NULL,
        module TEXT NOT NULL,
        etape TEXT,
        message TEXT NOT NULL,
        quoi_faire TEXT,
        cycle_id INTEGER REFERENCES cycles (id),
        acquittee_le TEXT,
        acquittee_par TEXT
    )
    """,
    # Chaque réglage changé : ancien, nouveau, qui, quand (pour pouvoir l'annuler).
    """
    CREATE TABLE reglages_appliques (
        id INTEGER PRIMARY KEY,
        quand TEXT NOT NULL,
        qui TEXT NOT NULL,
        fichier TEXT NOT NULL,
        reglage TEXT NOT NULL,
        -- Valeurs écrites en JSON (nombre, texte, liste...) ; vide = le réglage n'existait pas.
        ancien TEXT,
        nouveau TEXT,
        raison TEXT
    )
    """,
    "CREATE INDEX etapes_faites_cycle ON etapes_faites (cycle_id)",
    "CREATE INDEX mesures_quand ON mesures (quand)",
    "CREATE INDEX mesures_seau ON mesures (seau_id)",
    "CREATE INDEX photos_cycle ON photos (cycle_id)",
    "CREATE INDEX alarmes_quand ON alarmes (quand)",
)

# Version 2 (tâche 7) : chaque alarme garde le chemin de son bilan (fichier JSON écrit au moment
# de l'alarme : positions, capteurs, état des cartes...), relatif au dossier des données.
_VERSION_2 = ("ALTER TABLE alarmes ADD COLUMN bilan TEXT",)

# Version 3 (tâche 10) : la file d'envoi vers l'extérieur (logiciel de culture, copie de secours
# de la maison). Une ligne = une chose à envoyer ; elle reste jusqu'à ce que l'envoi réussisse.
_VERSION_3 = (
    """
    CREATE TABLE envois (
        id INTEGER PRIMARY KEY,
        -- Clé unique de l'envoi (UUID), la même à chaque essai : le destinataire reconnaît
        -- ainsi un envoi déjà reçu (coupure pendant l'envoi, base remise depuis une copie...).
        cle TEXT NOT NULL UNIQUE,
        -- culture : logiciel de culture (Django) ; secours : copie de secours de la maison.
        destination TEXT NOT NULL CHECK (destination IN ('culture', 'secours')),
        -- cycle : objet = numéro du cycle ; fichier : objet = chemin relatif au dossier
        -- des données (un fichier ou un dossier).
        sorte TEXT NOT NULL CHECK (sorte IN ('cycle', 'fichier')),
        objet TEXT NOT NULL,
        cree_le TEXT NOT NULL,
        -- attente : à envoyer ; envoye : reçu par le destinataire ; refuse : le destinataire
        -- dit que les données sont fausses (on ne réessaie plus tout seul).
        statut TEXT NOT NULL DEFAULT 'attente' CHECK (statut IN ('attente', 'envoye', 'refuse')),
        essais INTEGER NOT NULL DEFAULT 0,
        dernier_essai TEXT,
        derniere_erreur TEXT,
        envoye_le TEXT
    )
    """,
    "CREATE INDEX envois_statut ON envois (statut, destination)",
)

# Montée n° i (en partant de 1) : ce qui fait passer la base de la version i - 1 à la version i.
MONTEES: tuple[tuple[str, ...], ...] = (_VERSION_1, _VERSION_2, _VERSION_3)

VERSION = len(MONTEES)
