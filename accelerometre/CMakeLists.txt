# Programme du RP2040 de l'accéléromètre, fabriqué avec le Pico SDK de Raspberry Pi.
# Voir README.md (« Fabriquer le programme »). Donne accelerometre-complet.uf2 (pour l'USB) et
# accelerometre.bin (pour la mise à jour par le Pi).
cmake_minimum_required(VERSION 3.13)

include(reglages.cmake)  # avant le Pico SDK : il choisit la carte (PICO_BOARD)
include(plan_memoire.cmake)

if(NOT DEFINED PICO_SDK_PATH)
  set(PICO_SDK_PATH "$ENV{PICO_SDK_PATH}")
endif()
if(NOT EXISTS "${PICO_SDK_PATH}/pico_sdk_init.cmake")
  message(FATAL_ERROR "Pico SDK introuvable : donner son dossier dans PICO_SDK_PATH.")
endif()
include("${PICO_SDK_PATH}/pico_sdk_init.cmake")

project(accelerometre C CXX ASM)
set(CMAKE_C_STANDARD 11)
pico_sdk_init()

# Taille de la flash de la carte (donnée par le Pico SDK d'après PICO_BOARD).
if(PICO_FLASH_SIZE_BYTES)
  set(TAILLE_FLASH "${PICO_FLASH_SIZE_BYTES}")
else()
  set(TAILLE_FLASH "${PICO_DEFAULT_FLASH_SIZE_BYTES}")
endif()

# Le plan de la flash (plan_memoire.cmake) dans deux copies du fichier d'édition de liens du
# Pico SDK : le chargeur au début, le programme après la fiche.
set(MEMMAP_SDK "${PICO_SDK_PATH}/src/rp2_common/pico_crt0/rp2040/memmap_default.ld")
file(READ "${MEMMAP_SDK}" MEMMAP)
set(REGION_FLASH "INCLUDE \"pico_flash_region.ld\"")
string(FIND "${MEMMAP}" "${REGION_FLASH}" TROUVE)
if(TROUVE EQUAL -1)
  message(FATAL_ERROR "${MEMMAP_SDK} : « ${REGION_FLASH} » introuvable (autre version du SDK ?)")
endif()
string(REPLACE "${REGION_FLASH}"
  "FLASH(rx) : ORIGIN = ${PLAN_ADRESSE_FLASH}, LENGTH = ${PLAN_TAILLE_CHARGEUR}"
  MEMMAP_CHARGEUR "${MEMMAP}")
string(REPLACE "${REGION_FLASH}"
  "FLASH(rx) : ORIGIN = ${PLAN_ADRESSE_PROGRAMME}, LENGTH = (${TAILLE_FLASH}) - (${PLAN_ADRESSE_PROGRAMME} - ${PLAN_ADRESSE_FLASH})"
  MEMMAP_PROGRAMME "${MEMMAP}")
file(WRITE "${CMAKE_BINARY_DIR}/memmap_chargeur.ld" "${MEMMAP_CHARGEUR}")
file(WRITE "${CMAKE_BINARY_DIR}/memmap_programme.ld" "${MEMMAP_PROGRAMME}")
set(PLAN_DEFINITIONS
  PLAN_ADRESSE_FICHE=${PLAN_ADRESSE_FICHE}
  PLAN_ADRESSE_PROGRAMME=${PLAN_ADRESSE_PROGRAMME})

# ------------------------------------------------------------------ le programme
add_executable(programme
  src/main.c
  src/detecteur.c
  src/lis3dh.c
  src/reglages.c
  src/console.c
  src/liaison.c
  src/liaison_trame.c
  src/fiche.c
  src/un_fil.c)
# Le fil série unique vers le Pi (deux petites machines PIO).
pico_generate_pio_header(programme ${CMAKE_CURRENT_LIST_DIR}/src/un_fil.pio)
target_include_directories(programme PRIVATE src "${DOSSIER_GENERE}")
target_compile_options(programme PRIVATE -Wall -Wextra)
target_compile_definitions(programme PRIVATE ${PLAN_DEFINITIONS})
target_link_libraries(programme
  pico_stdlib
  pico_multicore
  pico_sync
  hardware_i2c
  hardware_pio
  hardware_watchdog)
pico_set_linker_script(programme "${CMAKE_BINARY_DIR}/memmap_programme.ld")
# Fenêtre texte par l'USB (le fil vers le Pi passe par une broche PIO, voir src/un_fil.pio).
pico_enable_stdio_usb(programme 1)
pico_enable_stdio_uart(programme 0)
pico_add_bin_output(programme)

# ------------------------------------------------------------------ le chargeur
add_executable(chargeur
  src/chargeur.c
  src/chargeur_protocole.c
  src/liaison_trame.c
  src/fiche.c
  src/un_fil.c)
pico_generate_pio_header(chargeur ${CMAKE_CURRENT_LIST_DIR}/src/un_fil.pio)
target_include_directories(chargeur PRIVATE src "${DOSSIER_GENERE}")
target_compile_options(chargeur PRIVATE -Wall -Wextra)
target_compile_definitions(chargeur PRIVATE ${PLAN_DEFINITIONS})
target_link_libraries(chargeur
  pico_stdlib
  hardware_flash
  hardware_pio
  hardware_watchdog)
pico_set_linker_script(chargeur "${CMAKE_BINARY_DIR}/memmap_chargeur.ld")
pico_enable_stdio_usb(chargeur 0)
pico_enable_stdio_uart(chargeur 0)
pico_add_bin_output(chargeur)

# ------------------------------------------------------------------ les fichiers à livrer
# accelerometre.bin : la fiche et le programme, que le Pi envoie par le fil (mise à jour).
# accelerometre-complet.uf2 : chargeur, fiche et programme, à copier par l'USB (première fois,
# ou secours). Fabriqués par pi/vidange/accelerometre/fichier_programme.py.
add_custom_command(
  OUTPUT accelerometre.bin accelerometre-complet.uf2
  COMMAND "${CMAKE_COMMAND}" -E env "PYTHONPATH=${CMAKE_CURRENT_LIST_DIR}/../pi"
          "${PYTHON}" -m vidange.accelerometre.fichier_programme
          --chargeur chargeur.bin
          --programme programme.bin
          --adresse-flash ${PLAN_ADRESSE_FLASH}
          --adresse-fiche ${PLAN_ADRESSE_FICHE}
          --adresse-programme ${PLAN_ADRESSE_PROGRAMME}
          --depot "${CMAKE_CURRENT_LIST_DIR}"
          --sortie-bin accelerometre.bin
          --sortie-uf2 accelerometre-complet.uf2
  DEPENDS chargeur programme "${CMAKE_CURRENT_LIST_DIR}/../pi/vidange/accelerometre/fichier_programme.py"
  WORKING_DIRECTORY "${CMAKE_BINARY_DIR}"
  VERBATIM)
add_custom_target(accelerometre ALL DEPENDS accelerometre.bin accelerometre-complet.uf2)
