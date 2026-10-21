#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

# MediaPipe needs Python 3.11–3.12. System python3.15 won't work.
CONDA_ENV="$ROOT/.conda-env"
COLOR_VENV="$ROOT/.venv"

setup_color_venv() {
  if [[ ! -d "$COLOR_VENV" ]]; then
    python3 -m venv "$COLOR_VENV"
  fi
  # shellcheck disable=SC1091
  source "$COLOR_VENV/bin/activate"
  pip install -q -U pip opencv-python-headless numpy
}

setup_full_env() {
  if [[ ! -x "$CONDA_ENV/bin/python" ]]; then
    echo "Creating conda env (Python 3.11) at $CONDA_ENV ..."
    conda create -y -p "$CONDA_ENV" python=3.11 pip
  fi
  "$CONDA_ENV/bin/pip" install -q -r requirements.txt requests
}

case "${1:-help}" in
  color)
    setup_color_venv
    if [[ $# -lt 2 ]]; then
      echo "Usage: ./run_local_test.sh color /path/to/image_or_video"
      exit 1
    fi
    python test_color_mask_refinement.py "$2"
    ;;
  server)
    setup_full_env
    echo "Starting local analyzer at http://127.0.0.1:8000"
    exec "$CONDA_ENV/bin/uvicorn" percfect_motion_analyzer_v2:app --host 127.0.0.1 --port 8000
    ;;
  client)
    setup_full_env
    if [[ $# -lt 2 ]]; then
      echo "Usage: ./run_local_test.sh client /path/to/clip.mp4"
      exit 1
    fi
    MOTION_API_URL="${MOTION_API_URL:-http://127.0.0.1:8000}" \
      "$CONDA_ENV/bin/python" test_motion_client.py "$2"
    ;;
  setup)
    setup_color_venv
    setup_full_env
    echo "Ready. Examples:"
    echo "  ./run_local_test.sh color _test_frame.jpg"
    echo "  ./run_local_test.sh server    # terminal 1"
    echo "  ./run_local_test.sh client _test_clip.mp4   # terminal 2"
    ;;
  *)
    echo "Usage:"
    echo "  ./run_local_test.sh setup"
    echo "  ./run_local_test.sh color  <image_or_video>"
    echo "  ./run_local_test.sh server"
    echo "  ./run_local_test.sh client <video>"
    ;;
esac