# Maintainer: ympb <manoely.games@gmail.com>
pkgname=noxtify
pkgver=0.6.0
pkgrel=1
pkgdesc='AMOLED music player using YouTube Music with queue, lyrics and playlists'
arch=('any')
url='https://github.com/ympb/noxtify'
license=('MIT')
depends=('mpv' 'python' 'python-pyqt6' 'python-requests' 'python-ytmusicapi' 'yt-dlp')
makedepends=('git')
checkdepends=('python-pytest')
provides=('nox-music')
conflicts=('nox-music' 'nox-music-git')
source=("${pkgname}::git+https://github.com/ympb/noxtify.git#tag=v${pkgver}")
sha256sums=('SKIP')

check() {
  cd "${srcdir}/${pkgname}"
  python -m pytest -q
  python -m py_compile nox_music/app.py
}

package() {
  cd "${srcdir}/${pkgname}"

  install -Dm755 nox_music/app.py "${pkgdir}/usr/lib/noxtify/app.py"
  install -Dm644 nox_music/__init__.py "${pkgdir}/usr/lib/noxtify/__init__.py"
  install -Dm644 LICENSE "${pkgdir}/usr/share/licenses/${pkgname}/LICENSE"
  install -Dm644 data/noxtify.desktop "${pkgdir}/usr/share/applications/noxtify.desktop"
  install -Dm644 README.md "${pkgdir}/usr/share/doc/${pkgname}/README.md"
  install -Dm644 CHANGELOG.md "${pkgdir}/usr/share/doc/${pkgname}/CHANGELOG.md"

  install -d "${pkgdir}/usr/bin"
  cat > "${pkgdir}/usr/bin/noxtify" <<'WRAPPER'
#!/bin/sh
exec /usr/bin/python /usr/lib/noxtify/app.py "$@"
WRAPPER
  chmod 755 "${pkgdir}/usr/bin/noxtify"
}
