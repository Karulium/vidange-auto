# Copie les réglages de pi/reglages/pesees.yaml (section poste_fut_radio) et l'adresse de la boîte
# du poste de docs/entrees-sorties.yaml (pesee_fut) dans le programme (reglages_radio.h), et donne
# le nom de version (le commit Git). Lu par plateau/CMakeLists.txt et boite/CMakeLists.txt, avant
# ESP-IDF.
#
# Les fichiers sont vérifiés par le programme du Pi (dossier pi/, avec pydantic et PyYAML) : une
# erreur arrête la fabrication avec le même message en français qu'au démarrage du Pi.

set(FICHIER_REGLAGES "${CMAKE_CURRENT_LIST_DIR}/../pi/reglages/pesees.yaml"
    CACHE FILEPATH "Fichier de réglages des pesées (section poste_fut_radio)")
set(FICHIER_ENTREES_SORTIES "${CMAKE_CURRENT_LIST_DIR}/../docs/entrees-sorties.yaml"
    CACHE FILEPATH "Liste des entrées/sorties (adresse de la boîte du poste du fût)")
set(DOSSIER_GENERE "${CMAKE_BINARY_DIR}/genere")

find_program(PYTHON NAMES python3 python)
if(NOT PYTHON)
  message(FATAL_ERROR "Python 3 est nécessaire pour lire les réglages du poste du fût.")
endif()

execute_process(
  COMMAND "${CMAKE_COMMAND}" -E env "PYTHONPATH=${CMAKE_CURRENT_LIST_DIR}/../pi"
          "${PYTHON}" -m vidange.pesees.entete_radio "${FICHIER_REGLAGES}"
          "${FICHIER_ENTREES_SORTIES}" "${DOSSIER_GENERE}"
  RESULT_VARIABLE RESULTAT_REGLAGES
  ERROR_VARIABLE ERREUR_REGLAGES)
if(NOT RESULTAT_REGLAGES EQUAL 0)
  message(FATAL_ERROR "${ERREUR_REGLAGES}")
endif()

# Refaire la copie quand un des deux fichiers change.
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
  "${FICHIER_REGLAGES}" "${FICHIER_ENTREES_SORTIES}")

# Nom de version : le commit Git (« -modifie » s'il y avait des changements pas enregistrés). La
# carte le dit dans sa fenêtre USB.
execute_process(
  COMMAND git describe --always --dirty=-modifie
  WORKING_DIRECTORY "${CMAKE_CURRENT_LIST_DIR}"
  OUTPUT_VARIABLE VERSION_GIT
  OUTPUT_STRIP_TRAILING_WHITESPACE
  ERROR_QUIET)
if(NOT VERSION_GIT)
  set(VERSION_GIT "inconnue")
endif()
# ESP-IDF met ce nom dans le programme (esp_app_get_description()->version).
set(PROJECT_VER "${VERSION_GIT}")
