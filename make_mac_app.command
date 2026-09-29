#!/bin/bash
# Double-click this file (on a Mac) to add "CV Maker" to your Applications folder, with its
# own icon. After that, open CV Maker like any other app: from Launchpad, Spotlight or the Dock.
# There's no window to keep open: it stops by itself about 15 minutes after you close the page.
# If you move this folder, double-click this file again.
cd "$(dirname "$0")" || exit 1
REPO="$(pwd)"
APP="$HOME/Applications/CV Maker.app"

if [ "$(uname)" != "Darwin" ]; then
  echo "This makes a Mac app. On other computers, use start.command or start.bat instead."
  exit 1
fi

echo "Making CV Maker.app…"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

# The icon: macOS's own tools turn the PNG into the .icns format apps use.
ICONSET="$(mktemp -d)/AppIcon.iconset"
mkdir -p "$ICONSET"
for size in 16 32 128 256 512; do
  sips -z $size $size cv_maker/static/icon.png --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
  sips -z $((size * 2)) $((size * 2)) cv_maker/static/icon.png --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>CV Maker</string>
  <key>CFBundleDisplayName</key><string>CV Maker</string>
  <key>CFBundleIdentifier</key><string>local.cv-maker</string>
  <key>CFBundleExecutable</key><string>CV Maker</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>LSUIElement</key><true/>
</dict>
</plist>
PLIST

# The app itself: reopen the page if CV Maker is already running, otherwise start it
# quietly in the background (setting up Python packages the first time).
cat > "$APP/Contents/MacOS/CV Maker" <<LAUNCHER
#!/bin/bash
REPO="$REPO"
LOG="\$HOME/Library/Logs/CV Maker.log"
mkdir -p "\$HOME/Library/Logs"
say() { osascript -e "display notification \"\$1\" with title \"CV Maker\"" >/dev/null 2>&1; }
fail() { osascript -e "display alert \"CV Maker\" message \"\$1\" as critical" >/dev/null 2>&1; exit 1; }

[ -d "\$REPO/cv_maker" ] || fail "The CV Maker folder has moved. Open the folder and double-click make_mac_app.command again."
cd "\$REPO" || exit 1

URL_FILE="\$REPO/data/.server-url"
if [ -f "\$URL_FILE" ] && curl -fsS -m 2 "\$(cat "\$URL_FILE")/api/ping" >/dev/null 2>&1; then
  open "\$(cat "\$URL_FILE")"
  exit 0
fi

command -v python3 >/dev/null 2>&1 || fail "Python 3 isn't installed. Get it from python.org/downloads, then open CV Maker again."
if [ ! -x .venv/bin/python ]; then
  say "Setting up for the first time. This takes a minute."
  python3 -m venv .venv >>"\$LOG" 2>&1 || fail "Couldn't set up Python. Details are in ~/Library/Logs/CV Maker.log."
fi
wanted="\$(shasum requirements.txt | cut -d' ' -f1)"
if [ "\$(cat .venv/.requirements-hash 2>/dev/null)" != "\$wanted" ]; then
  say "Installing what CV Maker needs…"
  .venv/bin/python -m pip install -q --upgrade pip >>"\$LOG" 2>&1
  .venv/bin/python -m pip install -q -r requirements.txt >>"\$LOG" 2>&1 && echo "\$wanted" > .venv/.requirements-hash \
    || fail "Couldn't install what CV Maker needs. Check your internet connection. Details are in ~/Library/Logs/CV Maker.log."
fi
exec .venv/bin/python -m cv_maker --quit-when-idle 15 >>"\$LOG" 2>&1
LAUNCHER
chmod +x "$APP/Contents/MacOS/CV Maker"
touch "$APP"  # so Finder picks up the new icon

echo
echo "Done. CV Maker is in your Applications folder ($APP)."
echo "Open it from Launchpad or Spotlight (Cmd+Space, type CV Maker). To keep it in the Dock,"
echo "drag it there from the Applications folder."
open -R "$APP"
