#!/usr/bin/env bash
# Remet un Raspberry Pi 5 NEUF (Raspberry Pi OS Bookworm 64 bits) en état, depuis la copie de secours.
#
#   sudo bash /opt/vidange-auto/pi/systeme/restaurer.sh [--depuis SOURCE] [autres options]
#
# SOURCE : « machine:dossier » (la copie de secours à la maison, par Tailscale/SSH) ou un dossier
# du Pi (clé USB montée). Les autres options sont celles de « vidange restaurer » (--ecraser,
# --sans-photos...).
#
# Ce que fait ce script (toute la liste est de pi/systeme/installation.md, étapes 1 à 7) :
#   installer les paquets, créer le compte « vidange », activer I2C et les liaisons série, mettre
#   le logiciel dans /opt/vidange-auto, le service systemd, le droit d'éteindre le Pi, le chien de
#   garde matériel ; aller chercher la copie de secours ; puis lancer « vidange restaurer ».
# On peut le relancer sans danger : ce qui est déjà fait est sauté.
#
# Avant de le lancer : le dépôt doit être copié à la main dans /opt/vidange-auto (le script est dedans) ;
# pas à pas : pi/systeme/essai-restauration.md. VIDANGE_A_BLANC=1 : affiche les commandes sans rien faire.
set -euo pipefail

DEST="${VIDANGE_DEST:-/opt/vidange-auto}"
A_BLANC="${VIDANGE_A_BLANC:-0}"
CONFIG_PI="${VIDANGE_CONFIG_PI:-/boot/firmware/config.txt}"
UTILISATEUR=vidange
DONNEES=/var/lib/vidange
SECRETS_DIR=/etc/vidange

faire() {
  if [ "$A_BLANC" = 1 ]; then
    echo "[à blanc] $*"
  else
    "$@"
  fi
}

dire() { echo; echo "== $* =="; }

# ---- 0. Où est la copie de secours ?
SOURCE=""
AUTRES=()
while [ $# -gt 0 ]; do
  case "$1" in
    --depuis) SOURCE="${2:?--depuis demande une valeur}"; shift 2 ;;
    *) AUTRES+=("$1"); shift ;;
  esac
done

if [ "$A_BLANC" != 1 ]; then
  if [ "$(id -u)" -ne 0 ]; then
    echo "Lancer avec sudo : sudo bash $0 ..." >&2
    exit 2
  fi
  if ! grep -q 'VERSION_CODENAME=bookworm' /etc/os-release; then
    echo "Ce Pi n'est pas sous Raspberry Pi OS Bookworm : le logiciel est prévu pour lui." >&2
    exit 2
  fi
  if [ ! -d "$DEST/pi" ]; then
    echo "Le logiciel n'est pas dans $DEST. D'abord :" >&2
    echo "  sudo apt install -y git && sudo git clone https://github.com/Karulium/vidange-auto.git $DEST" >&2
    echo "(dépôt privé : donner le nom GitHub et un jeton en lecture seule, voir installation.md)" >&2
    exit 2
  fi
fi

dire "1. Paquets du système"
faire apt-get update
faire apt-get install -y git python3-venv rsync ffmpeg

dire "2. Compte « $UTILISATEUR »"
if ! id "$UTILISATEUR" >/dev/null 2>&1; then
  faire useradd --system --create-home --shell /usr/sbin/nologin "$UTILISATEUR"
fi
# Les groupes qui n'existent pas sur ce Pi sont sautés (gpio, i2c...).
for groupe in dialout gpio i2c video; do
  if [ "$A_BLANC" = 1 ] || getent group "$groupe" >/dev/null; then
    faire usermod -aG "$groupe" "$UTILISATEUR"
  fi
done

dire "3. I2C et liaisons série"
faire raspi-config nonint do_i2c 0
REDEMARRER=0
for ligne in "dtoverlay=uart2-pi5" "dtparam=uart0=on"; do
  if [ "$A_BLANC" = 1 ]; then
    echo "[à blanc] ajouter « $ligne » à $CONFIG_PI si absent"
  elif ! grep -qxF "$ligne" "$CONFIG_PI"; then
    echo "$ligne" >> "$CONFIG_PI"
    REDEMARRER=1
  fi
done

dire "4. Logiciel et environnement Python"
faire chown -R "$UTILISATEUR:$UTILISATEUR" "$DEST"
if [ ! -x "$DEST/pi/.venv/bin/python" ]; then
  faire sudo -u "$UTILISATEUR" python3 -m venv "$DEST/pi/.venv"
fi
faire sudo -u "$UTILISATEUR" "$DEST/pi/.venv/bin/pip" install -e "$DEST/pi"

dire "5. Dossiers, service, droit d'éteindre, chien de garde"
faire mkdir -p "$SECRETS_DIR" "$DONNEES"
# Le compte « vidange » doit pouvoir écrire dans /etc/vidange (commande « vidange compte »).
faire chown "$UTILISATEUR:$UTILISATEUR" "$SECRETS_DIR" "$DONNEES"
faire chmod 750 "$SECRETS_DIR"
faire cp "$DEST/pi/systeme/vidange.service" /etc/systemd/system/vidange.service
faire systemctl daemon-reload
if [ "$A_BLANC" = 1 ]; then
  echo "[à blanc] écrire /etc/sudoers.d/vidange-extinction (droit de « systemctl poweroff »)"
  echo "[à blanc] écrire /etc/systemd/system.conf.d/chien-de-garde.conf (RuntimeWatchdogSec=14)"
else
  echo 'vidange ALL=(root) NOPASSWD: /usr/bin/systemctl poweroff' > /etc/sudoers.d/vidange-extinction
  chmod 440 /etc/sudoers.d/vidange-extinction
  visudo -c >/dev/null
  mkdir -p /etc/systemd/system.conf.d
  printf '[Manager]\nRuntimeWatchdogSec=14\n' > /etc/systemd/system.conf.d/chien-de-garde.conf
  systemctl daemon-reexec
fi

dire "6. Aller chercher la copie de secours"
COPIE="$SOURCE"
if [[ "$SOURCE" == *:* ]]; then
  CLE="/home/$UTILISATEUR/.ssh/id_ed25519"
  if [ "$A_BLANC" != 1 ] && [ ! -f "$CLE" ]; then
    sudo -u "$UTILISATEUR" mkdir -p "/home/$UTILISATEUR/.ssh"
    sudo -u "$UTILISATEUR" ssh-keygen -t ed25519 -N "" -f "$CLE" >/dev/null
    echo
    echo "Une clé SSH vient d'être créée pour ce Pi. L'AUTORISER à la maison, puis relancer ce script."
    echo "Clé à ajouter dans ~/.ssh/authorized_keys du compte à la maison :"
    cat "$CLE.pub"
    exit 3
  fi
  COPIE="$DONNEES/.copie-recue"
  faire sudo -u "$UTILISATEUR" mkdir -p "$COPIE"
  faire sudo -u "$UTILISATEUR" rsync -a --partial -e "ssh -o StrictHostKeyChecking=accept-new" \
    "${SOURCE%/}/" "$COPIE/"
fi

dire "7. Restauration (registre, fichiers hors Git, photos), vérification, service"
export VIDANGE_REGLAGES="$DEST/pi/reglages"
export VIDANGE_ENTREES_SORTIES="$DEST/docs/entrees-sorties.yaml"
export VIDANGE_SECRETS="$SECRETS_DIR/secrets.yaml"
export VIDANGE_DONNEES="$DONNEES"
ARGS=()
[ -n "$COPIE" ] && ARGS+=(--depuis "$COPIE")
ARGS+=("${AUTRES[@]}")
CODE=0
faire "$DEST/pi/.venv/bin/vidange" restaurer "${ARGS[@]}" || CODE=$?
if [[ "$SOURCE" == *:* ]]; then
  faire rm -rf "$COPIE"
fi
if [ "$REDEMARRER" = 1 ]; then
  echo
  echo "Les liaisons série viennent d'être activées : REDÉMARRER le Pi (sudo reboot)."
fi
exit "$CODE"
