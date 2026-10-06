#!/usr/bin/env bash
# Builds ComplianceWatch.app, the desktop app "ComplianceWatch Control", on the Desktop or in the
# directory given as $1.
#
# The bundle carries its own copy of the control app in Contents/Resources/control-panel: the
# helper (panel_server.py with panel_core.py, panel_catalog.py and panel_demo.py) and the web UI
# (ui/), so the app it opens is the one installed, whatever branch the checkout is on later. Its
# window is a small Swift program (shell/ControlApp.swift), compiled here with swiftc: it starts
# the helper with the checkout's Python and shows the UI. Without swiftc, the app opens the UI in
# Google Chrome's app mode, else in the default browser. The icon is drawn by shell/app_icon.py
# and packed with iconutil.
#
# The checkout is the one this script sits in, or CW_CONTROL_PANEL_REPO when the script runs from
# a copy outside a checkout. Run it again (make control-panel-app) to update the app: the new app
# is built beside the old one and swapped in only when complete, and any failure leaves the old
# one where it was. CW_CONTROL_APP_SHELL=browser skips the Swift window. CW_CONTROL_APP_NAME and
# CW_CONTROL_APP_ID give a test build its own name and bundle id ("ComplianceWatch Smoke"), so
# macOS never lists it as a second ComplianceWatch.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "${CW_CONTROL_PANEL_REPO:-$HERE/../..}" && pwd)"
DEST="${1:-$HOME/Desktop}"
FILES=(panel_core.py panel_catalog.py panel_server.py panel_demo.py)

for file in "${FILES[@]}" ui/index.html shell/ControlApp.swift shell/app_icon.py; do
  [ -f "$HERE/$file" ] || { echo "error: $HERE has no $file to put in the app"; exit 1; }
done
if [ ! -f "$REPO/Makefile" ] || [ ! -e "$REPO/.git" ]; then
  echo "error: $REPO is not a ComplianceWatch checkout; set CW_CONTROL_PANEL_REPO=<checkout>"
  exit 1
fi
NAME="${CW_CONTROL_APP_NAME:-ComplianceWatch}"
BUNDLE_ID="${CW_CONTROL_APP_ID:-local.compliancewatch.control-panel}"
SHOWN="ComplianceWatch Control"
[ -n "${CW_CONTROL_APP_NAME:-}" ] && SHOWN="$NAME"
plain_name='^[A-Za-z0-9][A-Za-z0-9 ._-]*$'
bundle_id='^[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$'
[[ "$NAME" =~ $plain_name ]] || { echo "error: CW_CONTROL_APP_NAME must be a plain name"; exit 1; }
[[ "$BUNDLE_ID" =~ $bundle_id ]] || { echo "error: CW_CONTROL_APP_ID must be a bundle id"; exit 1; }
LSREGISTER="${CW_CONTROL_APP_LSREGISTER-/System/Library/Frameworks/CoreServices.framework/Versions/A/Frameworks/LaunchServices.framework/Versions/A/Support/lsregister}"
mkdir -p "$DEST"
DEST="$(cd "$DEST" && pwd)"
APP="$DEST/$NAME.app"

# Built beside the app, then swapped in: the old app moves aside, the new one moves in, and the old
# one is deleted only once the new one is in place. On a failure before that the old app moves
# back; if even that fails, it stays in its .ComplianceWatch-old folder and the error says where.
# Nothing here ever deletes both.
work="$(mktemp -d "$DEST/.ComplianceWatch-build.XXXXXX")"
aside=""
swapped=""
finish() {
  local status=$?
  set +e
  if [ -n "$aside" ]; then
    if [ -n "$swapped" ]; then
      rm -rf "$aside"
    elif [ -e "$aside/$NAME.app" ]; then
      if [ ! -e "$APP" ] && mv "$aside/$NAME.app" "$APP"; then
        rmdir "$aside"
        echo "note: the install failed, so the old app is back at $APP"
      else
        echo "error: the old app is kept at $aside/$NAME.app; move it back to $APP"
      fi
    else
      rmdir "$aside" 2>/dev/null
    fi
  fi
  rm -rf "$work"
  exit "$status"
}
trap finish EXIT
new="$work/$NAME.app"
contents="$new/Contents"
panel="$contents/Resources/control-panel"
mkdir -p "$contents/MacOS" "$panel"
for file in "${FILES[@]}"; do cp "$HERE/$file" "$panel/"; done
cp -R "$HERE/ui" "$panel/ui"
find "$panel/ui" -name '.*' -prune -exec rm -rf {} +

# What the window shows as its build: when, and the commit the files came from (with +changes
# when they differ from it), or the files' own hash outside a commit.
commit="$(git --no-optional-locks -C "$HERE" rev-parse --short HEAD 2>/dev/null || true)"
if [ -n "$commit" ] && [ -n "$(git --no-optional-locks -C "$HERE" status --porcelain -- "${FILES[@]}" ui shell 2>/dev/null)" ]; then
  commit="$commit+changes"
fi
if command -v shasum >/dev/null 2>&1; then digest() { shasum -a 256; }; else digest() { sha256sum; }; fi
files="$(cd "$panel" && find . -type f -print0 | LC_ALL=C sort -z | xargs -0 cat | digest | cut -c1-12)"
{
  echo "built=$(date '+%Y-%m-%d %H:%M')"
  echo "commit=${commit:-none}"
  echo "files=$files"
  echo "source=$HERE"
} > "$panel/BUILD"

# The window: the Swift shell, or the browser fallback.
shell=browser
if [ "${CW_CONTROL_APP_SHELL:-swift}" != browser ] && xcrun --find swiftc >/dev/null 2>&1; then
  if xcrun swiftc -O -swift-version 5 -parse-as-library \
    -o "$contents/MacOS/ComplianceWatch" "$HERE/shell/ControlApp.swift" >"$work/swiftc.log" 2>&1; then
    shell=swift
  else
    echo "note: the Swift window did not compile, so the app opens in a browser instead:"
    tail -n 20 "$work/swiftc.log" | sed 's/^/  /'
  fi
fi
repo_quoted="$(printf '%q' "$REPO")"
if [ "$shell" = browser ]; then
  cat > "$contents/MacOS/ComplianceWatch" <<LAUNCHER
#!/bin/bash
# ComplianceWatch Control without its Swift window: starts the helper this bundle carries on the
# checkout it was built for, and opens the UI in Google Chrome's app mode, else the default
# browser. The helper stops ten minutes after the last window closes.
panel="\$(cd "\$(dirname "\$0")/../Resources/control-panel" && pwd)" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:\$PATH"
export CW_CONTROL_PANEL_REPO=$repo_quoted
export PYTHONDONTWRITEBYTECODE=1
cd "\$CW_CONTROL_PANEL_REPO" || exit 1
if [ ! -x .venv/bin/python ]; then
  osascript -e 'display alert "ComplianceWatch Control" message "The checkout has no Python environment yet. In Terminal, run uv sync --all-packages in the checkout, then open the app again."' >/dev/null 2>&1
  exit 1
fi
demo=""
for arg in "\$@"; do [ "\$arg" = --demo ] && demo=--demo; done
logs="\$HOME/Library/Logs/ComplianceWatch Control"
mkdir -p "\$logs"
nohup .venv/bin/python -B "\$panel/panel_server.py" --open app --detach \$demo </dev/null >/dev/null 2>>"\$logs/helper.log" &
LAUNCHER
fi
chmod +x "$contents/MacOS/ComplianceWatch"

# The icon: drawn in Python at every size, packed by iconutil.
icon=""
python="$REPO/.venv/bin/python"
[ -x "$python" ] || python="$(command -v python3 || true)"
if [ -n "$python" ] && command -v iconutil >/dev/null 2>&1 \
  && "$python" -B "$HERE/shell/app_icon.py" "$work/AppIcon.iconset" \
  && iconutil -c icns "$work/AppIcon.iconset" -o "$contents/Resources/AppIcon.icns"; then
  icon=AppIcon
else
  echo "note: no app icon (it needs python3 and iconutil); the app gets the default one"
fi

xml() { local s="$1"; s="${s//&/&amp;}"; s="${s//</&lt;}"; s="${s//>/&gt;}"; printf '%s' "$s"; }
{
  cat <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key><string>ComplianceWatch</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>2.0</string>
  <key>CFBundleVersion</key><string>2</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSPrincipalClass</key><string>NSApplication</string>
  <key>LSApplicationCategoryType</key><string>public.app-category.developer-tools</string>
  <key>NSAppTransportSecurity</key><dict><key>NSAllowsLocalNetworking</key><true/></dict>
PLIST
  echo "  <key>CFBundleName</key><string>$(xml "$NAME")</string>"
  echo "  <key>CFBundleDisplayName</key><string>$(xml "$SHOWN")</string>"
  echo "  <key>CFBundleIdentifier</key><string>$BUNDLE_ID</string>"
  [ -n "$icon" ] && echo "  <key>CFBundleIconFile</key><string>$icon</string>"
  echo "  <key>CWCheckout</key><string>$(xml "$REPO")</string>"
  echo "  <key>CWShell</key><string>$shell</string>"
  echo "</dict>"
  echo "</plist>"
} > "$contents/Info.plist"
if command -v plutil >/dev/null 2>&1; then plutil -lint "$contents/Info.plist" >/dev/null; fi

if [ -e "$APP" ] || [ -L "$APP" ]; then
  aside="$(mktemp -d "$DEST/.ComplianceWatch-old.XXXXXX")"
  mv "$APP" "$aside/$NAME.app"
fi
mv "$new" "$APP"
swapped=1
touch "$APP"  # Finder and the Dock pick up the new icon

# LaunchServices: the paths the new and the old app passed through, and any other copy of this
# app it knows at another path (an install this one replaces), are unregistered, so macOS lists
# the app once. A same-path swap needs nothing more.
if [ -n "$LSREGISTER" ] && [ -x "$LSREGISTER" ]; then
  forget=("$new")
  [ -n "$aside" ] && forget+=("$aside/$NAME.app")
  while IFS= read -r known; do
    [ "$known" = "$APP" ] || [ "$known" = "$new" ] && continue
    [ -n "$aside" ] && [ "$known" = "$aside/$NAME.app" ] && continue
    forget+=("$known")
    if [ -e "$known" ]; then
      echo "note: another copy of this app is at $known; macOS no longer lists it, delete it if it is old"
    fi
  done < <("$LSREGISTER" -dump 2>/dev/null | awk -v id="$BUNDLE_ID" '
    /^-+$/ { path = ""; next }
    /^path:/ { path = $0; sub(/^path:[[:space:]]+/, "", path); sub(/ \(0x[0-9a-fA-F]+\)$/, "", path); next }
    /^identifier:/ { if ($2 == id && path != "") { print path; path = "" } }')
  for known in "${forget[@]}"; do "$LSREGISTER" -u "$known" >/dev/null 2>&1 || true; done
fi

echo "built $APP"
echo "  window: $([ "$shell" = swift ] && echo "the Swift shell" || echo "a browser (no swiftc)"), icon: ${icon:-none}"
echo "  build $(sed -n 's/^built=//p' "$APP/Contents/Resources/control-panel/BUILD"), commit ${commit:-none}, files $files, for $REPO"
