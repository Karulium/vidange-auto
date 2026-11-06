# Essais des programmes du poste du fût sur PC (sans ESP32-C3, ni HX711, ni radio) : faux HX711,
# fausses trames radio, questions Modbus.
#   cmake -S poste_fut_radio/tests -B poste_fut_radio/build-essais
#   cmake --build poste_fut_radio/build-essais
#   ctest --test-dir poste_fut_radio/build-essais --output-on-failure
cmake_minimum_required(VERSION 3.13)
project(essais_poste_fut_radio C)
set(CMAKE_C_STANDARD 11)

add_executable(essais
  essais.c
  faux_hx711.c
  essais_trame.c
  essais_accu.c
  essais_plateau.c
  essais_boite.c
  essais_chaine.c
  ../commun/trame.c
  ../commun/accu.c
  ../commun/plateau.c
  ../commun/boite.c
  ../../pesee/src/hx711.c
  ../../pesee/src/modbus.c)
target_include_directories(essais PRIVATE . ../commun ../../pesee/src)
target_compile_options(essais PRIVATE -Wall -Wextra -Werror -fsanitize=address,undefined)
target_link_options(essais PRIVATE -fsanitize=address,undefined)

enable_testing()
add_test(NAME essais COMMAND essais)
