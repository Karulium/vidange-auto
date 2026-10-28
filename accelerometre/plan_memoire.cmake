# Plan de la flash du RP2040 (tâche 16), lu par CMakeLists.txt :
#   - au début, le chargeur (avec le « boot2 » du Pico SDK), jamais réécrit par le fil ;
#   - puis un secteur de 4 Kio pour la fiche du programme (taille, contrôle, nom : src/fiche.h) ;
#   - puis le programme, jusqu'à la fin de la flash.
# Changer ces adresses demande de réinstaller le chargeur par l'USB (accelerometre-complet.uf2).

set(PLAN_ADRESSE_FLASH 0x10000000)
set(PLAN_TAILLE_CHARGEUR 0x8000)  # 32 Kio
math(EXPR PLAN_ADRESSE_FICHE "${PLAN_ADRESSE_FLASH} + ${PLAN_TAILLE_CHARGEUR}"
     OUTPUT_FORMAT HEXADECIMAL)
math(EXPR PLAN_ADRESSE_PROGRAMME "${PLAN_ADRESSE_FICHE} + 0x1000" OUTPUT_FORMAT HEXADECIMAL)
