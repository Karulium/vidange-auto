# Essais du programme de l'accéléromètre sur PC (sans RP2040 ni capteur) :
#   cmake -S accelerometre/tests -B build-essais && cmake --build build-essais
#   ctest --test-dir build-essais --output-on-failure
cmake_minimum_required(VERSION 3.13)
project(essais_accelerometre C)
set(CMAKE_C_STANDARD 11)

include(../reglages.cmake)

add_executable(essais
  essais.c
  essais_reglages.c
  essais_lis3dh.c
  essais_detecteur.c
  essais_console.c
  faux_lis3dh.c
  ../src/detecteur.c
  ../src/lis3dh.c
  ../src/reglages.c
  ../src/console.c)
target_include_directories(essais PRIVATE . ../src "${DOSSIER_GENERE}")
target_compile_options(essais PRIVATE -Wall -Wextra -Werror -fsanitize=address,undefined)
target_link_options(essais PRIVATE -fsanitize=address,undefined)
target_link_libraries(essais PRIVATE m)

enable_testing()
add_test(NAME essais COMMAND essais)
