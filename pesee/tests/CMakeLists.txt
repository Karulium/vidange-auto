# Essais du programme des cartes de pesée sur PC (sans RP2040 ni HX711) :
#   cmake -S pesee/tests -B pesee/build-essais && cmake --build pesee/build-essais
#   ctest --test-dir pesee/build-essais --output-on-failure
cmake_minimum_required(VERSION 3.13)
project(essais_pesee C)
set(CMAKE_C_STANDARD 11)

add_executable(essais
  essais.c
  essais_hx711.c
  essais_modbus.c
  essais_mesures.c
  essais_i2c.c
  essais_plateau.c
  essais_rythme.c
  faux_i2c.c
  ../src/hx711.c
  ../src/modbus.c
  ../src/mesures.c
  ../src/pca9685.c
  ../src/vl6180x.c
  ../src/plateau.c)
target_include_directories(essais PRIVATE . ../src)
target_compile_options(essais PRIVATE -Wall -Wextra -Werror -fsanitize=address,undefined)
target_link_options(essais PRIVATE -fsanitize=address,undefined)

enable_testing()
add_test(NAME essais COMMAND essais)
