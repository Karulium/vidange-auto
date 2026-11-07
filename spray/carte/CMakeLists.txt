# Programme de la carte ESP32 n° 5 du spray (ESP32-S3 + MAX3485, sur le bus rs485_spray),
# fabriqué avec ESP-IDF (voir ../README.md, « Fabriquer le programme »).
cmake_minimum_required(VERSION 3.16)

# Avant ESP-IDF : réglages copiés de machine.yaml et pesees.yaml (reglages_spray.h) et nom de
# version.
include("${CMAKE_CURRENT_LIST_DIR}/../reglages.cmake")
# Le code essayé sur PC.
set(EXTRA_COMPONENT_DIRS "${CMAKE_CURRENT_LIST_DIR}/../commun")
# Seulement ce qui sert (programme plus petit, fabrication plus rapide).
set(COMPONENTS main)

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(carte_spray)
