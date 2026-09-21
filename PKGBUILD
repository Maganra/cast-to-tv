# Maintainer: Maganra
pkgname=cast-to-tv
pkgver=1.0.0
pkgrel=1
pkgdesc="Cast a monitor or system audio to a Chromecast (Qt GUI + CLI)"
arch=('any')
url="https://github.com/Maganra/cast-to-tv"
license=('MIT')
depends=('python' 'python-pyqt6' 'ffmpeg' 'gpu-screen-recorder' 'catt'
         'libpulse' 'iproute2' 'procps-ng')
# gpu-screen-recorder and catt are in the AUR — install with an AUR helper
# (e.g. `paru -S gpu-screen-recorder catt`) before/while building.
source=()

package() {
  cd "$startdir"
  # App + stream servers
  install -Dm644 src/cast_to_tv.py   "$pkgdir/usr/share/cast-to-tv/cast_to_tv.py"
  install -Dm644 src/screen_server.py "$pkgdir/usr/share/cast-to-tv/screen_server.py"
  install -Dm644 src/audio_server.py  "$pkgdir/usr/share/cast-to-tv/audio_server.py"
  # Executables
  install -Dm755 bin/cast-to-tv "$pkgdir/usr/bin/cast-to-tv"
  install -Dm755 bin/cast-screen "$pkgdir/usr/bin/cast-screen"
  install -Dm755 bin/cast-audio  "$pkgdir/usr/bin/cast-audio"
  # Desktop entry
  install -Dm644 cast-to-tv.desktop "$pkgdir/usr/share/applications/cast-to-tv.desktop"
}
