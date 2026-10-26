# Programme du RP2040 (accéléromètre LIS3DH)

Détecte les chocs horizontaux sur le chariot Z. Coupe un signal « OK » en sécurité positive vers l'ESP32 n° 1 et envoie la mesure au Pi par liaison série (3,3 V, 115 200). Voir la tâche correspondante dans `docs/taches.md`.
