# Copie les réglages de pi/reglages/pesees.yaml et de docs/entrees-sorties.yaml dans le
# programme (reglages_genere.h), donne la carte au Pico SDK (PICO_BOARD) et la liste des cartes
# avec leur adresse (CARTES_PESEE). Lu par CMakeLists.txt et tests/CMakeLists.txt.
#
# Les fichiers sont vérifiés par le programme du Pi (dossier pi/, avec pydantic et PyYAML) :
# une erreur arrête la fabrication avec le même message en français qu'au démarrage du Pi.

set(FICHIER_REGLAGES "${CMAKE_CURRENT_LIST_DIR}/../pi/reglages/pesees.yaml"
    CACHE FILEPATH "Fichier de réglages des cartes de pesée")
set(FICHIER_ENTREES_SORTIES "${CMAKE_CURRENT_LIST_DIR}/../docs/entrees-sorties.yaml"
    CACHE FILEPATH "Liste des entrées/sorties (adresses des cartes de pesée)")
set(DOSSIER_GENERE "${CMAKE_BINARY_DIR}/genere")

find_program(PYTHON NAMES python3 python)
if(NOT PYTHON)
  message(FATAL_ERROR "Python 3 est nécessaire pour lire les réglages des cartes de pesée.")
endif()

execute_process(
  COMMAND "${CMAKE_COMMAND}" -E env "PYTHONPATH=${CMAKE_CURRENT_LIST_DIR}/../pi"
          "${PYTHON}" -m vidange.pesees.entete "${FICHIER_REGLAGES}"
          "${FICHIER_ENTREES_SORTIES}" "${DOSSIER_GENERE}"
  RESULT_VARIABLE RESULTAT_REGLAGES
  ERROR_VARIABLE ERREUR_REGLAGES)
if(NOT RESULTAT_REGLAGES EQUAL 0)
  message(FATAL_ERROR "${ERREUR_REGLAGES}")
endif()

# Refaire la copie quand un des deux fichiers change.
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
  "${FICHIER_REGLAGES}" "${FICHIER_ENTREES_SORTIES}")
include("${DOSSIER_GENERE}/reglages_genere.cmake")
