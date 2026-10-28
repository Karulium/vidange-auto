# Programme du RP2040 de l'accéléromètre, fabriqué avec le Pico SDK de Raspberry Pi.
# Voir README.md (« Fabriquer le programme »). Donne accelerometre.uf2.
cmake_minimum_required(VERSION 3.13)

include(reglages.cmake)  # avant le Pico SDK : il choisit la carte (PICO_BOARD)

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

add_executable(accelerometre
  src/main.c
  src/detecteur.c
  src/lis3dh.c
  src/reglages.c
  src/console.c
  src/liaison.c
  src/un_fil.c)
# Le fil série unique vers le Pi (deux petites machines PIO).
pico_generate_pio_header(accelerometre ${CMAKE_CURRENT_LIST_DIR}/src/un_fil.pio)
target_include_directories(accelerometre PRIVATE src "${DOSSIER_GENERE}")
target_compile_options(accelerometre PRIVATE -Wall -Wextra)
target_link_libraries(accelerometre
  pico_stdlib
  pico_multicore
  pico_sync
  hardware_i2c
  hardware_pio
  hardware_watchdog)

# Fenêtre texte par l'USB (le fil vers le Pi passe par une broche PIO, voir src/un_fil.pio).
pico_enable_stdio_usb(accelerometre 1)
pico_enable_stdio_uart(accelerometre 0)
pico_add_extra_outputs(accelerometre)
