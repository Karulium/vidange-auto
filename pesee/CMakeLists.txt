# Programme des cartes de pesée RP2040 + HX711, fabriqué avec le Pico SDK de Raspberry Pi.
# Voir README.md (« Fabriquer le programme »). Donne un fichier par carte, à copier par l'USB :
# pesee_griffe.uf2, pesee_prehension.uf2, pesee_plateau_remplissage.uf2 (le même programme,
# chacun avec l'adresse de sa carte sur le bus).
cmake_minimum_required(VERSION 3.13)

include(reglages.cmake)  # avant le Pico SDK : il choisit la carte (PICO_BOARD)

if(NOT DEFINED PICO_SDK_PATH)
  set(PICO_SDK_PATH "$ENV{PICO_SDK_PATH}")
endif()
if(NOT EXISTS "${PICO_SDK_PATH}/pico_sdk_init.cmake")
  message(FATAL_ERROR "Pico SDK introuvable : donner son dossier dans PICO_SDK_PATH.")
endif()
include("${PICO_SDK_PATH}/pico_sdk_init.cmake")

project(pesee C CXX ASM)
set(CMAKE_C_STANDARD 11)
pico_sdk_init()

# Nom de version : le commit Git (« -modifie » s'il y avait des changements pas enregistrés).
execute_process(
  COMMAND git describe --always --dirty=-modifie
  WORKING_DIRECTORY "${CMAKE_CURRENT_LIST_DIR}"
  OUTPUT_VARIABLE VERSION_GIT
  OUTPUT_STRIP_TRAILING_WHITESPACE
  ERROR_QUIET)
if(NOT VERSION_GIT)
  set(VERSION_GIT "inconnue")
endif()

# Un programme par carte : CARTES_PESEE = nom;adresse;nom;adresse...
list(LENGTH CARTES_PESEE TAILLE)
math(EXPR DERNIER "${TAILLE} - 1")
foreach(I RANGE 0 ${DERNIER} 2)
  math(EXPR J "${I} + 1")
  list(GET CARTES_PESEE ${I} NOM)
  list(GET CARTES_PESEE ${J} ADRESSE)
  add_executable(${NOM}
    src/main.c
    src/hx711.c
    src/mesures.c
    src/modbus.c
    src/pca9685.c
    src/vl6180x.c
    src/plateau.c)
  target_include_directories(${NOM} PRIVATE src "${DOSSIER_GENERE}")
  target_compile_options(${NOM} PRIVATE -Wall -Wextra)
  # L'I2C (servos et capteur de distance) : la carte de CARTE_PESEE_I2C seulement.
  if(NOM STREQUAL CARTE_PESEE_I2C)
    set(AVEC_I2C 1)
  else()
    set(AVEC_I2C 0)
  endif()
  target_compile_definitions(${NOM} PRIVATE
    REGLAGE_AVEC_I2C=${AVEC_I2C}
    REGLAGE_ADRESSE=${ADRESSE}
    REGLAGE_NOM="${NOM}"
    REGLAGE_VERSION="${VERSION_GIT}")
  target_link_libraries(${NOM}
    pico_stdlib
    pico_multicore
    pico_sync
    hardware_uart
    hardware_i2c
    pico_rand
    hardware_watchdog)
  # Fenêtre texte par l'USB (le bus RS485 passe par l'UART).
  pico_enable_stdio_usb(${NOM} 1)
  pico_enable_stdio_uart(${NOM} 0)
  pico_add_extra_outputs(${NOM})
endforeach()
