# Le code de la carte du spray sans matériel (essayé sur PC : tests/). Composant ESP-IDF
# « commun », pris par carte/. Le HX711 et le Modbus sont ceux des cartes de pesée RP2040
# (pesee/src/) : le même code, pas une copie.
idf_component_register(
  SRCS
    "moteur.c"
    "balance.c"
    "tmc2209.c"
    "spray.c"
    "../../pesee/src/hx711.c"
    "../../pesee/src/modbus.c"
  INCLUDE_DIRS "." "../../pesee/src")
target_compile_options(${COMPONENT_LIB} PRIVATE -Wall -Wextra -Werror)
