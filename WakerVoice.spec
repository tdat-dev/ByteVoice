# -*- mode: python ; coding: utf-8 -*-
# Bản CLOUD-ONLY (Groq): KHÔNG bundle faster-whisper / ctranslate2 / CUDA.
# Nhận dạng chạy qua Groq API (stdlib urllib) -> bundle nhỏ (~vài chục MB).
import os
from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []

# Chỉ cần native của sounddevice (portaudio) cho việc thu mic.
for pkg in ("sounddevice",):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

hiddenimports += ["pynput.keyboard._win32", "pynput.mouse._win32"]

a = Analysis(
    ["app_qt.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # Loại hẳn engine cục bộ + đồ nặng không dùng ở bản cloud-only.
    excludes=[
        "faster_whisper", "ctranslate2", "onnxruntime", "av",
        "torch", "noisereduce", "scipy", "matplotlib", "tkinter",
        "pywebview", "pystray", "PyQt5", "PyQt6",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="WakerVoice",
    debug=False,
    strip=False,
    upx=False,
    console=False,                 # app cửa sổ, không console
    icon="icon.ico",
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="WakerVoice",
)
