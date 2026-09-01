#!/usr/bin/env bash
# ==============================================================================
# AILÉN Living Appliance — Script de Ejecución Unificado
# Ejecuta AILÉN con una sola configuración canónica (config/ailen.toml).
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

CONFIG_FILE="config/ailen.toml"
MODE="${1:-full}"

if [ ! -f "${CONFIG_FILE}" ]; then
  if [ -f "runtime/lab/ailen-lab.toml" ]; then
    mkdir -p config
    cp "runtime/lab/ailen-lab.toml" "${CONFIG_FILE}"
    echo "[AILEN] Inicializado ${CONFIG_FILE} desde plantilla."
  elif [ -f "config/ailen.example.toml" ]; then
    mkdir -p config
    cp "config/ailen.example.toml" "${CONFIG_FILE}"
    echo "[AILEN] Inicializado ${CONFIG_FILE} desde ejemplo."
  fi
fi

if [ ! -d ".venv" ]; then
  echo "[ERROR] Entorno virtual .venv no encontrado. Ejecutá: python3 -m venv .venv && pip install -e ."
  exit 1
fi

export AILEN_CONFIG="${CONFIG_FILE}"
AILEN_VERSION="$(tr -d '\r\n' < VERSION 2>/dev/null || true)"
if [ -z "${AILEN_VERSION}" ]; then
  AILEN_VERSION="$(.venv/bin/python -c 'import ailen; print(ailen.__version__)')"
fi
mkdir -p runtime/lab

# Matar instancias previas del servidor o de ailen
pkill -f "ailen.*serve" 2>/dev/null || true
pkill -f "ailen.*lab start" 2>/dev/null || true
sleep 0.5

echo "=================================================="
echo " 🔥 AILÉN Living Appliance v${AILEN_VERSION}"
echo " 📄 Configuración: ${CONFIG_FILE}"
echo "=================================================="

case "${MODE}" in
  panel|serve|web)
    echo " 🌐 Modo: Panel Web Administrativo en primer plano"
    echo " 🔗 URL: http://127.0.0.1:8080"
    echo "=================================================="
    exec .venv/bin/ailen -c "${CONFIG_FILE}" serve
    ;;

  app|lab|assistant)
    echo " 🤖 Modo: Asistente AILÉN (Rostro + Voz + Visión + IA)"
    echo "=================================================="
    exec .venv/bin/ailen -c "${CONFIG_FILE}" lab start
    ;;

  face|demo-face)
    echo " 🙂 Modo: Rostro AILÉN FacePack nativo"
    echo "=================================================="
    exec .venv/bin/ailen -c "${CONFIG_FILE}" demo face --gui --style facepack
    ;;

  face-portrait|portrait)
    echo " 🖼️  Modo diagnóstico explícito: Retrato legacy"
    echo "=================================================="
    exec .venv/bin/ailen -c "${CONFIG_FILE}" demo face --gui --style portrait
    ;;

  face-pixel|pixel)
    echo " 👾 Modo explícito: Rostro Pixel para pantallas limitadas"
    echo "=================================================="
    exec .venv/bin/ailen -c "${CONFIG_FILE}" demo face --gui --style pixel
    ;;

  face-vector)
    echo " 📐 Modo: Rostro Vector Clásico (Tkinter)"
    echo "=================================================="
    exec .venv/bin/ailen -c "${CONFIG_FILE}" demo face --gui --style vector
    ;;

  full|*)
    echo " 🚀 Modo: Completo (Panel Web en 8080 + Asistente AILÉN GUI)"
    echo " 🌐 Panel Web: http://127.0.0.1:8080"
    echo " 🤖 Asistente: Inicializando Rostro, Micrófono y Cerebro IA..."
    echo "=================================================="

    # Iniciar Panel Web en segundo plano
    .venv/bin/ailen -c "${CONFIG_FILE}" serve > runtime/lab/web_server.log 2>&1 &
    WEB_PID=$!

    cleanup() {
      echo ""
      echo "[AILEN] Deteniendo servicios..."
      kill "${WEB_PID}" 2>/dev/null || true
      wait "${WEB_PID}" 2>/dev/null || true
      echo "[AILEN] Sesión finalizada."
    }
    trap cleanup EXIT INT TERM

    sleep 1

    # Iniciar Asistente AILÉN en primer plano
    .venv/bin/ailen -c "${CONFIG_FILE}" lab start
    ;;
esac
