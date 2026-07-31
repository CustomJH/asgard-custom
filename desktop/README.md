# Asgard Desktop native shell

Tauri owns the native window and application lifecycle. The existing Python
Desktop server remains the single runtime/API implementation, so the browser
fallback and native app cannot drift.

## Run

```sh
uv run asgard desktop
```

The command opens the built Tauri app when available and otherwise opens the
browser. Use `--browser` to force the browser or `--no-open` to serve only.

The `.app` or Windows `.exe` can also be opened directly when `asgard` is installed. Set
`ASGARD_EXECUTABLE` only when the executable is outside the normal install
locations.

## Build

```sh
cd desktop
npm install
npm run build -- --bundles app
# signed distribution build:
npm run bundle:mac
# Windows (run on Windows):
npm run bundle:windows
```

macOS distribution still requires the normal Apple signing and notarization
credentials. Windows produces a per-user NSIS installer and requires code
signing before public distribution.

On macOS the launcher opens `…/Asgard Desktop.app/Contents/MacOS/asgard-desktop`
rather than the bare `target/release` binary: a bare binary has no bundle, so the
Dock shows a generic icon and no application name. Build the `app` bundle at
least once for the native window to carry its own face.

## Icons

`assets/asgard-yggdrasil-production-mark.png` is the source mark. It has no
background of its own, so the icon set is baked from it — the brand night behind
it, the macOS icon grid around it:

```sh
uv run --no-project --with pillow desktop/src-tauri/icons/build_icons.py
npm run build -- --bundles app   # the bundle only picks up icons on a rebuild
```

That writes `desktop/app-icon.png` (1024 master) and every size Tauri references
in `tauri.conf.json`. Copy `icons/128x128@2x.png` to
`src/asgard/assets/app-icon.png` when the mark changes — that is the copy the
browser fallback serves as its tab icon.
