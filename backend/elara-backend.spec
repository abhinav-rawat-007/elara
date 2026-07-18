# PyInstaller spec — freezes the Elara backend into a single elara-backend.exe
# that the Tauri shell ships as a sidecar.
#
# Build:  cd backend && ..\backend\.venv\Scripts\pyinstaller elara-backend.spec
# Output: backend/dist/elara-backend.exe
#
# The heavy ML/voice packages ship data files and dynamic imports PyInstaller
# can't see by static analysis, so we collect them wholesale. The Kokoro model
# files (~340 MB) are intentionally NOT bundled — they're downloaded once at
# first run into %APPDATA%\Elara\models (see backend/paths.py).

from PyInstaller.utils.hooks import collect_all

_bundle = [
    "faster_whisper",
    "kokoro_onnx",
    "ddgs",
    "trafilatura",
    "sounddevice",
    "pycaw",
    "comtypes",
    "screen_brightness_control",
    # agentic layer: cloud brain, browser control, native-app control
    "anthropic",
    "playwright",
    "pywinauto",
]

datas = [("characters/elara.yaml", "characters")]
binaries = []
hiddenimports = [
    "uvicorn",
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
]

for pkg in _bundle:
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h


a = Analysis(
    ["main.py"],
    pathex=[".."],  # so `import backend.*` resolves from the project root
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="elara-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,       # no console window; the Tauri shell owns the UI
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
