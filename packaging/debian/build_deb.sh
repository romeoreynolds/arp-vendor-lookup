#!/usr/bin/env bash
# Build an architecture-independent .deb for Debian 12+, Ubuntu 22.04+,
# Kali and Raspberry Pi OS. Uses the system python3 and python3-tk.
#
# Usage: packaging/debian/build_deb.sh VERSION OUI_DATA_DIR [OUT_DIR]
set -euo pipefail

VERSION="${1:?version, e.g. 2.1.0}"
OUI_DIR="${2:?folder containing oui.csv / mam.csv / oui36.csv}"
OUT_DIR="${3:-dist}"
PKG=arp-vendor-lookup
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

ROOT="$STAGE/${PKG}_${VERSION}_all"
install -d "$ROOT/DEBIAN" \
           "$ROOT/usr/bin" \
           "$ROOT/usr/lib/python3/dist-packages" \
           "$ROOT/usr/share/$PKG/oui_data" \
           "$ROOT/usr/share/applications" \
           "$ROOT/usr/share/icons/hicolor/scalable/apps" \
           "$ROOT/usr/share/doc/$PKG"

# Python package (source only; Debian's python3 compiles on first use)
cp -r "$REPO/src/arp_vendor_lookup" "$ROOT/usr/lib/python3/dist-packages/"
find "$ROOT/usr/lib/python3/dist-packages" -name '__pycache__' -prune -exec rm -rf {} +

# Vendor database
cp "$OUI_DIR"/*.csv "$ROOT/usr/share/$PKG/oui_data/"

# Launchers
cat > "$ROOT/usr/bin/arpvendor" <<'EOF'
#!/usr/bin/python3
from arp_vendor_lookup.cli import main
raise SystemExit(main())
EOF
cat > "$ROOT/usr/bin/arpvendor-gui" <<'EOF'
#!/usr/bin/python3
from arp_vendor_lookup.gui import main
main()
EOF
chmod 755 "$ROOT/usr/bin/arpvendor" "$ROOT/usr/bin/arpvendor-gui"

# App menu entry + icon
install -m 644 "$HERE/arp-vendor-lookup.desktop" "$ROOT/usr/share/applications/"
install -m 644 "$HERE/arp-vendor-lookup.svg" "$ROOT/usr/share/icons/hicolor/scalable/apps/"

# Docs
install -m 644 "$REPO/LICENSE" "$ROOT/usr/share/doc/$PKG/copyright"
gzip -9n -c "$REPO/CHANGELOG.md" > "$ROOT/usr/share/doc/$PKG/changelog.gz"

SIZE_KB=$(du -sk --exclude=DEBIAN "$ROOT" | cut -f1)
sed -e "s/@VERSION@/$VERSION/" -e "s/@SIZE@/$SIZE_KB/" "$HERE/control" > "$ROOT/DEBIAN/control"
install -m 755 "$HERE/postinst" "$ROOT/DEBIAN/postinst"
install -m 755 "$HERE/postrm" "$ROOT/DEBIAN/postrm"

find "$ROOT" -type d -exec chmod 755 {} +
find "$ROOT/usr/lib" "$ROOT/usr/share" -type f -exec chmod 644 {} +

mkdir -p "$OUT_DIR"
dpkg-deb --build --root-owner-group -Zxz "$ROOT" "$OUT_DIR/${PKG}_${VERSION}_all.deb"
echo "Built $OUT_DIR/${PKG}_${VERSION}_all.deb"
