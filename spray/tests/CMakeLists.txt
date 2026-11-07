# Essais du programme de la carte du spray sur PC (sans ESP32-S3, ni moteurs, ni HX711, ni
# capteur) : faux moteurs et faux bras, faux HX711 (celui de poste_fut_radio/tests), fausses
# balances, questions Modbus écrites à la main.
#   cmake -S spray/tests -B spray/build-essais
#   cmake --build spray/build-essais
#   ctest --test-dir spray/build-essais --output-on-failure
cmake_minimum_required(VERSION 3.13)
project(essais_spray C)
set(CMAKE_C_STANDARD 11)

add_executable(essais
  essais.c
  monde.c
  essais_moteur.c
  essais_balance.c
  essais_tmc2209.c
  essais_spray.c
  essais_bus.c
  ../../poste_fut_radio/tests/faux_hx711.c
  ../commun/moteur.c
  ../commun/balance.c
  ../commun/tmc2209.c
  ../commun/spray.c
  ../../pesee/src/hx711.c
  ../../pesee/src/modbus.c)
target_include_directories(essais PRIVATE . ../commun ../../pesee/src ../../poste_fut_radio/tests)
target_compile_options(essais PRIVATE -Wall -Wextra -Werror -fsanitize=address,undefined)
target_link_options(essais PRIVATE -fsanitize=address,undefined)

enable_testing()
add_test(NAME essais COMMAND essais)
