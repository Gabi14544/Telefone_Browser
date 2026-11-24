#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -m)" != x86_64 ]]; then
    echo "Este instalador es para Linux x86_64." >&2
    exit 1
fi

source_dir=$(cd "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
data_dir="${XDG_DATA_HOME:-$HOME/.local/share}"
app_dir="$data_dir/telefone-browser"
version=3.3.4
release="scrcpy-linux-x86_64-v$version"
archive_url="https://github.com/Genymobile/scrcpy/releases/download/v$version/$release.tar.gz"
checksum=0305d98c06178c67e12427bbf340c436d0d58c9e2a39bf9ffbbf8f54d7ef95a5

if ! command -v curl >/dev/null || ! command -v wmctrl >/dev/null ||
   ! command -v xdotool >/dev/null ||
   ! /usr/bin/python3 -c 'import gi; gi.require_version("Gtk", "3.0"); from gi.repository import Gtk' 2>/dev/null; then
    echo "Instalando GTK y las herramientas de ventanas de Linux…"
    sudo apt-get install --no-install-recommends curl ca-certificates python3-gi gir1.2-gtk-3.0 wmctrl xdotool
fi

mkdir -p "$data_dir"
work_dir=$(mktemp -d "$data_dir/.telefone-instalar.XXXXXX")
trap 'rm -rf -- "$work_dir"' EXIT

echo "Descargando scrcpy $version y ADB desde Genymobile…"
curl --fail --location --silent --show-error --retry 2 --connect-timeout 15 \
    --max-time 120 --proto '=https' "$archive_url" -o "$work_dir/$release.tar.gz"
if ! printf '%s  %s\n' "$checksum" "$work_dir/$release.tar.gz" | sha256sum --check --status; then
    echo "El archivo descargado no coincide con la suma SHA-256 de Genymobile." >&2
    exit 1
fi
tar -xzf "$work_dir/$release.tar.gz" -C "$work_dir"
"$work_dir/$release/scrcpy" --version | sed -n '1p'
"$work_dir/$release/adb" version | sed -n '1p'

mkdir -p "$app_dir/telefone_browser" "$app_dir/motor" "$data_dir/applications"
install -m 755 "$source_dir/abrir" "$app_dir/abrir"
install -m 644 "$source_dir"/telefone_browser/*.py "$source_dir/telefone_browser/style.css" "$app_dir/telefone_browser/"
install -m 755 "$work_dir/$release/adb" "$work_dir/$release/scrcpy" "$app_dir/motor/"
install -m 644 "$work_dir/$release/scrcpy-server" "$work_dir/$release/icon.png" "$app_dir/motor/"

/usr/bin/python3 - "$app_dir/abrir" "$data_dir/applications/ar.telefonebrowser.Desktop.desktop" <<'PY'
import sys
from pathlib import Path

launcher, destination = sys.argv[1:]
# Exec uses both desktop-entry string escaping and command-line quoting.
quoted = launcher.replace("%", "%%")
for character in ("\\", '"', "$", chr(96)):
    quoted = quoted.replace(character, "\\" + character)
quoted = quoted.replace("\\", "\\\\")
Path(destination).write_text(
    "[Desktop Entry]\n"
    "Type=Application\n"
    "Name=Telefone Browser\n"
    "Comment=Compartí la pantalla y los archivos de Android\n"
    f'Exec="{quoted}"\n'
    "Icon=phone\n"
    "Terminal=false\n"
    "Categories=Utility;\n"
    "StartupNotify=true\n",
    encoding="utf-8",
)
PY

printf '\nInstalación lista. Abrí Telefone Browser desde el menú de Cinnamon.\n'
