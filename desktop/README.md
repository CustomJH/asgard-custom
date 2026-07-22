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

The `.app` can also be opened directly when `asgard` is installed. Set
`ASGARD_EXECUTABLE` only when the executable is outside the normal install
locations.

## Build

```sh
cd desktop
npm install
npm run build -- --bundles app
# signed distribution build:
npm run bundle:mac
```

macOS distribution still requires the normal Apple signing and notarization
credentials.
