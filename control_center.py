"""
WakerVoice — Control Center (PySide6)
======================================
MỘT cửa sổ điều khiển duy nhất cho cả app — thay hẳn menu khay list dài. Gọi thẳng
method Pill sẵn có (một nguồn chân lý, không nhân đôi logic).

Thiết kế (áp craft-rules build-premium-website, route DASHBOARD_PRODUCT):
  - Chiến lược màu RESTRAINED: nền trung tính tối + MỘT accent indigo; xanh lá CHỈ
    cho trạng thái "đang nghe". Không nhồi 4 màu.
  - KHÔNG eyebrow chữ-hoa-tracked trên mỗi nhóm (scaffold grammar) — tiêu đề nhóm
    thường, tĩnh, nhẹ.
  - Segoe UI (giữ nhận diện app, phủ đủ dấu tiếng Việt) với tương phản theo weight.
  - Contrast chữ đạt ngưỡng; công tắc gạt tự vẽ; frameless bo góc, kéo header.
Nuốt lỗi -> app không chết vì panel.
"""

import threading

from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import QPainter, QColor, QGuiApplication, QLinearGradient
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QLineEdit, QFrame, QScrollArea, QSizePolicy, QButtonGroup,
)

import config
import install
import providers as stt_providers

# ----------------------- Tokens (RESTRAINED) -----------------------
BG0   = "#0F1015"      # nền cửa sổ (sâu)
BG1   = "#171922"      # nền nhóm
BG2   = "#1F222C"      # nền control
BG2H  = "#282C38"      # hover
LINE  = "rgba(255,255,255,0.06)"
INK   = "#ECEEF3"      # chữ chính
INK2  = "#AEB3C0"      # chữ phụ (đạt >=4.5:1 trên BG1)
INK3  = "#868C9A"      # gợi ý
ACCENT   = "#6C7BFF"   # accent DUY NHẤT (hành động/chọn)
ACCENT_H = "#7F8CFF"
LIVE  = "#33C86B"      # CHỈ dùng cho trạng thái đang nghe
DANGER = "#FF7D7D"

STT_LANGS = [("auto", "Tự động"), ("vi", "Tiếng Việt"), ("en", "English")]
SOURCE_LANGS = [
    ("auto", "Tự động"), ("vi", "Tiếng Việt"), ("en", "English"),
    ("ja", "日本語"), ("ko", "한국어"), ("zh-CN", "中文"),
]
TARGET_LANGS = [
    ("en", "English"), ("vi", "Tiếng Việt"), ("ja", "日本語"),
    ("ko", "한국어"), ("zh-CN", "中文"), ("fr", "Français"),
    ("es", "Español"), ("de", "Deutsch"),
]
AUDIO_SOURCES = [
    ("system", "Chỉ hệ thống"), ("both", "Mic + Hệ thống"), ("mic", "Chỉ mic"),
]


def _combo(items, cur):
    c = QComboBox()
    for code, label in items:
        c.addItem(label, code)
    for i in range(c.count()):
        if c.itemData(i) == cur:
            c.setCurrentIndex(i)
            break
    return c


class Switch(QWidget):
    """Công tắc gạt: xám (tắt) / xanh live (bật)."""

    def __init__(self, checked=False, on_toggle=None):
        super().__init__()
        self._on = bool(checked)
        self._cb = on_toggle
        self.setFixedSize(44, 25)
        self.setCursor(Qt.PointingHandCursor)

    def isChecked(self):
        return self._on

    def setChecked(self, v):
        self._on = bool(v); self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._on = not self._on
            self.update()
            if self._cb:
                self._cb(self._on)

    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(LIVE) if self._on else QColor("#3A3E4A"))
        p.drawRoundedRect(QRectF(0, 0, w, h), h / 2, h / 2)
        d = h - 6
        x = (w - d - 3) if self._on else 3
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(QRectF(x, 3, d, d))
        p.end()


class Group(QFrame):
    """Nhóm control: tiêu đề thường (KHÔNG eyebrow) + các hàng."""

    def __init__(self, title):
        super().__init__()
        self.setObjectName("group")
        self.v = QVBoxLayout(self)
        self.v.setContentsMargins(16, 14, 16, 16)
        self.v.setSpacing(12)
        t = QLabel(title, objectName="grouptitle")
        self.v.addWidget(t)

    def row(self, label, control, fill=True):
        r = QHBoxLayout()
        r.setSpacing(12)
        lb = QLabel(label, objectName="rowlabel")
        lb.setMinimumWidth(150)
        r.addWidget(lb)
        if fill:
            control.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            r.addWidget(control, 1)
        else:
            r.addStretch(1)
            r.addWidget(control)
        self.v.addLayout(r)
        return control

    def add(self, w):
        self.v.addWidget(w); return w

    def divider(self):
        ln = QFrame(); ln.setFixedHeight(1)
        ln.setStyleSheet(f"background:{LINE}; border:none;")
        self.v.addWidget(ln)


_QSS = f"""
#root {{ background:{BG0}; border-radius:20px; border:1px solid {LINE}; }}
QWidget {{ color:{INK}; font-family:'Segoe UI'; font-size:12px; }}
QScrollArea, QScrollArea>QWidget>QWidget {{ background:transparent; border:none; }}
QScrollBar:vertical {{ background:transparent; width:9px; margin:4px 2px; }}
QScrollBar::handle:vertical {{ background:rgba(255,255,255,0.13); border-radius:4px; min-height:32px; }}
QScrollBar::handle:vertical:hover {{ background:rgba(255,255,255,0.22); }}
QScrollBar::add-line,QScrollBar::sub-line {{ height:0; }}
QScrollBar::add-page,QScrollBar::sub-page {{ background:transparent; }}

#appname {{ font-size:15px; font-weight:600; letter-spacing:0.2px; }}
#ver {{ color:{INK3}; font-size:11px; }}
#close {{ background:transparent; border:none; color:{INK3}; font-size:17px; padding:2px 8px; border-radius:9px; }}
#close:hover {{ background:{BG2}; color:{INK}; }}

#group {{ background:{BG1}; border:1px solid {LINE}; border-radius:16px; }}
#grouptitle {{ color:{INK}; font-size:13px; font-weight:600; }}
#rowlabel {{ color:{INK2}; font-size:12px; }}
#hint {{ color:{INK3}; font-size:11px; }}

QPushButton#hero {{ background:{ACCENT}; border:none; border-radius:13px; color:#FFFFFF;
    font-size:14px; font-weight:600; padding:14px; }}
QPushButton#hero:hover {{ background:{ACCENT_H}; }}
QPushButton#hero[live="true"] {{ background:{LIVE}; }}
QPushButton#hero[live="true"]:hover {{ background:#3ED37A; }}

QComboBox {{ background:{BG2}; border:1px solid {LINE}; border-radius:9px; padding:7px 11px;
    color:{INK}; font-size:12px; min-width:130px; }}
QComboBox:hover {{ border:1px solid rgba(255,255,255,0.16); }}
QComboBox::drop-down {{ border:none; width:20px; }}
QComboBox QAbstractItemView {{ background:{BG2}; color:{INK}; border:1px solid {LINE};
    border-radius:8px; selection-background-color:{ACCENT}; padding:4px; outline:none; }}

QLineEdit {{ background:{BG2}; border:1px solid {LINE}; border-radius:9px; padding:7px 11px;
    color:{INK}; font-size:12px; }}
QLineEdit:focus {{ border:1px solid {ACCENT}; }}

QPushButton.seg {{ background:{BG2}; border:1px solid {LINE}; color:{INK2};
    padding:8px 12px; border-radius:10px; font-size:12px; }}
QPushButton.seg:hover {{ background:{BG2H}; color:{INK}; }}
QPushButton.seg:checked {{ background:{ACCENT}; color:#FFFFFF; border:1px solid {ACCENT}; }}

QPushButton.act {{ background:{BG2}; border:1px solid {LINE}; color:{INK};
    padding:10px 12px; border-radius:11px; font-size:12px; text-align:left; }}
QPushButton.act:hover {{ background:{BG2H}; }}
QPushButton.mini {{ background:{BG2}; border:1px solid {LINE}; color:{INK};
    padding:7px 12px; border-radius:9px; font-size:12px; }}
QPushButton.mini:hover {{ background:{BG2H}; }}
QPushButton#danger {{ background:transparent; border:1px solid {LINE}; color:{DANGER};
    padding:10px 12px; border-radius:11px; font-size:12px; }}
QPushButton#danger:hover {{ background:rgba(255,90,90,0.10); }}
#status {{ color:{INK2}; font-size:11px; }}
#keystatus {{ color:{INK3}; font-size:11px; }}
"""


class ControlCenter(QWidget):
    def __init__(self, pill):
        super().__init__()
        self.pill = pill
        self.engine = pill.engine
        self.te = pill.translate_engine
        self._drag = None

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowTitle("WakerVoice — Bảng điều khiển")
        self.setFixedWidth(460)
        self.setStyleSheet(_QSS)
        self._build()
        self._pulse = QTimer(self); self._pulse.timeout.connect(lambda: None)

    # ----------------------- Dựng -----------------------
    def _build(self):
        from version import __version__
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        self._root = QWidget(objectName="root")
        outer.addWidget(self._root)
        rv = QVBoxLayout(self._root); rv.setContentsMargins(0, 0, 0, 0); rv.setSpacing(0)

        # Header
        head = QHBoxLayout(); head.setContentsMargins(22, 18, 14, 10)
        name = QLabel("WakerVoice", objectName="appname")
        ver = QLabel(f"v{__version__}", objectName="ver")
        close = QPushButton("✕", objectName="close"); close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(self.hide)
        head.addWidget(name); head.addSpacing(9); head.addWidget(ver)
        head.addStretch(1); head.addWidget(close)
        rv.addLayout(head)

        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget(); b = QVBoxLayout(body)
        b.setContentsMargins(18, 4, 18, 18); b.setSpacing(13)
        scroll.setWidget(body); rv.addWidget(scroll)
        self.setMaximumHeight(780)

        b.addWidget(self._grp_translate())
        b.addWidget(self._grp_voice())
        b.addWidget(self._grp_system())

    # ---- Dịch nhanh ----
    def _grp_translate(self):
        g = Group("Dịch nhanh realtime")
        self.tr_hero = QPushButton(objectName="hero"); self.tr_hero.setCursor(Qt.PointingHandCursor)
        self.tr_hero.clicked.connect(lambda: (self.pill._panel_toggle(), self._refresh()))
        g.add(self.tr_hero)
        self.tr_status = QLabel("", objectName="status"); self.tr_status.setWordWrap(True)
        g.add(self.tr_status)

        seg = QHBoxLayout(); seg.setSpacing(8)
        self.m_batch = self._seg("Groq · ~1s")
        self.m_stream = self._seg("Deepgram · ~0.3s")
        grp = QButtonGroup(self); grp.addButton(self.m_batch); grp.addButton(self.m_stream)
        self.m_batch.clicked.connect(lambda: (self.te.set_stt_mode("batch"), self._refresh()))
        self.m_stream.clicked.connect(lambda: (self.te.set_stt_mode("streaming"), self._refresh()))
        for w_ in (self.m_batch, self.m_stream):
            w_.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred); seg.addWidget(w_)
        g.v.addLayout(seg)

        self.tr_audio = _combo(AUDIO_SOURCES, self.te.audio_source)
        self.tr_audio.currentIndexChanged.connect(
            lambda: self.te.set_audio_source(self.tr_audio.currentData()))
        g.row("Nguồn nghe", self.tr_audio)
        self.tr_src = _combo(SOURCE_LANGS, self.te.source_lang)
        self.tr_src.currentIndexChanged.connect(
            lambda: self.te.set_source_lang(self.tr_src.currentData()))
        g.row("Ngôn ngữ nghe", self.tr_src)
        self.tr_tgt = _combo(TARGET_LANGS, self.te.target_lang)
        self.tr_tgt.currentIndexChanged.connect(
            lambda: self.te.set_target_lang(self.tr_tgt.currentData()))
        g.row("Dịch sang", self.tr_tgt)

        g.divider()
        cfg = config.load()
        self.dg_key = self._passwd(cfg.get("deepgram_api_key") or "", "Deepgram key (cho streaming ~0.3s)…")
        g.add(self._keyrow(self.dg_key, self._save_dg, self._test_dg))
        self.gg_key = self._passwd(cfg.get("google_translate_api_key") or "", "Google Translate key (để dịch)…")
        g.add(self._keyrow(self.gg_key, self._save_gg, self._test_gg))
        self.key_status = QLabel("", objectName="keystatus"); self.key_status.setWordWrap(True)
        g.add(self.key_status)
        return g

    # ---- Gõ bằng giọng ----
    def _grp_voice(self):
        import engine as em
        g = Group("Gõ bằng giọng")
        hk = em.HOTKEY_LABELS.get(self.engine.hotkey_name, self.engine.hotkey_name)
        talk = QPushButton(f"Bật/tắt nói  ·  phím {hk}")
        talk.setProperty("class", "act"); talk.setCursor(Qt.PointingHandCursor)
        talk.clicked.connect(self.engine.toggle)
        g.add(talk)

        lb = QLabel("Ngôn ngữ nhận dạng", objectName="rowlabel"); g.add(lb)
        seg = QHBoxLayout(); seg.setSpacing(8)
        self._v_lang = {}
        for code, label in STT_LANGS:
            btn = self._seg(label); btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            btn.clicked.connect(lambda _=False, cc=code: (self.pill._set_language(cc), self._refresh()))
            self._v_lang[code] = btn; seg.addWidget(btn)
        g.v.addLayout(seg)

        self.v_model = _combo([(m, self._short(m)) for m in self.engine.provider.get("models", [])],
                              self.engine.model)
        self.v_model.currentIndexChanged.connect(
            lambda: self.pill._set_model(self.v_model.currentData()))
        g.row("Chất lượng nhận dạng", self.v_model)
        self.v_prov = _combo([(pid, p["display_name"]) for pid, p in stt_providers.all_providers().items()],
                             self.engine.provider_id)
        self.v_prov.currentIndexChanged.connect(self._on_provider)
        g.row("Nhà cung cấp STT", self.v_prov)
        self.v_refine = Switch(self.engine.refine, self._set_refine)
        g.row("Dọn chính tả bằng AI (+0.5s)", self.v_refine, fill=False)

        key = QPushButton("Đổi / nhập Groq API key…")
        key.setProperty("class", "act"); key.setCursor(Qt.PointingHandCursor)
        key.clicked.connect(self.pill._enter_groq_key)
        g.add(key)
        return g

    # ---- Hệ thống ----
    def _grp_system(self):
        g = Group("Hệ thống")
        self.sw_start = Switch(install.startup_enabled(), self._set_startup)
        g.row("Khởi động cùng Windows", self.sw_start, fill=False)
        g.divider()
        for text, fn in (
            ("Tạo lối tắt (Start Menu + Desktop)", self._shortcuts),
            ("Kiểm tra cập nhật", self.pill._manual_check),
            ("Snippets · text-expansion…", self.pill._open_snippets_editor),
            ("Cài đặt nâng cao…", self.pill._open_settings),
        ):
            btn = QPushButton(text); btn.setProperty("class", "act")
            btn.setCursor(Qt.PointingHandCursor); btn.clicked.connect(fn); g.add(btn)
        quit_btn = QPushButton("Thoát WakerVoice"); quit_btn.setObjectName("danger")
        quit_btn.setCursor(Qt.PointingHandCursor); quit_btn.clicked.connect(self.pill._quit)
        g.add(quit_btn)
        return g

    # ----------------------- helpers -----------------------
    def _seg(self, text):
        b = QPushButton(text); b.setProperty("class", "seg"); b.setCheckable(True)
        b.setCursor(Qt.PointingHandCursor); return b

    def _passwd(self, val, ph):
        e = QLineEdit(val); e.setEchoMode(QLineEdit.Password); e.setPlaceholderText(ph)
        return e

    def _keyrow(self, edit, on_save, on_test):
        w = QWidget(); r = QHBoxLayout(w); r.setContentsMargins(0, 0, 0, 0); r.setSpacing(8)
        r.addWidget(edit, 1)
        s = QPushButton("Lưu"); s.setProperty("class", "mini"); s.setCursor(Qt.PointingHandCursor)
        s.clicked.connect(on_save)
        t = QPushButton("Test"); t.setProperty("class", "mini"); t.setCursor(Qt.PointingHandCursor)
        t.clicked.connect(on_test)
        r.addWidget(s); r.addWidget(t)
        return w

    @staticmethod
    def _short(m):
        return m.replace("whisper-", "").replace("gpt-4o-", "gpt-").replace("-v3", "")

    def _on_provider(self):
        self.pill._set_provider(self.v_prov.currentData())
        self.v_model.blockSignals(True); self.v_model.clear()
        for m in self.engine.provider.get("models", []):
            self.v_model.addItem(self._short(m), m)
        for i in range(self.v_model.count()):
            if self.v_model.itemData(i) == self.engine.model:
                self.v_model.setCurrentIndex(i); break
        self.v_model.blockSignals(False)

    def _set_refine(self, on):
        self.engine.set_refine(on)
        self.pill._notify("Bật dọn chính tả AI." if on else "Tắt dọn chính tả AI.", 1800)

    def _set_startup(self, on):
        try:
            install.set_startup(on)
        except Exception as e:
            self.pill._notify(f"Lỗi startup: {e}", 3000)

    def _shortcuts(self):
        try:
            install.create_shortcuts(); self.pill._notify("Đã tạo lối tắt.", 2000)
        except Exception as e:
            self.pill._notify(f"Lỗi tạo lối tắt: {e}", 3000)

    def _save_dg(self):
        self.te.set_deepgram_api_key(self.dg_key.text()); self.key_status.setText("Đã lưu Deepgram key.")

    def _save_gg(self):
        self.te.set_google_api_key(self.gg_key.text()); self.key_status.setText("Đã lưu Google key.")

    def _test_dg(self):
        self.te.set_deepgram_api_key(self.dg_key.text())
        self.key_status.setText("Đang test Deepgram…"); self._run_test(self.te.test_deepgram_key, "Deepgram")

    def _test_gg(self):
        self.te.set_google_api_key(self.gg_key.text())
        self.key_status.setText("Đang test Google…"); self._run_test(self.te.test_google_key, "Google")

    def _run_test(self, fn, name):
        def worker():
            try:
                ok, msg = fn()
            except Exception as e:
                ok, msg = False, str(e)
            QTimer.singleShot(0, lambda: self.key_status.setText(f"{'✓' if ok else '✗'} {name}: {msg}"))
        threading.Thread(target=worker, daemon=True).start()

    # ----------------------- trạng thái -----------------------
    def _refresh(self):
        on = self.te.is_running()
        streaming = getattr(self.te, "stt_mode", "batch") == "streaming"
        self.tr_hero.setText("Đang nghe — bấm để tắt" if on else "Bật dịch nhanh")
        self.tr_hero.setProperty("live", "true" if on else "false")
        self.tr_hero.style().unpolish(self.tr_hero); self.tr_hero.style().polish(self.tr_hero)
        self.tr_status.setText(
            ("Đang nghe" if on else "Đang tắt") + " · "
            + ("Deepgram streaming ~0.3s (chữ chảy realtime)" if streaming else "Groq batch ~1–1.5s"))
        (self.m_stream if streaming else self.m_batch).setChecked(True)
        for code, btn in getattr(self, "_v_lang", {}).items():
            btn.setChecked(code == self.engine.language)

    def show_center(self):
        self._refresh()
        if not self.isVisible():
            self.adjustSize()
            gm = QGuiApplication.primaryScreen().availableGeometry()
            self.move(gm.center().x() - self.width() // 2, max(20, gm.center().y() - self.height() // 2))
        self.show(); self.raise_(); self.activateWindow()

    # header vẽ nền gradient nhẹ (không dây vào QSS translucent)
    def paintEvent(self, e):
        pass

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and e.position().y() < 54:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):
        self._drag = None
