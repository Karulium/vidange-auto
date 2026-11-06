# Programme de la boîte du poste du fût (ESP32-C3 + MAX3485, sur le bus des pesées),
# fabriqué avec ESP-IDF (voir ../README.md, « Fabriquer les programmes »).
cmake_minimum_required(VERSION 3.16)

# Avant ESP-IDF : réglages copiés de pesees.yaml (reglages_radio.h) et nom de version.
include("${CMAKE_CURRENT_LIST_DIR}/../reglages.cmake")
# Le code commun aux 2 programmes (essayé sur PC).
set(EXTRA_COMPONENT_DIRS "${CMAKE_CURRENT_LIST_DIR}/../commun")
# Seulement ce qui sert (programme plus petit, fabrication plus rapide).
set(COMPONENTS main)

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(boite_poste_fut)
