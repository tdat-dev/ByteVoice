"""
WakerVoice — Cửa sổ điều khiển Dịch nhanh (PySide6)
====================================================
Thay việc mò trong menu chuột phải bé tí bằng một cửa sổ điều khiển thật:
  - Nút BẬT/TẮT lớn + đèn "đang nghe".
  - Chọn chế độ STT: Groq (batch ~1s) hoặc Deepgram (streaming ~0.3s).
  - Nguồn nghe (mic/hệ thống), ngôn ngữ nghe -> dịch sang.
  - Khoá API (Deepgram cho streaming, Google cho dịch) + nút Test.

Thiết kế bám đúng bản sắc app: nền tối bo góc như Pill/overlay, accent xanh (Bạn) /
cam (Hệ thống), một màu nhấn chủ đạo, tiết chế. Frameless, kéo tiêu đề để di chuyển.
Nuốt mọi lỗi UI -> app không chết vì panel.
"""

import threading

from PySide6.QtCore import Qt, QTimer, QPoint
from PySide6.QtGui import QFont, QColor, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QComboBox, QLineEdit, QButtonGroup, QFrame, QSizePolicy,
)

import config

# Bảng màu — bám overlay (nền 18,18,22) + accent mic/hệ thống có sẵn.
BG        = "#15161B"
CARD      = "#1E2028"
CARD_Hi   = "#262933"
TEXT      = "#ECEDF1"
MUTED     = "#969BA6"
BORDER    = "rgba(255,255,255,0.07)"
ACCENT    = "#6C7BFF"          # indigo nhấn chủ đạo
LIVE      = "#34C56A"          # xanh "đang nghe"
MIC_CLR   = "#82AAFF"
SYS_CLR   = "#FFAA6E"

# Ngôn ngữ (đồng bộ với settings_ui / app_qt)
TARGET_LANGS = [
    ("en", "English"), ("vi", "Tiếng Việt"), ("ja", "日本語"),
    ("ko", "한국어"), ("zh-CN", "中文"), ("fr", "Français"),
    ("es", "Español"), ("de", "Deutsch"), ("ru", "Русский"),
    ("th", "ไทย"), ("id", "Bahasa Indonesia"),
]
SOURCE_LANGS = [("auto", "Tự động")] + TARGET_LANGS
AUDIO_SOURCES = [
    ("system", "Chỉ hệ thống (game/video)"),
    ("both", "Mic + Hệ thống"),
    ("mic", "Chỉ mic (giọng bạn)"),
]

_QSS = f"""
#root {{ background: {BG}; border-radius: 18px; border: 1px solid {BORDER}; }}
QWidget {{ color: {TEXT}; font-family: 'Segoe UI'; }}
#title {{ font-size: 15px; font-weight: 600; }}
#dot {{ font-size: 15px; }}
#close {{
    background: transparent; border: none; color: {MUTED};
    font-size: 18px; padding: 0 6px; border-radius: 8px;
}}
#close:hover {{ background: {CARD_Hi if False else CARD}; color: {TEXT}; }}
.section {{
    color: {MUTED}; font-size: 10px; font-weight: 700;
    letter-spacing: 1.4px; text-transform: uppercase;
}}
#hero {{
    border: none; border-radius: 14px; padding: 16px;
    font-size: 15px; font-weight: 600; color: white;
    background: {ACCENT};
}}
#hero:hover {{ background: #7C8AFF; }}
#hero[live="true"] {{ background: {LIVE}; }}
#hero[live="true"]:hover {{ background: #43D177; }}
#status {{ color: {MUTED}; font-size: 11px; }}
QPushButton.seg {{
    background: {CARD}; border: 1px solid {BORDER}; color: {MUTED};
    padding: 9px 12px; border-radius: 10px; font-size: 12px; text-align: left;
}}
QPushButton.seg:hover {{ background: {CARD_Hi}; }}
QPushButton.seg:checked {{
    background: {CARD_Hi}; color: {TEXT}; border: 1px solid {ACCENT};
}}
QComboBox {{
    background: {CARD}; border: 1px solid {BORDER}; border-radius: 9px;
    padding: 7px 10px; color: {TEXT}; font-size: 12px;
}}
QComboBox:hover {{ border: 1px solid rgba(255,255,255,0.18); }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {CARD}; color: {TEXT}; border: 1px solid {BORDER};
    selection-background-color: {ACCENT}; outline: none;
}}
QLineEdit {{
    background: {CARD}; border: 1px solid {BORDER}; border-radius: 9px;
    padding: 7px 10px; color: {TEXT}; font-size: 12px;
}}
QLineEdit:focus {{ border: 1px solid {ACCENT}; }}
QPushButton.mini {{
    background: {CARD}; border: 1px solid {BORDER}; color: {TEXT};
    padding: 7px 12px; border-radius: 9px; font-size: 12px;
}}
QPushButton.mini:hover {{ background: {CARD_Hi}; }}
#label {{ color: {MUTED}; font-size: 11px; }}
#hint {{ color: {MUTED}; font-size: 10px; }}
"""


def _combo(items, cur):
    c = QComboBox()
    for code, label in items:
        c.addItem(label, code)
    for i in range(c.count()):
        if c.itemData(i) == cur:
            c.setCurrentIndex(i)
            break
    return c


class TranslatePanel(QWidget):
    """Cửa sổ điều khiển Dịch nhanh. engine=TranslateEngine, notify=callback(str,int)."""

    def __init__(self, engine, notify=None, on_toggle=None, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.notify = notify or (lambda *_: None)
        # on_toggle: nếu có, app_qt điều phối bật/tắt (đồng bộ overlay + tray).
        self.on_toggle = on_toggle
        self._drag = None
        self._pulse_on = False

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowTitle("WakerVoice — Dịch nhanh")
        self.setFixedWidth(420)

        cfg = config.load()
        self._build(cfg)
        self.setStyleSheet(_QSS)

        # Nhịp nháy đèn "đang nghe"
        self._pulse = QTimer(self)
        self._pulse.timeout.connect(self._tick_pulse)
        self._refresh_running()

    # ----------------------- Dựng UI -----------------------
    def _build(self, cfg):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        root = QWidget(objectName="root")
        outer.addWidget(root)
        v = QVBoxLayout(root)
        v.setContentsMargins(20, 16, 20, 18)
        v.setSpacing(14)

        # Header
        head = QHBoxLayout()
        self.dot = QLabel("●", objectName="dot")
        self.dot.setStyleSheet(f"color:{MUTED}")
        title = QLabel("Dịch nhanh", objectName="title")
        close = QPushButton("✕", objectName="close")
        close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(self.hide)
        head.addWidget(self.dot)
        head.addSpacing(6)
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(close)
        v.addLayout(head)

        # Hero toggle
        self.hero = QPushButton("Bật dịch nhanh", objectName="hero")
        self.hero.setCursor(Qt.PointingHandCursor)
        self.hero.setMinimumHeight(52)
        self.hero.clicked.connect(self._toggle)
        v.addWidget(self.hero)
        self.status = QLabel("", objectName="status")
        self.status.setWordWrap(True)
        v.addWidget(self.status)

        # Chế độ STT (segmented)
        v.addWidget(self._section("Chế độ nhận dạng"))
        seg = QHBoxLayout()
        seg.setSpacing(8)
        self.mode_group = QButtonGroup(self)
        self.btn_batch = self._seg_btn("Groq · gửi cả cụm\n~1–1.5s")
        self.btn_stream = self._seg_btn("Deepgram · streaming\n~0.3s realtime")
        self.mode_group.addButton(self.btn_batch, 0)
        self.mode_group.addButton(self.btn_stream, 1)
        seg.addWidget(self.btn_batch)
        seg.addWidget(self.btn_stream)
        v.addLayout(seg)
        (self.btn_stream if cfg.get("translate_stt_mode") == "streaming"
         else self.btn_batch).setChecked(True)
        self.btn_batch.clicked.connect(lambda: self._set_mode("batch"))
        self.btn_stream.clicked.connect(lambda: self._set_mode("streaming"))

        # Ngôn ngữ + nguồn
        v.addWidget(self._section("Nghe & dịch"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        self.audio_combo = _combo(AUDIO_SOURCES, cfg.get("translate_audio_source") or "system")
        self.src_combo = _combo(SOURCE_LANGS, cfg.get("translate_source_lang") or "auto")
        self.tgt_combo = _combo(TARGET_LANGS, cfg.get("translate_target_lang") or "en")
        grid.addWidget(self._lbl("Nguồn nghe"), 0, 0)
        grid.addWidget(self.audio_combo, 1, 0, 1, 2)
        grid.addWidget(self._lbl("Ngôn ngữ nghe"), 2, 0)
        grid.addWidget(self._lbl("Dịch sang"), 2, 1)
        grid.addWidget(self.src_combo, 3, 0)
        grid.addWidget(self.tgt_combo, 3, 1)
        v.addLayout(grid)
        self.audio_combo.currentIndexChanged.connect(
            lambda: self.engine.set_audio_source(self.audio_combo.currentData()))
        self.src_combo.currentIndexChanged.connect(
            lambda: self.engine.set_source_lang(self.src_combo.currentData()))
        self.tgt_combo.currentIndexChanged.connect(
            lambda: self.engine.set_target_lang(self.tgt_combo.currentData()))

        # Khoá API
        v.addWidget(self._section("Khoá API"))
        self.dg_key = QLineEdit(cfg.get("deepgram_api_key") or "")
        self.dg_key.setEchoMode(QLineEdit.Password)
        self.dg_key.setPlaceholderText("Deepgram API key (cho streaming)…")
        v.addLayout(self._key_row(self.dg_key, "Deepgram", self._save_dg, self._test_dg))
        self.gg_key = QLineEdit(cfg.get("google_translate_api_key") or "")
        self.gg_key.setEchoMode(QLineEdit.Password)
        self.gg_key.setPlaceholderText("Google Translate API key (cho dịch)…")
        v.addLayout(self._key_row(self.gg_key, "Google", self._save_gg, self._test_gg))
        self.key_status = QLabel("", objectName="hint")
        self.key_status.setWordWrap(True)
        v.addWidget(self.key_status)

        v.addWidget(QLabel(
            "Streaming cần key Deepgram (deepgram.com, có free tier). Dịch cần key "
            "Google Translate. Đổi chế độ/ngôn ngữ khi đang bật sẽ tự áp lại.",
            objectName="hint", wordWrap=True))

    def _section(self, text):
        lb = QLabel(text)
        lb.setProperty("class", "section")
        lb.setStyleSheet(f"color:{MUTED}; font-size:10px; font-weight:700; letter-spacing:1.4px;")
        return lb

    def _lbl(self, text):
        lb = QLabel(text, objectName="label")
        return lb

    def _seg_btn(self, text):
        b = QPushButton(text)
        b.setProperty("class", "seg")
        b.setCheckable(True)
        b.setCursor(Qt.PointingHandCursor)
        b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        b.setMinimumHeight(48)
        return b

    def _key_row(self, edit, label, on_save, on_test):
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(edit, 1)
        save = QPushButton("Lưu")
        save.setProperty("class", "mini")
        save.setCursor(Qt.PointingHandCursor)
        save.clicked.connect(on_save)
        test = QPushButton("Test")
        test.setProperty("class", "mini")
        test.setCursor(Qt.PointingHandCursor)
        test.clicked.connect(on_test)
        row.addWidget(save)
        row.addWidget(test)
        return row

    # ----------------------- Hành vi -----------------------
    def _toggle(self):
        if self.on_toggle is not None:
            self.on_toggle()            # app_qt lo start/stop + overlay + tray
        elif self.engine.is_running():
            self.engine.stop()
        else:
            self.engine.start()
        self._refresh_running()

    def sync(self):
        """Cho app_qt gọi khi trạng thái đổi từ ngoài (tray) để panel cập nhật."""
        self._refresh_running()

    def _set_mode(self, mode):
        self.engine.set_stt_mode(mode)
        self._refresh_running()
        self.notify(f"Chế độ: {'Deepgram streaming' if mode=='streaming' else 'Groq batch'}", 2000)

    def _refresh_running(self):
        on = self.engine.is_running()
        streaming = getattr(self.engine, "stt_mode", "batch") == "streaming"
        self.hero.setText("● Đang nghe — bấm để tắt" if on else "Bật dịch nhanh")
        self.hero.setProperty("live", "true" if on else "false")
        self.hero.style().unpolish(self.hero)
        self.hero.style().polish(self.hero)
        self.dot.setStyleSheet(f"color:{LIVE if on else MUTED}")
        lat = "~0.3s (chữ chảy realtime)" if streaming else "~1–1.5s"
        self.status.setText(
            (f"Đang nghe · {'Deepgram' if streaming else 'Groq'} · độ trễ {lat}"
             if on else f"Đang tắt · sẽ dùng {'Deepgram' if streaming else 'Groq'} · {lat}"))
        if on:
            self._pulse.start(650)
        else:
            self._pulse.stop()

    def _tick_pulse(self):
        self._pulse_on = not self._pulse_on
        self.dot.setStyleSheet(f"color:{LIVE if self._pulse_on else '#1f6b3c'}")

    def _save_dg(self):
        self.engine.set_deepgram_api_key(self.dg_key.text())
        self.key_status.setText("✓ Đã lưu Deepgram key.")

    def _save_gg(self):
        self.engine.set_google_api_key(self.gg_key.text())
        self.key_status.setText("✓ Đã lưu Google key.")

    def _test_dg(self):
        self.engine.set_deepgram_api_key(self.dg_key.text())
        self.key_status.setText("Đang test Deepgram…")
        self._run_test(self.engine.test_deepgram_key, "Deepgram")

    def _test_gg(self):
        self.engine.set_google_api_key(self.gg_key.text())
        self.key_status.setText("Đang test Google…")
        self._run_test(self.engine.test_google_key, "Google")

    def _run_test(self, fn, name):
        def worker():
            try:
                ok, msg = fn()
            except Exception as e:
                ok, msg = False, str(e)
            # về GUI thread qua singleShot
            QTimer.singleShot(0, lambda: self.key_status.setText(
                f"{'✓' if ok else '✗'} {name}: {msg}"))
        threading.Thread(target=worker, daemon=True).start()

    def show_panel(self):
        """Hiện panel giữa màn hình, cập nhật trạng thái."""
        self._refresh_running()
        if not self.isVisible():
            from PySide6.QtGui import QGuiApplication
            g = QGuiApplication.primaryScreen().availableGeometry()
            self.adjustSize()
            self.move(g.center().x() - self.width() // 2,
                      g.center().y() - self.height() // 2)
        self.show()
        self.raise_()
        self.activateWindow()

    # Kéo tiêu đề để di chuyển (frameless)
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and e.position().y() < 46:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e):
        if self._drag is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag)
            e.accept()

    def mouseReleaseEvent(self, e):
        self._drag = None
