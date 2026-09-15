#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Активируем существующий venv
source "${SCRIPT_DIR}/.venv/bin/activate"

# Запускаем приложение
python trimui_uploader.py

