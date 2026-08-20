"""
WakerVoice — Control Center (PySide6)
======================================
Biến cả menu chuột phải (list dài) thành MỘT cửa sổ điều khiển: card có nhóm,
công tắc gạt, dropdown, nút bấm — như trang settings xịn. Mọi thứ gọi thẳng các
method sẵn có của Pill (một nguồn chân lý, không viết trùng logic).

Thiết kế bám bản sắc app (nền tối bo góc như Pill/overlay, một accent indigo,
accent xanh live). Frameless, kéo tiêu đề để di chuyển. Nuốt lỗi -> app không chết.
"""

from PySide6.QtCore import Qt, QTimer, QRectF, QSize
from PySide6.QtGui import QPainter, QColor, QFont, QPainterPath, QGuiApplication
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QComboBox, QFrame, QScrollArea, QSizePolicy, QButtonGroup,
)

import config
import install
import providers as stt_providers
from translate_panel import (
    BG, CARD, CARD_Hi, TEXT, MUTED, BORDER, ACCENT, LIVE, MIC_CLR, SYS_CLR,
    SOURCE_LANGS, TARGET_LANGS, _combo,
)

STT_LANGS = [("auto", "Tự động"), ("vi", "Tiếng Việt"), ("en", "English")]


# ----------------------- Công tắc gạt tùy biến -----------------------
class Switch(QWidget):
    """Công tắc gạt kiểu iOS: xám (tắt) / xanh accent (bật). click -> toggled(bool)."""

    def __init__(self, checked=False, on_toggle=None, parent=None):
        super().__init__(parent)
        self._checked = bool(checked)
        self._on_toggle = on_toggle
        self.setFixedSize(46, 26)
        self.setCursor(Qt.PointingHandCursor)

    def isChecked(self):
        return self._checked

    def setChecked(self, v):
        self._checked = bool(v)
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._checked = not self._checked
            self.update()
            if self._on_toggle:
                self._on_toggle(self._checked)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        track = QColor(LIVE) if self._checked else QColor("#3A3D47")
        p.setBrush(track)
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRectF(0, 0, w, h), h / 2, h / 2)
        d = h - 6
        x = (w - d - 3) if self._checked else 3
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(QRectF(x, 3, d, d))
        p.end()


def _title_font():
    f = QFont("Segoe UI", 15)
    f.setWeight(QFont.Weight.DemiBold)
    return f


class Card(QFrame):
    """Khung nhóm: tiêu đề + nội dung dạng hàng label|control."""

    def __init__(self, title, accent=ACCENT, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setStyleSheet(
            f"#card{{background:{CARD}; border:1px solid {BORDER}; border-radius:14px;}}")
        self.v = QVBoxLayout(self)
        self.v.setContentsMargins(16, 14, 16, 14)
        self.v.setSpacing(11)
        head = QLabel(title)
        head.setStyleSheet(
            f"color:{accent}; font-size:11px; font-weight:800; letter-spacing:1.3px;")
        self.v.addWidget(head)

    def row(self, label, control, fill=True):
        r = QHBoxLayout()
        lb = QLabel(label)
        lb.setStyleSheet(f"color:{TEXT}; font-size:12px;")
        lb.setMinimumWidth(150)
        r.addWidget(lb)
        if fill:
            # combo giãn lấp phần còn lại -> không bị đẩy tràn mép phải
            control.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            r.addWidget(control, 1)
        else:
            # công tắc/điều khiển cố định -> canh phải
            r.addStretch(1)
            r.addWidget(control)
        self.v.addLayout(r)
        return control

    def add(self, w):
        self.v.addWidget(w)
        return w


_QSS = f"""
#root {{ background:{BG}; border-radius:20px; border:1px solid {BORDER}; }}
QWidget {{ color:{TEXT}; font-family:'Segoe UI'; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background:transparent; border:none; }}
QScrollBar:vertical {{ background:transparent; width:8px; margin:2px; }}
QScrollBar::handle:vertical {{ background:rgba(255,255,255,0.14); border-radius:4px; min-height:30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height:0; }}
#appname {{ font-size:16px; font-weight:700; }}
#ver {{ color:{MUTED}; font-size:11px; }}
#close {{ background:transparent; border:none; color:{MUTED}; font-size:18px; padding:0 6px; border-radius:8px; }}
#close:hover {{ background:{CARD_Hi}; color:{TEXT}; }}
QComboBox {{ background:{CARD_Hi}; border:1px solid {BORDER}; border-radius:9px; padding:6px 10px; color:{TEXT}; font-size:12px; min-width:150px; max-width:190px; }}
QComboBox::drop-down {{ border:none; width:20px; }}
QComboBox QAbstractItemView {{ background:{CARD}; color:{TEXT}; border:1px solid {BORDER}; selection-background-color:{ACCENT}; outline:none; }}
QPushButton.seg {{ background:{CARD_Hi}; border:1px solid {BORDER}; color:{MUTED}; padding:6px 14px; border-radius:9px; font-size:12px; }}
QPushButton.seg:checked {{ background:{ACCENT}; color:white; border:1px solid {ACCENT}; }}
QPushButton.act {{ background:{CARD_Hi}; border:1px solid {BORDER}; color:{TEXT}; padding:9px 12px; border-radius:10px; font-size:12px; text-align:left; }}
QPushButton.act:hover {{ background:#30333E; }}
QPushButton#hero {{ background:{ACCENT}; border:none; border-radius:12px; color:white; font-size:14px; font-weight:600; padding:12px; }}
QPushButton#hero[live="true"] {{ background:{LIVE}; }}
QPushButton#danger {{ background:transparent; border:1px solid {BORDER}; color:#FF8A8A; padding:9px 12px; border-radius:10px; font-size:12px; }}
QPushButton#danger:hover {{ background:rgba(255,90,90,0.12); }}
#status {{ color:{MUTED}; font-size:11px; }}
"""


class ControlCenter(QWidget):
    """Cửa sổ điều khiển tổng. pill = Pill (main window) để tái dùng method + state."""

    def __init__(self, pill):
        super().__init__()
        self.pill = pill
        self.engine = pill.engine
        self.te = pill.translate_engine
        self._drag = None

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowTitle("WakerVoice — Bảng điều khiển")
        self.setFixedWidth(468)
        self.setStyleSheet(_QSS)
        self._build()

        self._pulse = QTimer(self)
        self._pulse.timeout.connect(self._tick)
        self._pulse_on = False

    # ----------------------- Dựng -----------------------
    def _build(self):
        from version import __version__
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        root = QWidget(objectName="root")
        outer.addWidget(root)
        rv = QVBoxLayout(root)
        rv.setContentsMargins(0, 0, 0, 0)

        # Header
        head = QHBoxLayout()
        head.setContentsMargins(22, 16, 16, 8)
        name = QLabel("WakerVoice", objectName="appname")
        ver = QLabel(f"v{__version__}", objectName="ver")
        close = QPushButton("✕", objectName="close")
        close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(self.hide)
        head.addWidget(name)
        head.addSpacing(8)
        head.addWidget(ver)
        head.addStretch(1)
        head.addWidget(close)
        rv.addLayout(head)

        # Scroll body
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        b = QVBoxLayout(body)
        b.setContentsMargins(18, 4, 18, 18)
        b.setSpacing(14)
        scroll.setWidget(body)
        rv.addWidget(scroll)
        self.setMaximumHeight(760)

        b.addWidget(self._card_translate())
        b.addWidget(self._card_voice())
        b.addWidget(self._card_system())

    # ---- Card Dịch nhanh ----
    def _card_translate(self):
        c = Card("DỊCH NHANH (REALTIME)", accent=SYS_CLR)
        self.tr_hero = QPushButton(objectName="hero")
        self.tr_hero.setCursor(Qt.PointingHandCursor)
        self.tr_hero.clicked.connect(lambda: (self.pill._panel_toggle(), self._refresh()))
        c.add(self.tr_hero)
        self.tr_status = QLabel("", objectName="status")
        self.tr_status.setWordWrap(True)
        c.add(self.tr_status)

        # mode segmented
        seg = QHBoxLayout()
        self.mode_grp = QButtonGroup(self)
        self.m_batch = self._seg("Groq ~1s")
        self.m_stream = self._seg("Deepgram ~0.3s")
        self.mode_grp.addButton(self.m_batch)
        self.mode_grp.addButton(self.m_stream)
        self.m_batch.clicked.connect(lambda: (self.te.set_stt_mode("batch"), self._refresh()))
        self.m_stream.clicked.connect(lambda: (self.te.set_stt_mode("streaming"), self._refresh()))
        seg.addWidget(self.m_batch)
        seg.addWidget(self.m_stream)
        seg.addStretch(1)
        c.v.addLayout(seg)

        self.tr_audio = _combo([("system", "Chỉ hệ thống"), ("both", "Mic + Hệ thống"),
                                ("mic", "Chỉ mic")], self.te.audio_source)
        self.tr_audio.currentIndexChanged.connect(
            lambda: self.te.set_audio_source(self.tr_audio.currentData()))
        c.row("Nguồn nghe", self.tr_audio)
        self.tr_src = _combo(SOURCE_LANGS, self.te.source_lang)
        self.tr_src.currentIndexChanged.connect(
            lambda: self.te.set_source_lang(self.tr_src.currentData()))
        c.row("Ngôn ngữ nghe", self.tr_src)
        self.tr_tgt = _combo(TARGET_LANGS, self.te.target_lang)
        self.tr_tgt.currentIndexChanged.connect(
            lambda: self.te.set_target_lang(self.tr_tgt.currentData()))
        c.row("Dịch sang", self.tr_tgt)

        full = QPushButton("Mở bảng đầy đủ (nhập key Deepgram/Google)…")
        full.setProperty("class", "act")
        full.setCursor(Qt.PointingHandCursor)
        full.clicked.connect(self.pill._open_translate_panel)
        c.add(full)
        return c

    # ---- Card Gõ bằng giọng ----
    def _card_voice(self):
        import engine as eng_mod
        c = Card("GÕ BẰNG GIỌNG (PUSH-TO-TALK)", accent=MIC_CLR)
        hk = eng_mod.HOTKEY_LABELS.get(self.engine.hotkey_name, self.engine.hotkey_name)
        talk = QPushButton(f"Bật/tắt nói  ·  phím {hk}")
        talk.setProperty("class", "act")
        talk.setCursor(Qt.PointingHandCursor)
        talk.clicked.connect(self.engine.toggle)
        c.add(talk)

        # Ngôn ngữ nhận dạng — nhãn 1 dòng, 3 nút segmented ở dòng dưới (đủ chỗ)
        lb = QLabel("Ngôn ngữ nhận dạng")
        lb.setStyleSheet(f"color:{TEXT}; font-size:12px;")
        c.v.addWidget(lb)
        seg = QHBoxLayout()
        seg.setSpacing(8)
        self.v_lang_grp = QButtonGroup(self)
        self._v_lang_btns = {}
        for code, label in STT_LANGS:
            btn = self._seg(label)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            self.v_lang_grp.addButton(btn)
            btn.clicked.connect(lambda _=False, cc=code: (self.pill._set_language(cc), self._refresh()))
            self._v_lang_btns[code] = btn
            seg.addWidget(btn)
        c.v.addLayout(seg)

        # Model + provider
        self.v_model = _combo([(m, self._short(m)) for m in self.engine.provider.get("models", [])],
                              self.engine.model)
        self.v_model.currentIndexChanged.connect(
            lambda: self.pill._set_model(self.v_model.currentData()))
        c.row("Chất lượng nhận dạng", self.v_model)

        provs = [(pid, p["display_name"]) for pid, p in stt_providers.all_providers().items()]
        self.v_prov = _combo(provs, self.engine.provider_id)
        self.v_prov.currentIndexChanged.connect(self._on_provider)
        c.row("Nhà cung cấp STT", self.v_prov)

        # Dọn chính tả switch
        self.v_refine = Switch(self.engine.refine, on_toggle=self._set_refine)
        c.row("Dọn chính tả bằng AI (+0.5s)", self.v_refine, fill=False)

        key = QPushButton("Đổi/nhập Groq API key…")
        key.setProperty("class", "act")
        key.setCursor(Qt.PointingHandCursor)
        key.clicked.connect(self.pill._enter_groq_key)
        c.add(key)
        return c

    # ---- Card Hệ thống ----
    def _card_system(self):
        c = Card("HỆ THỐNG", accent=MUTED)
        self.sys_startup = Switch(install.startup_enabled(), on_toggle=self._set_startup)
        c.row("Khởi động cùng Windows", self.sys_startup, fill=False)
        for text, fn in (
            ("Tạo lối tắt (Start Menu + Desktop)", self._make_shortcuts),
            ("Kiểm tra cập nhật", self.pill._manual_check),
            ("Snippets · text-expansion…", self.pill._open_snippets_editor),
            ("Cài đặt nâng cao…", self.pill._open_settings),
        ):
            btn = QPushButton(text)
            btn.setProperty("class", "act")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(fn)
            c.add(btn)
        quit_btn = QPushButton("Thoát WakerVoice")
        quit_btn.setObjectName("danger")
        quit_btn.setCursor(Qt.PointingHandCursor)
        quit_btn.clicked.connect(self.pill._quit)
        c.add(quit_btn)
        return c

    # ----------------------- Helpers -----------------------
    def _seg(self, text):
        b = QPushButton(text)
        b.setProperty("class", "seg")
        b.setCheckable(True)
        b.setCursor(Qt.PointingHandCursor)
        return b

    @staticmethod
    def _short(m):
        return m.replace("whisper-", "").replace("gpt-4o-", "gpt-").replace("-v3", "")

    def _on_provider(self):
        pid = self.v_prov.currentData()
        self.pill._set_provider(pid)
        # provider đổi -> model list đổi -> nạp lại combo model
        self.v_model.blockSignals(True)
        self.v_model.clear()
        for m in self.engine.provider.get("models", []):
            self.v_model.addItem(self._short(m), m)
        for i in range(self.v_model.count()):
            if self.v_model.itemData(i) == self.engine.model:
                self.v_model.setCurrentIndex(i)
                break
        self.v_model.blockSignals(False)

    def _set_refine(self, on):
        self.engine.set_refine(on)
        self.pill._notify("Bật dọn chính tả AI." if on else "Tắt dọn chính tả AI.", 1800)

    def _set_startup(self, on):
        try:
            install.set_startup(on)
        except Exception as e:
            self.pill._notify(f"Lỗi startup: {e}", 3000)

    def _make_shortcuts(self):
        try:
            install.create_shortcuts()
            self.pill._notify("Đã tạo lối tắt.", 2000)
        except Exception as e:
            self.pill._notify(f"Lỗi tạo lối tắt: {e}", 3000)

    # ----------------------- Trạng thái -----------------------
    def _refresh(self):
        on = self.te.is_running()
        streaming = getattr(self.te, "stt_mode", "batch") == "streaming"
        self.tr_hero.setText("● Đang nghe — bấm để tắt" if on else "Bật dịch nhanh")
        self.tr_hero.setProperty("live", "true" if on else "false")
        self.tr_hero.style().unpolish(self.tr_hero)
        self.tr_hero.style().polish(self.tr_hero)
        self.tr_status.setText(
            f"{'Đang nghe' if on else 'Đang tắt'} · "
            f"{'Deepgram ~0.3s (chữ chảy)' if streaming else 'Groq ~1–1.5s'}")
        (self.m_stream if streaming else self.m_batch).setChecked(True)
        for code, btn in getattr(self, "_v_lang_btns", {}).items():
            btn.setChecked(code == self.engine.language)
        if on:
            self._pulse.start(650)
        else:
            self._pulse.stop()

    def _tick(self):
        self._pulse_on = not self._pulse_on

    def show_center(self):
        self._refresh()
        if not self.isVisible():
            self.adjustSize()
            g = QGuiApplication.primaryScreen().availableGeometry()
            self.move(g.center().x() - self.width() // 2,
                      max(20, g.center().y() - self.height() // 2))
        self.show()
        self.raise_()
        self.activateWindow()

    # kéo header để di chuyển
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and e.position().y() < 52:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):
        self._drag = None
