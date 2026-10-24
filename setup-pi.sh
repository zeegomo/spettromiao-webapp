#!/bin/bash
#
# spettromiao - Raspberry Pi setup
#
# Sets up the Pi backend (camera capture, controller v2 board, spectrum
# processing) as a systemd service serving the API and the frontend on port 80.
# Safe to re-run: every step skips work that is already done.
#
# Usage (from the repo checkout, e.g. /opt/spettromiao-webapp):
#   ./setup-pi.sh
#
# Environment overrides:
#   KAT_DIR        where the kat repo is (cloned if missing)   [~/kat]
#   KAT_REPO       URL to clone kat from                       [https://github.com/zeegomo/kat.git]
#

set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$APP_DIR/.venv"
KAT_DIR="${KAT_DIR:-$HOME/kat}"
KAT_REPO="${KAT_REPO:-https://github.com/zeegomo/kat.git}"
SERVICE_NAME="spettromiao-webapp"
CALIB_DIR="$HOME/.kat/calibration"

for arg in "$@"; do
    case "$arg" in
        -h|--help) sed -n '3,14p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Unknown option: $arg" >&2; exit 1 ;;
    esac
done

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

if [ "$(id -u)" -eq 0 ]; then
    log_error "Run this as the user the service should run as, not root (sudo is used where needed)"
    exit 1
fi

if ! grep -q "Raspberry Pi" /proc/device-tree/model 2>/dev/null; then
    log_warn "This doesn't appear to be a Raspberry Pi. Continuing anyway..."
fi

# =============================================================================
# System packages
# =============================================================================

log_info "Installing system packages..."
sudo apt-get update
# picamera2/libcamera, gpiozero and lgpio are used from the system install
sudo apt-get install -y \
    git python3-venv python3-dev python3-picamera2 python3-gpiozero python3-lgpio \
    v4l-utils i2c-tools

if ! command -v rpicam-still >/dev/null; then
    sudo apt-get install -y rpicam-apps-lite
fi

# =============================================================================
# I2C (controller board ADC) and device permissions
# =============================================================================

if command -v raspi-config >/dev/null; then
    sudo raspi-config nonint do_i2c 0
else
    log_warn "raspi-config not found, make sure I2C is enabled"
fi

RELOGIN=false
for group in gpio i2c video; do
    if getent group "$group" >/dev/null && ! id -nG "$USER" | grep -qw "$group"; then
        sudo usermod -aG "$group" "$USER"
        RELOGIN=true
    fi
done

# =============================================================================
# Python environment
# =============================================================================

# --system-site-packages: picamera2/libcamera, gpiozero and lgpio come from apt
if [ ! -d "$VENV_DIR" ]; then
    log_info "Creating virtual environment at $VENV_DIR..."
    python3 -m venv --system-site-packages "$VENV_DIR"
elif ! grep -q "^include-system-site-packages = true" "$VENV_DIR/pyvenv.cfg"; then
    log_info "Enabling system site-packages in the existing $VENV_DIR..."
    sed -i "s/^include-system-site-packages = .*/include-system-site-packages = true/" "$VENV_DIR/pyvenv.cfg"
fi
PIP="$VENV_DIR/bin/pip"
"$PIP" install --upgrade pip

# Don't let pip replace the system numpy: the apt picamera2 stack is built against it
CONSTRAINTS="$(mktemp)"
trap 'rm -f "$CONSTRAINTS"' EXIT
SYSTEM_NUMPY="$(/usr/bin/python3 -c 'import numpy; print(numpy.__version__)' 2>/dev/null || true)"
if [ -n "$SYSTEM_NUMPY" ]; then
    echo "numpy==$SYSTEM_NUMPY" > "$CONSTRAINTS"
fi

log_info "Installing backend dependencies..."
"$PIP" install -c "$CONSTRAINTS" -r "$APP_DIR/backend/requirements.txt"

if [ ! -f "$KAT_DIR/pyproject.toml" ]; then
    log_info "Cloning kat into $KAT_DIR (private repo: git will ask for a GitHub username + token)..."
    git clone "$KAT_REPO" "$KAT_DIR"
fi
log_info "Installing kat from $KAT_DIR (this takes a while)..."
"$PIP" install -c "$CONSTRAINTS" -e "$KAT_DIR"

# =============================================================================
# Calibration
# =============================================================================

mkdir -p "$CALIB_DIR"
for f in calib_results.npz calibration.json; do
    if [ ! -f "$CALIB_DIR/$f" ]; then
        log_warn "Missing $CALIB_DIR/$f - captures will return photos without spectra"
    fi
done

# =============================================================================
# Systemd service
# =============================================================================

log_info "Installing $SERVICE_NAME service..."
sed -e "s|^User=.*|User=$USER|" \
    -e "s|/opt/spettromiao-webapp|$APP_DIR|g" \
    "$APP_DIR/$SERVICE_NAME.service" | sudo tee "/etc/systemd/system/$SERVICE_NAME.service" >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

# =============================================================================
# Checks
# =============================================================================

log_info "Checking the installation..."
PY="$VENV_DIR/bin/python"
FAILED=false
check() {
    local name="$1" code="$2"
    if "$PY" -c "$code" >/dev/null 2>&1; then
        log_info "  ok: $name"
    else
        log_warn "  FAILED: $name  (debug: $PY -c \"$code\")"
        FAILED=true
    fi
}
check "picamera2"            "import picamera2"
check "kat_board"            "import kat_board"
check "spectrum processing"  "import cv2, ramanspy, kat.acquisition.image_processing"

if sudo i2cdetect -y 1 2>/dev/null | grep -q " 48"; then
    log_info "  ok: controller board ADC at 0x48"
else
    log_warn "  controller board not found on I2C (0x48) - laser control will be disabled"
fi

if ! systemctl is-active --quiet "$SERVICE_NAME"; then
    log_error "Service failed to start: sudo journalctl -u $SERVICE_NAME -e"
    FAILED=true
fi

echo ""
if [ "$FAILED" = true ]; then
    log_warn "Setup finished with problems, see the warnings above"
else
    log_info "Setup complete"
fi
echo "  Service: sudo systemctl status $SERVICE_NAME"
echo "  Logs:    sudo journalctl -u $SERVICE_NAME -f"
if [ "$RELOGIN" = true ]; then
    log_warn "Added $USER to gpio/i2c/video groups: log out and back in to use them from your shell"
fi
