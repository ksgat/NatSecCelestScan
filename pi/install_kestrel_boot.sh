#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  exec sudo bash "$0" "$@"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SERVICE_NAME="kestrel"
SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}.service"
ENV_PATH="/etc/default/${SERVICE_NAME}"
RUN_USER="${SUDO_USER:-$(logname 2>/dev/null || echo pi)}"
START_NOW="${1:-}"

chmod +x "${REPO_ROOT}/pi/start_kestrel.sh"

cat > "${ENV_PATH}" <<EOF
# Kestrel runtime environment
# Set this to the laptop IP running dash.
NATSEC_UDP_HOST=172.20.10.3
NATSEC_UDP_PORT=10110
NATSEC_DEBUG_UDP_ENABLED=1
NATSEC_DEBUG_UDP_PORT=10111
NATSEC_CAMERA_PORT=8080
NATSEC_CAM0_ID=0
NATSEC_CAM1_ID=2
NATSEC_CAMERA_WIDTH=640
NATSEC_CAMERA_HEIGHT=480
EOF

cat > "${SERVICE_PATH}" <<EOF
[Unit]
Description=Kestrel Pi runtime
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${RUN_USER}
WorkingDirectory=${REPO_ROOT}
EnvironmentFile=${ENV_PATH}
ExecStart=${REPO_ROOT}/pi/start_kestrel.sh
Restart=always
RestartSec=3
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}.service"

echo "Installed ${SERVICE_NAME}.service"
echo "Environment file: ${ENV_PATH}"
echo "Edit NATSEC_UDP_HOST in ${ENV_PATH} before starting if needed."

if [[ "${START_NOW}" == "--start" ]]; then
  systemctl restart "${SERVICE_NAME}.service"
  echo "Started ${SERVICE_NAME}.service"
fi

echo
echo "Useful commands:"
echo "  sudo systemctl status ${SERVICE_NAME}.service"
echo "  sudo journalctl -u ${SERVICE_NAME}.service -f"
echo "  sudo systemctl restart ${SERVICE_NAME}.service"
