# Le code commun aux 2 programmes, sans matériel (essayé sur PC : tests/). Composant ESP-IDF
# « commun », pris par plateau/ et boite/. Le HX711 et le Modbus sont ceux des cartes de pesée
# RP2040 (pesee/src/) : le même code, pas une copie.
idf_component_register(
  SRCS
    "trame.c"
    "accu.c"
    "plateau.c"
    "boite.c"
    "../../pesee/src/hx711.c"
    "../../pesee/src/modbus.c"
  INCLUDE_DIRS "." "../../pesee/src")
target_compile_options(${COMPONENT_LIB} PRIVATE -Wall -Wextra -Werror)
