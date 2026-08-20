"""
WakerVoice — Caption Overlay (Translate Mode)
==============================================
Thanh phụ đề nằm đáy màn hình, hiện text gốc + text dịch theo thời gian thực.
Ẩn hoàn toàn khi translate mode tắt. Style giống Pill (frameless, translucent,
always-on-top, click-through khi không hover).
"""

import time

from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import QPainter, QColor, QPainterPath, QFont, QGuiApplication
from PySide6.QtWidgets import QWidget

MAX_LINES = 4                  # số dòng hiện tối đa
LINE_TTL_S = 8.0                # mỗi dòng tự ẩn sau 8s không có dòng mới
OVERLAY_W = 900
LINE_H = 58
PAD_V = 14
MARGIN_BOTTOM = 90              # cách đáy màn hình (chừa chỗ cho Pill)

SOURCE_LABELS = {"mic": "Bạn", "system": "Hệ thống"}


class CaptionOverlay(QWidget):
    """Overlay hiển thị caption realtime. show_line() thêm dòng mới, tự cuộn/ẩn."""

    def __init__(self):
        super().__init__()
        self._lines = []           # list of dict {source, original, translated, ts}

        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setWindowTitle("WakerVoice — Dịch nhanh")

        self._font_orig = QFont("Segoe UI", 10)
        self._font_trans = QFont("Segoe UI", 14, QFont.Weight.DemiBold)
        self._font_label = QFont("Segoe UI", 9, QFont.Weight.Bold)

        self._resize_to_content()
        self._place()

        # Timer dọn dòng cũ (mỗi 500ms)
        self._gc_timer = QTimer(self)
        self._gc_timer.timeout.connect(self._gc_old_lines)
        self._gc_timer.start(500)

        self.hide()     # ẩn mặc định — chỉ hiện khi translate mode bật

    # ---------------- API công khai ----------------
    def add_result(self, source, original, translated, final_stream=False):
        """Thêm/chốt 1 dòng caption (source='mic'|'system').

        final_stream=True (streaming): CHỐT dòng đang chảy của nguồn này — thay
        chữ + đánh dấu final, thay vì thêm dòng mới. Batch (=False): luôn thêm dòng.
        """
        self._drop_placeholder()
        line = self._streaming_line(source) if final_stream else None
        if line is not None:
            line["original"] = (original or "").strip()
            line["translated"] = (translated or "").strip()
            line["final"] = True
            line["ts"] = time.monotonic()
        else:
            self._lines.append({
                "source": source,
                "original": (original or "").strip(),
                "translated": (translated or "").strip(),
                "final": True,
                "ts": time.monotonic(),
            })
        self._trim_show()

    def stream_interim(self, source, original):
        """Cập nhật bản GỐC đang chảy realtime (chưa dịch) của một nguồn.

        Nếu dòng cuối là dòng streaming CHƯA chốt của cùng nguồn -> cập nhật tại chỗ
        (chữ chảy dần). Nếu không -> mở dòng streaming mới."""
        self._drop_placeholder()
        line = self._streaming_line(source)
        text = (original or "").strip()
        if not text:
            return
        if line is not None:
            line["original"] = text
            line["ts"] = time.monotonic()
        else:
            self._lines.append({
                "source": source,
                "original": text,
                "translated": "",
                "final": False,
                "ts": time.monotonic(),
            })
        self._trim_show()

    def _streaming_line(self, source):
        """Dòng streaming CHƯA chốt gần nhất của nguồn (để cập nhật/chốt). None nếu không có."""
        if self._lines:
            last = self._lines[-1]
            if last.get("source") == source and not last.get("final", True):
                return last
        return None

    def _trim_show(self):
        if len(self._lines) > MAX_LINES:
            self._lines = self._lines[-MAX_LINES:]
        self._resize_to_content()
        self._place()
        if not self.isVisible():
            self.show()
        self.update()

    def clear_lines(self):
        self._lines = []
        self.update()

    def show_listening(self):
        """Hiện thanh chờ khi vừa bật Dịch nhanh (chưa có tiếng) — để user BIẾT nó
        đang chạy + thấy chỗ phụ đề sẽ hiện. Tự bị thay khi có transcript thật."""
        self._lines = [{
            "source": "system", "original": "",
            "translated": "🎧  Đang nghe — phát tiếng để hiện phụ đề…",
            "final": True, "placeholder": True, "ts": time.monotonic(),
        }]
        self._trim_show()

    def _drop_placeholder(self):
        self._lines = [l for l in self._lines if not l.get("placeholder")]

    def set_active(self, on):
        """Bật/tắt overlay theo translate mode."""
        if on:
            self._place()
            self.show()
        else:
            self.clear_lines()
            self.hide()

    # ---------------- internal ----------------
    def _gc_old_lines(self):
        if not self._lines:
            return
        now = time.monotonic()
        before = len(self._lines)
        # Giữ placeholder "Đang nghe" (không hết hạn) tới khi có transcript / tắt.
        self._lines = [l for l in self._lines
                       if l.get("placeholder") or now - l["ts"] < LINE_TTL_S]
        if len(self._lines) != before:
            self._resize_to_content()
            self._place()
            self.update()
            if not self._lines:
                self.hide()

    def _resize_to_content(self):
        h = max(1, len(self._lines)) * LINE_H + PAD_V * 2
        self.setFixedSize(OVERLAY_W, h)

    def _place(self):
        g = QGuiApplication.primaryScreen().availableGeometry()
        x = g.center().x() - OVERLAY_W // 2
        y = g.bottom() - self.height() - MARGIN_BOTTOM
        self.move(x, y)

    # ---------------- vẽ ----------------
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        w, h = self.width(), self.height()
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, w, h), 16, 16)
        p.fillPath(path, QColor(18, 18, 22, 195))

        n = len(self._lines)
        for i, line in enumerate(self._lines):
            y0 = PAD_V + i * LINE_H
            self._draw_line(p, line, y0, w)
        p.end()

    def _draw_line(self, p, line, y0, w):
        label = SOURCE_LABELS.get(line["source"], line["source"])
        pad_l = 20

        p.setFont(self._font_label)
        p.setPen(QColor(130, 170, 255) if line["source"] == "mic"
                 else QColor(255, 170, 110))
        p.drawText(QRectF(pad_l, y0, 90, 20), Qt.AlignLeft | Qt.AlignVCenter,
                  f"{label}")

        # Text gốc (nhỏ, mờ) — chỉ hiện khi ĐÃ có bản dịch và khác nhau. Lúc đang
        # chảy (interim, chưa dịch) thì bản gốc hiện ở dòng lớn bên dưới, khỏi lặp.
        orig = line["original"]
        trans = line["translated"]
        if orig and trans and orig != trans:
            p.setFont(self._font_orig)
            p.setPen(QColor(190, 190, 200, 190))
            p.drawText(QRectF(pad_l + 95, y0, w - pad_l - 115, 20),
                      Qt.AlignLeft | Qt.AlignVCenter, self._elide(orig, 70))

        # Text dịch (to, rõ)
        p.setFont(self._font_trans)
        p.setPen(QColor(255, 255, 255))
        p.drawText(QRectF(pad_l, y0 + 22, w - pad_l * 2, 32),
                  Qt.AlignLeft | Qt.AlignVCenter, self._elide(trans or orig, 90))

    @staticmethod
    def _elide(text, max_chars):
        if len(text) <= max_chars:
            return text
        return text[:max_chars - 1] + "…"
