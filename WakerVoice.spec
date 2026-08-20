# -*- mode: python ; coding: utf-8 -*-
# Bản CLOUD-ONLY (Groq): KHÔNG bundle faster-whisper / ctranslate2 / CUDA.
# Nhận dạng chạy qua Groq API (stdlib urllib) -> bundle nhỏ (~vài chục MB).
import os
import sys
from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []

# --- OpenSSL: ép dùng libcrypto/libssl KHỚP với _ssl.pyd của Python này ---
# PyInstaller dò phụ thuộc của _ssl.pyd bằng cách quét PATH; nếu máy có
# libcrypto-3-x64.dll khác (VD Laragon/PHP, mingw) đứng trước trên PATH thì nó
# bundle NHẦM bản OpenSSL đó -> lệch phiên bản -> _ssl.pyd văng 0xC0000139
# (ENTRYPOINT_NOT_FOUND) -> `import ssl` chết ngầm -> urllib mất handler https
# -> mọi request Groq báo "unknown url type: https" -> không ra chữ.
# Fix: (1) đưa thư mục DLLs của Python lên ĐẦU PATH để bản đúng được dò trước,
#      (2) thêm thẳng các DLL đúng vào binaries làm chốt chặn cuối.
_dll_dir = os.path.join(sys.base_prefix, "DLLs")
os.environ["PATH"] = _dll_dir + os.pathsep + os.environ.get("PATH", "")
for _n in ("libcrypto-3-x64.dll", "libssl-3-x64.dll", "_ssl.pyd", "_hashlib.pyd"):
    _p = os.path.join(_dll_dir, _n)
    if os.path.exists(_p):
        binaries.append((_p, "."))

# Native của sounddevice (portaudio) cho thu mic; pyaudiowpatch (WASAPI loopback)
# cho translate mode thu system-audio. pyaudiowpatch được import LỒNG trong
# translate_engine.start() nên PyInstaller dễ bỏ sót -> ép collect_all để chắc
# chắn native _portaudio đi kèm, không thì "Hệ thống" (system audio) chết trong exe.
for pkg in ("sounddevice", "pyaudiowpatch"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# websocket-client cho Deepgram streaming (import lồng trong deepgram_stream)
try:
    d, b, h = collect_all("websocket")
    datas += d
    binaries += b
    hiddenimports += h
except Exception:
    pass

hiddenimports += ["pynput.keyboard._win32", "pynput.mouse._win32",
                  "translate_audio", "translate_engine", "google_translate",
                  "caption_overlay", "text_filters", "deepgram_stream",
                  "translate_panel", "control_center", "websocket"]

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
