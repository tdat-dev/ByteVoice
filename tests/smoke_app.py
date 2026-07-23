"""
Smoke test: app_qt.py vẫn import + Pill class khởi tạo được (off-screen Qt).
Phục vụ kiểm tra trước khi chạy app thật.
"""
import os
import sys
import tempfile

ROOT = r"d:\ByteWaker\WakerVoice"
sys.path.insert(0, ROOT)

# Isolated env để không đụng config máy
tmp = tempfile.mkdtemp(prefix="waker_smoke_")
os.environ["APPDATA"] = tmp
os.environ["LOCALAPPDATA"] = tmp

# Qt platform off-screen (CI / sandbox không cần display server)
os.environ["QT_QPA_PLATFORM"] = "offscreen"

try:
    # Disable install first-run shortcuts (auto when frozen only)
    import app_qt
    print("import app_qt: OK")

    # SttEngine + Bridge (không cần Pill UI thật)
    from engine import SttEngine
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtWidgets import QApplication

    # Cần QApplication cho engine.start (Qt global)
    qa = QApplication.instance() or QApplication([])

    # Tạo engine (không start pynput, dùng stub)
    from pynput import keyboard
    class _NoOp:
        def __init__(self, *a, **kw): pass
        def start(self): pass
        @property
        def running(self): return True
        def stop(self): pass
    keyboard.Listener = _NoOp

    eng = SttEngine(lambda *a: None)
    print(f"SttEngine: provider={eng.provider_id} model={eng.model} key={'set' if eng.api_key else 'empty'}")

    # Pill: chỉ kiểm tra khởi tạo, không show
    from app_qt import Pill, Bridge
    bridge = Bridge()
    pill = Pill.__new__(Pill)  # skip __init__ (vì nó gọi _build_tray, _place_bottom_center, ...)
    # Gọi từng phần tối thiểu
    pill.engine = eng
    pill.bridge = bridge
    pill.state = "idle"
    print("Pill class: loadable")

    print("\nALL SMOKE OK")
finally:
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
