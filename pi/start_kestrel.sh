#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PI_SRC_DIR="${REPO_ROOT}/pi/src"
PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"
LOCAL_ENV_FILE="${SCRIPT_DIR}/kestrel.env"

if [[ -f "${LOCAL_ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${LOCAL_ENV_FILE}"
  set +a
fi

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "Missing Python venv at ${PYTHON_BIN}"
  echo "Create it on the Pi first with:"
  echo "  python3 -m venv ${REPO_ROOT}/.venv"
  echo "  source ${REPO_ROOT}/.venv/bin/activate"
  echo "  pip install -r ${REPO_ROOT}/requirements.txt"
  exit 1
fi

if [[ -z "${NATSEC_UDP_HOST:-}" ]]; then
  echo "NATSEC_UDP_HOST is not set."
  echo "Set it to the laptop IP that is running dash."
  echo "Example:"
  echo "  NATSEC_UDP_HOST=172.20.10.3 bash ${SCRIPT_DIR}/start_kestrel.sh"
  exit 1
fi

export NATSEC_UDP_PORT="${NATSEC_UDP_PORT:-10110}"
export NATSEC_DEBUG_UDP_ENABLED="${NATSEC_DEBUG_UDP_ENABLED:-1}"
export NATSEC_DEBUG_UDP_PORT="${NATSEC_DEBUG_UDP_PORT:-10111}"
export NATSEC_CAMERA_PORT="${NATSEC_CAMERA_PORT:-8080}"
export NATSEC_CAM0_ID="${NATSEC_CAM0_ID:-0}"
export NATSEC_CAM1_ID="${NATSEC_CAM1_ID:-2}"
export NATSEC_CAMERA_WIDTH="${NATSEC_CAMERA_WIDTH:-640}"
export NATSEC_CAMERA_HEIGHT="${NATSEC_CAMERA_HEIGHT:-480}"

CAMERA_PID=""
NAV_PID=""

cleanup() {
  if [[ -n "${CAMERA_PID}" ]] && kill -0 "${CAMERA_PID}" 2>/dev/null; then
    kill "${CAMERA_PID}" 2>/dev/null || true
  fi
  if [[ -n "${NAV_PID}" ]] && kill -0 "${NAV_PID}" 2>/dev/null; then
    kill "${NAV_PID}" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

echo "Starting Kestrel on Pi"
echo "  repo: ${REPO_ROOT}"
echo "  udp_host: ${NATSEC_UDP_HOST}"
echo "  udp_port: ${NATSEC_UDP_PORT}"
echo "  debug_udp_port: ${NATSEC_DEBUG_UDP_PORT}"
echo "  camera_debug_port: ${NATSEC_CAMERA_PORT}"
echo "  camera_ids: cam0=${NATSEC_CAM0_ID} cam1=${NATSEC_CAM1_ID}"
echo
echo "Useful checks from the laptop:"
echo "  curl http://$(hostname -I | awk '{print $1}'):${NATSEC_CAMERA_PORT}/health"
echo "  curl http://<laptop-ip>:5000/api/telemetry/latest"
echo

cd "${PI_SRC_DIR}"

"${PYTHON_BIN}" scripts/camera_debug_server.py \
  --host 0.0.0.0 \
  --port "${NATSEC_CAMERA_PORT}" \
  --cam0 "${NATSEC_CAM0_ID}" \
  --cam1 "${NATSEC_CAM1_ID}" \
  --width "${NATSEC_CAMERA_WIDTH}" \
  --height "${NATSEC_CAMERA_HEIGHT}" &
CAMERA_PID=$!

PYTHONPATH="${PI_SRC_DIR}" "${PYTHON_BIN}" -m pnt.main &
NAV_PID=$!

wait -n "${CAMERA_PID}" "${NAV_PID}"
EXIT_CODE=$?

echo "One of the Kestrel processes exited with code ${EXIT_CODE}"
exit "${EXIT_CODE}"
