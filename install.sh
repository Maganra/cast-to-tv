#!/usr/bin/env bash
# Distro-agnostic per-user install for Cast to TV (installs to ~/.local).
# For Arch/CachyOS, `makepkg -si` (system-wide) is preferred; this is the
# fallback / non-Arch path.
set -euo pipefail
cd "$(dirname "$0")"

SHARE="$HOME/.local/share/cast-to-tv"
BIN="$HOME/.local/bin"
APPS="$HOME/.local/share/applications"

echo "== Checking dependencies =="
miss=()
for c in python3 ffmpeg gpu-screen-recorder pactl ip pkill; do
  command -v "$c" >/dev/null || miss+=("$c")
done
python3 -c "import PyQt6.QtWidgets" 2>/dev/null || miss+=("python-pyqt6 (PyQt6)")
if ! command -v catt >/dev/null && [ ! -x "$HOME/.local/bin/catt" ]; then
  echo "  catt not found — installing via pipx…"
  if command -v pipx >/dev/null; then pipx install catt || miss+=("catt"); else miss+=("catt (and pipx)"); fi
fi
if [ "${#miss[@]}" -gt 0 ]; then
  echo "  Missing: ${miss[*]}"
  echo "  Install them, then re-run. (Arch: python-pyqt6 ffmpeg are repo pkgs;"
  echo "  gpu-screen-recorder is AUR; catt via pipx or AUR.)"
  echo "  Continuing to install files anyway."
fi

echo "== Installing files =="
mkdir -p "$SHARE" "$BIN" "$APPS"
install -Dm644 src/cast_to_tv.py    "$SHARE/cast_to_tv.py"
install -Dm644 src/screen_server.py "$SHARE/screen_server.py"
install -Dm644 src/audio_server.py  "$SHARE/audio_server.py"
install -Dm755 bin/cast-to-tv  "$BIN/cast-to-tv"
install -Dm755 bin/cast-screen "$BIN/cast-screen"
install -Dm755 bin/cast-audio  "$BIN/cast-audio"
install -Dm755 bin/cast-pause  "$BIN/cast-pause"
install -Dm644 cast-to-tv.desktop "$APPS/cast-to-tv.desktop"
command -v update-desktop-database >/dev/null && update-desktop-database "$APPS" 2>/dev/null || true

echo "== Done =="
echo "Launch 'Cast to TV' from your app menu, or run: cast-to-tv"
case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) echo "NOTE: add ~/.local/bin to your PATH to use the CLI commands." ;;
esac
echo
echo "IMPORTANT (firewall): if you use a firewall, allow your Chromecast to"
echo "reach this PC, e.g. (UFW):  sudo ufw allow from <chromecast-ip>"
echo "and mDNS discovery:          sudo ufw allow 5353/udp"
