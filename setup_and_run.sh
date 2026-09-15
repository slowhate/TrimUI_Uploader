#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/.venv"

# Создаём venv, если нет
if [ ! -d "$VENV_DIR" ]; then
  echo "Создаю виртуальное окружение..."
  python3 -m venv "$VENV_DIR"
fi

# Активируем
source "$VENV_DIR/bin/activate"

# Ставим зависимости, если нужно
pip install --upgrade pip
pip install "paramiko>=5.0.0" "pillow>=12.3.0"

# Запускаем
python trimui_uploader.py

