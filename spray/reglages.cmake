# Copie les réglages du spray (pi/reglages/machine.yaml → spray, pesees.yaml → balances_spray) et
# l'adresse de la carte (docs/entrees-sorties.yaml : carte_spray, rs485_spray) dans le programme
# (reglages_spray.h), et donne le nom de version (le commit Git). Lu par carte/CMakeLists.txt,
# avant ESP-IDF.
#
# Les fichiers sont vérifiés par le programme du Pi (dossier pi/, avec pydantic et PyYAML) : une
# erreur arrête la fabrication avec le même message en français qu'au démarrage du Pi.

set(DOSSIER_REGLAGES "${CMAKE_CURRENT_LIST_DIR}/../pi/reglages"
    CACHE PATH "Dossier des réglages du Pi (machine.yaml, pesees.yaml...)")
set(FICHIER_ENTREES_SORTIES "${CMAKE_CURRENT_LIST_DIR}/../docs/entrees-sorties.yaml"
    CACHE FILEPATH "Liste des entrées/sorties (adresse de la carte du spray)")
set(DOSSIER_GENERE "${CMAKE_BINARY_DIR}/genere")

find_program(PYTHON NAMES python3 python)
if(NOT PYTHON)
  message(FATAL_ERROR "Python 3 est nécessaire pour lire les réglages du spray.")
endif()

execute_process(
  COMMAND "${CMAKE_COMMAND}" -E env "PYTHONPATH=${CMAKE_CURRENT_LIST_DIR}/../pi"
          "${PYTHON}" -m vidange.entete_spray "${DOSSIER_REGLAGES}"
          "${FICHIER_ENTREES_SORTIES}" "${DOSSIER_GENERE}"
  RESULT_VARIABLE RESULTAT_REGLAGES
  ERROR_VARIABLE ERREUR_REGLAGES)
if(NOT RESULTAT_REGLAGES EQUAL 0)
  message(FATAL_ERROR "${ERREUR_REGLAGES}")
endif()

# Refaire la copie quand un des fichiers change.
file(GLOB FICHIERS_REGLAGES "${DOSSIER_REGLAGES}/*.yaml")
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
  ${FICHIERS_REGLAGES} "${FICHIER_ENTREES_SORTIES}")

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
