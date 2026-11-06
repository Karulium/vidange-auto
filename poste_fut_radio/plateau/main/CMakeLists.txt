idf_build_get_property(DOSSIER_FABRICATION BUILD_DIR)
idf_component_register(
  SRCS "main.c"
  INCLUDE_DIRS "${DOSSIER_FABRICATION}/genere"
  REQUIRES commun esp_wifi esp_driver_gpio esp_driver_uart esp_adc esp_timer nvs_flash
           esp_app_format esp_hw_support)
target_compile_options(${COMPONENT_LIB} PRIVATE -Wall -Wextra -Werror)
