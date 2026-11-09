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

# Version 4 (tâche 12) : le journal du pilotage à distance (qui, quand, quoi).
_VERSION_4 = (
    """
    CREATE TABLE actions_distance (
        id INTEGER PRIMARY KEY,
        quand TEXT NOT NULL,
        -- D'où vient l'action : « page web (100.101.102.103) », « écran de l'armoire »...
        qui TEXT NOT NULL,
        -- activer, quitter, mouvement, arret, refus, reprise_sur_place.
        action TEXT NOT NULL,
        -- En clair : axe et sens, position d'arrivée, raison de l'arrêt ou du refus...
        detail TEXT
    )
    """,
    "CREATE INDEX actions_distance_quand ON actions_distance (quand)",
)

# Version 5 (tâche 18) : chaque prise de la griffe, pour apprendre les doses (densité du fût,
# corrections près de la paroi et du fond) et pour les essais.
_VERSION_5 = (
    """
    CREATE TABLE prises_griffe (
        id INTEGER PRIMARY KEY,
        quand TEXT NOT NULL,
        cycle_id INTEGER REFERENCES cycles (id),
        fut_id INTEGER REFERENCES futs (id),
        -- couche, paroi, fond.
        lieu TEXT NOT NULL,
        -- Ouverture du godet (0 fermé, 1 grand ouvert), enfoncement (m), nombre de bouchées.
        ouverture REAL NOT NULL,
        enfoncement_m REAL NOT NULL,
        bouchees INTEGER NOT NULL,
        -- Niveau du substrat (bas du godet au contact, m) et position du mât dans le fût (m).
        niveau_z REAL,
        x REAL NOT NULL,
        y REAL NOT NULL,
        -- Poids pesé (kg) et volume d'après la table (L).
        poids_kg REAL NOT NULL,
        volume_l REAL NOT NULL
    )
    """,
    "CREATE INDEX prises_griffe_cycle ON prises_griffe (cycle_id)",
)

# Version 6 (tâche 19) : le mycélium. Chaque dose dit sa couche ; un bocal garde sa variété (un
# bocal ne sert 2 petits seaux que de la même variété) ; un seau mal dosé (bocal vide, cassé...)
# garde la raison de son défaut (vide : seau bon).
_VERSION_6 = (
    "ALTER TABLE doses_mycelium ADD COLUMN couche INTEGER",
    "ALTER TABLE bocaux ADD COLUMN variete TEXT",
    "ALTER TABLE seaux ADD COLUMN defaut TEXT",
)

# Version 7 (tâche 22) : un objet dont le QR est resté illisible (ou que la vision a trouvé
# douteux) garde la raison pour laquelle il est « à vérifier » (vide : rien à vérifier).
_VERSION_7 = (
    "ALTER TABLE futs ADD COLUMN a_verifier TEXT",
    "ALTER TABLE seaux ADD COLUMN a_verifier TEXT",
    "ALTER TABLE bocaux ADD COLUMN a_verifier TEXT",
)

# Version 8 (tâche 35) : l'inventaire du Stockage, qui n'a aucun capteur de présence. Une ligne
# par place (pile_1, file_2, bocal_3_4, boite_capsules_enlevees...) : ce qu'il y a (format du
# seau, sorte de bocal ; vide : rien de plus à dire) et combien.
_VERSION_8 = (
    """
    CREATE TABLE inventaire_stockage (
        place TEXT PRIMARY KEY,
        contenu TEXT,
        nombre INTEGER NOT NULL CHECK (nombre >= 0),
        modifie_le TEXT NOT NULL
    )
    """,
)

# Version 9 (tâche 27) : notifications sur le téléphone.
# - une alarme peut être « vue » (bouton « J'ai vu » de la page web) sans être acquittée ;
# - la file d'envoi accepte des messages (destinations « ntfy » et « telegram », sorte « message »,
#   texte et niveau dans « contenu », en JSON) : SQLite ne change pas un CHECK, la table est
#   refaite ;
# - « notifications_faites » : ce que le notificateur a déjà traité (envoyé, ou volontairement
#   laissé de côté), pour ne jamais envoyer deux fois la même chose, même après un redémarrage.
#   Ce qui existe déjà au moment de la montée est marqué comme traité (pas de rafale de vieux
#   messages).
_VERSION_9 = (
    "ALTER TABLE alarmes ADD COLUMN vue_le TEXT",
    "ALTER TABLE alarmes ADD COLUMN vue_par TEXT",
    """
    CREATE TABLE envois_neuf (
        id INTEGER PRIMARY KEY,
        cle TEXT NOT NULL UNIQUE,
        -- culture : logiciel de culture (Django) ; secours : copie de secours de la maison ;
        -- ntfy, telegram : messages pour le téléphone.
        destination TEXT NOT NULL
            CHECK (destination IN ('culture', 'secours', 'ntfy', 'telegram')),
        -- cycle : objet = numéro du cycle ; fichier : objet = chemin relatif au dossier des
        -- données ; message : objet = nom de ce qui est annoncé (« alarme:12 »...).
        sorte TEXT NOT NULL CHECK (sorte IN ('cycle', 'fichier', 'message')),
        objet TEXT NOT NULL,
        cree_le TEXT NOT NULL,
        statut TEXT NOT NULL DEFAULT 'attente' CHECK (statut IN ('attente', 'envoye', 'refuse')),
        essais INTEGER NOT NULL DEFAULT 0,
        dernier_essai TEXT,
        derniere_erreur TEXT,
        envoye_le TEXT,
        -- Sorte « message » : titre, texte, niveau, groupe de destinataires... en JSON.
        contenu TEXT
    )
    """,
    "INSERT INTO envois_neuf (id, cle, destination, sorte, objet, cree_le, statut, essais, "
    "dernier_essai, derniere_erreur, envoye_le) SELECT id, cle, destination, sorte, objet, "
    "cree_le, statut, essais, dernier_essai, derniere_erreur, envoye_le FROM envois",
    "DROP TABLE envois",
    "ALTER TABLE envois_neuf RENAME TO envois",
    "CREATE INDEX envois_statut ON envois (statut, destination)",
    """
    CREATE TABLE notifications_faites (
        cle TEXT PRIMARY KEY,
        quand TEXT NOT NULL
    )
    """,
    "INSERT INTO notifications_faites (cle, quand) SELECT 'alarme:' || id, quand FROM alarmes",
    "INSERT INTO notifications_faites (cle, quand) SELECT 'fut:' || id, fin FROM cycles "
    "WHERE fin IS NOT NULL",
    "INSERT INTO notifications_faites (cle, quand) SELECT 'nettoyage:' || id, fin FROM cycles "
    "WHERE fin IS NOT NULL",
)

# Version 10 (tâche 28 bis) : le carnet de bord, des notes libres datées écrites depuis la page web.
# Une note se rattache, si on veut, à un cycle (un « lot »), à un seau ou à une alarme. Une note ne
# se supprime jamais et son texte ne change jamais : on la BARRE (qui, quand, pourquoi), et on en
# écrit une autre si besoin. Les déclencheurs ci-dessous l'imposent à la base elle-même.
_VERSION_10 = (
    """
    CREATE TABLE carnet_de_bord (
        id INTEGER PRIMARY KEY,
        quand TEXT NOT NULL,
        auteur TEXT NOT NULL,
        texte TEXT NOT NULL CHECK (length(trim(texte)) > 0),
        cycle_id INTEGER REFERENCES cycles (id),
        seau_id INTEGER REFERENCES seaux (id),
        alarme_id INTEGER REFERENCES alarmes (id),
        barre_le TEXT,
        barre_par TEXT,
        barre_raison TEXT
    )
    """,
    "CREATE INDEX carnet_de_bord_quand ON carnet_de_bord (quand)",
    """
    CREATE TRIGGER carnet_de_bord_pas_de_suppression BEFORE DELETE ON carnet_de_bord
    BEGIN
        SELECT RAISE(ABORT, 'une note du carnet de bord ne se supprime pas : on la barre');
    END
    """,
    """
    CREATE TRIGGER carnet_de_bord_pas_de_modification
    BEFORE UPDATE OF quand, auteur, texte, cycle_id, seau_id, alarme_id ON carnet_de_bord
    BEGIN
        SELECT RAISE(ABORT, 'une note du carnet de bord ne se modifie pas : on la barre');
    END
    """,
    """
    CREATE TRIGGER carnet_de_bord_barree_une_fois
    BEFORE UPDATE OF barre_le, barre_par, barre_raison ON carnet_de_bord
    WHEN OLD.barre_le IS NOT NULL
    BEGIN
        SELECT RAISE(ABORT, 'cette note est déjà barrée');
    END
    """,
)

# Montée n° i (en partant de 1) : ce qui fait passer la base de la version i - 1 à la version i.
MONTEES: tuple[tuple[str, ...], ...] = (
    _VERSION_1,
    _VERSION_2,
    _VERSION_3,
    _VERSION_4,
    _VERSION_5,
    _VERSION_6,
    _VERSION_7,
    _VERSION_8,
    _VERSION_9,
    _VERSION_10,
)

VERSION = len(MONTEES)
