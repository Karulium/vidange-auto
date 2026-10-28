# Copie les réglages de pi/reglages/accelerometre.yaml dans le programme (reglages_genere.h)
# et donne la carte au Pico SDK (PICO_BOARD). Lu par CMakeLists.txt et tests/CMakeLists.txt.
#
# Le fichier est vérifié par le programme du Pi (dossier pi/, avec pydantic et PyYAML) :
# une erreur arrête la fabrication avec le même message en français qu'au démarrage du Pi.

set(FICHIER_REGLAGES "${CMAKE_CURRENT_LIST_DIR}/../pi/reglages/accelerometre.yaml"
    CACHE FILEPATH "Fichier de réglages de l'accéléromètre")
set(DOSSIER_GENERE "${CMAKE_BINARY_DIR}/genere")

find_program(PYTHON NAMES python3 python)
if(NOT PYTHON)
  message(FATAL_ERROR "Python 3 est nécessaire pour lire les réglages de l'accéléromètre.")
endif()

execute_process(
  COMMAND "${CMAKE_COMMAND}" -E env "PYTHONPATH=${CMAKE_CURRENT_LIST_DIR}/../pi"
          "${PYTHON}" -m vidange.accelerometre.entete "${FICHIER_REGLAGES}" "${DOSSIER_GENERE}"
  RESULT_VARIABLE RESULTAT_REGLAGES
  ERROR_VARIABLE ERREUR_REGLAGES)
if(NOT RESULTAT_REGLAGES EQUAL 0)
  message(FATAL_ERROR "${ERREUR_REGLAGES}")
endif()

# Refaire la copie quand le fichier de réglages change.
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS "${FICHIER_REGLAGES}")
include("${DOSSIER_GENERE}/reglages_genere.cmake")
