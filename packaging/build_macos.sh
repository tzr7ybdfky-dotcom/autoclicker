#!/usr/bin/env bash
# Сборка AutoClicker.app на macOS (собирать нужно на Mac).
#
#   packaging/build_macos.sh              # архитектура текущего Python
#   packaging/build_macos.sh arm64        # Apple Silicon
#   packaging/build_macos.sh x86_64       # Intel (нужен Python с x86_64)
#   packaging/build_macos.sh universal2   # оба варианта в одном .app
#
# Для x86_64 и universal2 нужен universal2-Python (установщик с python.org);
# Python из Homebrew обычно содержит только одну архитектуру.
# Интерпретатор можно указать: PYTHON=/путь/к/python3.12 packaging/build_macos.sh
set -euo pipefail

ARCH="${1:-}"
case "$ARCH" in
  ""|arm64|x86_64|universal2) ;;
  *) echo "Неизвестная архитектура: $ARCH (arm64 | x86_64 | universal2)" >&2; exit 2 ;;
esac

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PYTHON="${PYTHON:-python3}"
VENV="build/venv-macos"

if [[ -n "$ARCH" && "$ARCH" != "$(uname -m)" ]]; then
  PY_ARCHS="$(lipo -archs "$("$PYTHON" -c 'import sys; print(sys.executable)')" 2>/dev/null || true)"
  if [[ "$ARCH" == "universal2" ]]; then
    NEED="x86_64 arm64"
  else
    NEED="$ARCH"
  fi
  for a in $NEED; do
    if [[ " $PY_ARCHS " != *" $a "* ]]; then
      echo "Python ($PYTHON) не содержит архитектуру $a (есть: ${PY_ARCHS:-неизвестно})." >&2
      echo "Установите universal2-Python с python.org и укажите его через PYTHON=…" >&2
      exit 1
    fi
  done
fi

echo "==> Виртуальное окружение: $VENV"
"$PYTHON" -m venv "$VENV"
"$VENV/bin/python" -m pip install --upgrade pip >/dev/null
"$VENV/bin/python" -m pip install -r requirements-dev.txt

echo "==> Тесты (без реальных кликов)"
"$VENV/bin/python" -m pytest

echo "==> Иконка"
"$VENV/bin/python" packaging/make_icons.py

# Сборка идёт во временной папке вне iCloud: в синхронизируемых папках (Рабочий
# стол, Документы) iCloud добавляет к .framework расширенные атрибуты, и codesign
# отказывается подписывать бандл («resource fork, Finder information… not allowed»).
OUT="${AUTOCLICKER_BUILD_DIR:-${TMPDIR:-/tmp}/autoclicker-build}"
rm -rf "$OUT"
mkdir -p "$OUT"

echo "==> PyInstaller (${ARCH:-$(uname -m)}) в $OUT"
AUTOCLICKER_ARCH="$ARCH" "$VENV/bin/python" -m PyInstaller --noconfirm --clean \
  --distpath "$OUT/dist" --workpath "$OUT/work" packaging/autoclicker.spec

BUILT="$OUT/dist/AutoClicker.app"
BIN="$BUILT/Contents/MacOS/AutoClicker"
echo "==> Проверка сборки"
lipo -archs "$BIN"
if ! codesign --verify --deep --strict "$BUILT"; then
  echo "Подпись .app некорректна — сборка остановлена." >&2
  exit 1
fi
echo "Подпись: корректна (ad-hoc, если не задан AUTOCLICKER_CODESIGN_IDENTITY)"
"$BIN" --smoke-test
if [[ "$ARCH" == "universal2" ]] && arch -x86_64 /usr/bin/true 2>/dev/null; then
  arch -x86_64 "$BIN" --smoke-test
fi

APP="dist/AutoClicker.app"
rm -rf "$APP"
mkdir -p dist
ditto "$BUILT" "$APP"  # ditto сохраняет подпись и структуру бандла
rm -rf "$OUT"
echo "Готово: $ROOT/$APP"
echo "Установка: ditto --noextattr --norsrc \"$ROOT/$APP\" /Applications/AutoClicker.app"
