"""
WakerVoice — Settings dialog & Snippets editor (PySide6)
========================================================
Mục tiêu: Gom tất cả cấu hình ra 1 chỗ. Tách bạch khỏi engine + main UI để:
  - dễ test từng phần
  - không phình `app_qt.py`
  - reusable cho bản portable (gọi dialog mà không cần build pill UI đầy đủ).

Hai dialog:
  - SnippetsDialog: chỉnh trigger prefix + danh sách snippet (key/label/replacement)
  - SettingsDialog: tab Ngôn ngữ / API / Phím tắt / Snippets (link tới SnippetsDialog)
                     / Lịch sử (nút mở file / xoá).

Tất cả dialog NUỐT lỗi -> app không bao giờ chết vì UI setting.
"""

import os
import json
import threading
import time
import logging

from PySide6.QtCore import Qt, QUrl, QTimer
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QTabWidget, QWidget,
    QLabel, QLineEdit, QComboBox, QCheckBox, QPushButton, QListWidget,
    QListWidgetItem, QTextEdit, QDialogButtonBox, QGroupBox, QMessageBox,
    QSpinBox, QPlainTextEdit, QFileDialog, QInputDialog, QAbstractItemView,
)

import config
import snippets as snip_mod
import history as hist_mod
import providers as stt_providers
import google_translate

# Ngôn ngữ hỗ trợ cho tab Dịch nhanh (mã ISO -> nhãn hiển thị)
TRANSLATE_LANGS = [
    ("en", "English"), ("vi", "Tiếng Việt"), ("ja", "日本語"),
    ("ko", "한국어"), ("zh-CN", "中文"), ("fr", "Français"),
    ("es", "Español"), ("de", "Deutsch"), ("ru", "Русский"),
    ("th", "ไทย"), ("id", "Bahasa Indonesia"),
]
TRANSLATE_SOURCE_LANGS = [("auto", "Tự động nhận diện")] + TRANSLATE_LANGS


# ---------- helpers ----------
def _label_provider_name(pid):
    p = stt_providers.get_provider(pid)
    return p["display_name"] if p else pid


# ============================================================================
# SnippetsDialog — chỉnh snippets
# ============================================================================
class SnippetsDialog(QDialog):
    """Editor cho snippets: trigger prefix + list {key, label, replacement}."""

    def __init__(self, parent=None, engine=None):
        super().__init__(parent)
        self.setWindowTitle("Snippets · text-expansion")
        self.setMinimumSize(620, 460)
        self.engine = engine

        # Load ban đầu
        self._data = snip_mod.load()  # {"trigger_prefix": str, "items": [...]}

        root = QVBoxLayout(self)

        # Prefix
        prefix_row = QHBoxLayout()
        prefix_row.addWidget(QLabel("Trigger prefix:"))
        self.prefix_edit = QLineEdit(self._data.get("trigger_prefix") or "@@")
        self.prefix_edit.setMaximumWidth(80)
        prefix_row.addWidget(self.prefix_edit)
        prefix_row.addWidget(QLabel(
            '  Ví dụ: với prefix "@@" và key "date", '
            'nói "hôm nay là @@date" → "hôm nay là 23/07/2026".',
        ))
        prefix_row.addStretch(1)
        root.addLayout(prefix_row)

        # Placeholder gợi ý
        hint = QLabel(
            'Placeholder trong replacement:\n'
            '  {{date}} — dd/MM/yyyy   ·   {{time}} — HH:MM   ·   {{datetime}} — cả hai\n'
            '  {{weekday}} — Thứ + tên   ·   {{clipboard}} — nội dung clipboard hiện tại'
        )
        hint.setStyleSheet("color: #888;")
        root.addWidget(hint)

        # List snippets (QTableWidget cho gọn)
        from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView
        self.table = QTableWidget(0, 3, self)
        self.table.setHorizontalHeaderLabels(["Key", "Mô tả", "Replacement"])
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked
                                   | QAbstractItemView.EditTrigger.EditKeyPressed)
        root.addWidget(self.table, 1)

        self._reload_table()

        # Nút thêm / xoá / reset
        btn_row = QHBoxLayout()
        add_btn = QPushButton("Thêm snippet")
        add_btn.clicked.connect(self._add_row)
        del_btn = QPushButton("Xoá dòng chọn")
        del_btn.clicked.connect(self._del_row)
        reset_btn = QPushButton("Khôi phục mặc định")
        reset_btn.clicked.connect(self._reset_defaults)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(del_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(reset_btn)
        root.addLayout(btn_row)

        # OK / Cancel
        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self._save_and_accept)
        box.rejected.connect(self.reject)
        root.addWidget(box)

    def _reload_table(self):
        from PySide6.QtWidgets import QTableWidgetItem
        self.table.setRowCount(0)
        for it in self._data.get("items") or []:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(it.get("key") or ""))
            self.table.setItem(r, 1, QTableWidgetItem(it.get("label") or ""))
            self.table.setItem(r, 2, QTableWidgetItem(it.get("replacement") or ""))

    def _add_row(self):
        from PySide6.QtWidgets import QTableWidgetItem
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem("newkey"))
        self.table.setItem(r, 1, QTableWidgetItem("Mô tả"))
        self.table.setItem(r, 2, QTableWidgetItem("văn bản thay thế"))
        self.table.editItem(self.table.item(r, 0))

    def _del_row(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.table.removeRow(r)

    def _reset_defaults(self):
        self._data = snip_mod.reset_defaults()
        self.prefix_edit.setText(self._data["trigger_prefix"])
        self._reload_table()

    def _save_and_accept(self):
        items = []
        for r in range(self.table.rowCount()):
            k_item = self.table.item(r, 0)
            l_item = self.table.item(r, 1)
            v_item = self.table.item(r, 2)
            k = (k_item.text() if k_item else "").strip()
            if not k:
                continue
            items.append({
                "key": k,
                "label": (l_item.text() if l_item else k),
                "replacement": (v_item.text() if v_item else ""),
            })
        prefix = self.prefix_edit.text().strip() or "@@"
        self._data = {"trigger_prefix": prefix, "items": items}
        snip_mod.save(self._data)
        self.accept()


# ============================================================================
# SettingsDialog — cài đặt tổng hợp
# ============================================================================

# Số test request đang chạy đồng thời — chống user bấm 5 lần liên tiếp sinh
# 5 thread race nhau. Lưu vào instance của SettingsDialog.
_TEST_INFLIGHT = {}


def _run_test_in_thread(self, label_widget, label_text, runner, on_done):
    """Chạy `runner()` trong thread daemon; khi xong setText `label_widget`
    bằng `on_done(ok, msg)` trên UI thread. Chống trùng lặp + log đầy đủ.

    runner() -> (ok: bool, msg: str). Nên có timeout nội tại (vd 6s).
    """
    # Chống bấm liên tiếp: nếu đang chạy, hiện "đang chạy" và bỏ qua
    if _TEST_INFLIGHT.get(id(self)):
        try:
            label_widget.setText(
                f"<span style='color:#888'>…đợi test trước xong ({label_text})</span>"
            )
        except (RuntimeError, AttributeError):
            pass
        return
    _TEST_INFLIGHT[id(self)] = True
    try:
        label_widget.setText(f"<span style='color:#888'>⏳ {label_text}…</span>")
    except (RuntimeError, AttributeError):
        pass
    log = logging.getLogger("wakervoice.test")

    def work():
        t0 = time.monotonic()
        log.info("[test:%s] start", label_text)
        try:
            ok, msg = runner()
        except Exception as e:
            ok, msg = False, f"{type(e).__name__}: {e}"
            log.exception("[test:%s] raised", label_text)
        dt = (time.monotonic() - t0) * 1000
        log.info("[test:%s] done in %.0fms ok=%s msg=%r",
                 label_text, dt, ok, (msg or "")[:120])
        html = on_done(ok, msg)

        def _apply():
            try:
                # Đánh dấu xong TRƯỚC khi setText, để lần bấm tiếp theo không bị block
                _TEST_INFLIGHT[id(self)] = False
                if html is not None and label_widget is not None:
                    label_widget.setText(html)
            except (RuntimeError, AttributeError):
                pass

        QTimer.singleShot(0, _apply)

    threading.Thread(target=work, daemon=True, name=f"test-{label_text[:8]}").start()


class SettingsDialog(QDialog):
    """Tab tổng hợp: Ngôn ngữ / API / Phím tắt / Snippets / Lịch sử."""

    def __init__(self, parent=None, engine=None, translate_engine=None):
        super().__init__(parent)
        self.setWindowTitle("Cài đặt WakerVoice")
        self.setMinimumSize(700, 520)
        self.engine = engine
        self.translate_engine = translate_engine
        self._cfg = config.load()  # snapshot

        root = QVBoxLayout(self)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)

        self._build_tab_language()
        self._build_tab_api()
        self._build_tab_hotkey()
        self._build_tab_translate()
        self._build_tab_snippets()
        self._build_tab_history()

        # OK / Cancel / Apply
        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self._on_ok)
        box.rejected.connect(self.reject)
        root.addWidget(box)

    # --------------- Tab Ngôn ngữ ---------------
    def _build_tab_language(self):
        w = QWidget()
        layout = QFormLayout(w)
        layout.addRow(QLabel(
            "<b>Ngôn ngữ nhận dạng</b> · 'Tự động' cho phép Whisper nhận cả "
            "tiếng Việt + tiếng Anh trong cùng câu."
        ))
        self.lang_combo = QComboBox()
        self.lang_combo.addItem("Tự động · mọi ngôn ngữ", "auto")
        self.lang_combo.addItem("Tiếng Việt (khoá cứng)", "vi")
        self.lang_combo.addItem("English (khoá cứng)", "en")
        cur = self._cfg.get("language") or self.engine.language or "auto"
        for i in range(self.lang_combo.count()):
            if self.lang_combo.itemData(i) == cur:
                self.lang_combo.setCurrentIndex(i)
                break
        layout.addRow("Ngôn ngữ:", self.lang_combo)

        # Prompt gợi ý từ vựng
        layout.addRow(QLabel(
            "<b>Prompt gợi ý</b> · Câu mẫu ngắn (1-2 câu) cho Whisper bám "
            "vào giọng/code-switch. KHÔNG để meta/hướng dẫn."
        ))
        self.prompt_edit = QPlainTextEdit()
        self.prompt_edit.setPlaceholderText(
            "Ví dụ: 'Chiều nay có meeting review pull request, mình fix bug rồi deploy.'"
        )
        self.prompt_edit.setPlainText(self._cfg.get("groq_prompt") or "")
        self.prompt_edit.setMaximumHeight(80)
        layout.addRow(self.prompt_edit)

        self.tabs.addTab(w, "Ngôn ngữ")

    # --------------- Tab API ---------------
    def _build_tab_api(self):
        w = QWidget()
        layout = QFormLayout(w)
        layout.addRow(QLabel("<b>Provider STT</b>"))

        # Chọn provider
        self.provider_combo = QComboBox()
        for pid, p in stt_providers.all_providers().items():
            self.provider_combo.addItem(p["display_name"], pid)
        cur_pid = self.engine.provider_id
        for i in range(self.provider_combo.count()):
            if self.provider_combo.itemData(i) == cur_pid:
                self.provider_combo.setCurrentIndex(i)
                break
        self.provider_combo.currentIndexChanged.connect(self._refresh_api_tab)
        layout.addRow("Nhà cung cấp:", self.provider_combo)

        # API key
        self.api_edit = QLineEdit()
        self.api_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_edit.setPlaceholderText("Dán API key…")
        self.api_edit.setText(self.engine.api_key or "")
        layout.addRow("API key:", self.api_edit)

        show_btn = QPushButton("Hiện")
        show_btn.setCheckable(True)
        show_btn.toggled.connect(
            lambda v: self.api_edit.setEchoMode(
                QLineEdit.EchoMode.Normal if v else QLineEdit.EchoMode.Password
            )
        )
        layout.addRow("", show_btn)

        # Model STT
        self.model_combo = QComboBox()
        for m in self.engine.provider.get("models") or []:
            self.model_combo.addItem(m, m)
        cur_model = self.engine.model
        for i in range(self.model_combo.count()):
            if self.model_combo.itemData(i) == cur_model:
                self.model_combo.setCurrentIndex(i)
                break
        layout.addRow("Model STT:", self.model_combo)

        # Test connection
        test_btn = QPushButton("Test kết nối")
        test_btn.clicked.connect(self._test_provider_connection)
        layout.addRow("", test_btn)
        self.test_result = QLabel("")
        self.test_result.setStyleSheet("color: #888;")
        layout.addRow("", self.test_result)

        # Refine
        self.refine_chk = QCheckBox("Dọn dấu/chính tả tiếng Việt bằng LLM (+~0.5s)")
        self.refine_chk.setChecked(bool(self._cfg.get("refine", True)))
        layout.addRow(self.refine_chk)

        self.refine_model_combo = QComboBox()
        for m in self.engine.provider.get("refine_models") or []:
            self.refine_model_combo.addItem(m, m)
        cur_rm = self._cfg.get("refine_model") or self.engine.refine_model
        for i in range(self.refine_model_combo.count()):
            if self.refine_model_combo.itemData(i) == cur_rm:
                self.refine_model_combo.setCurrentIndex(i)
                break
        layout.addRow("Model refine:", self.refine_model_combo)

        # Endpoint tùy chỉnh (OpenAI-compatible)
        layout.addRow(QLabel("<hr>"))
        layout.addRow(QLabel(
            "<b>Endpoint tùy chỉnh</b> · Thêm URL OpenAI-compatible "
            "(self-hosted, Together, Fireworks, proxy nội bộ)."
        ))

        self.custom_list = QListWidget()
        for c in self._cfg.get("custom_providers") or []:
            if isinstance(c, dict):
                self.custom_list.addItem(
                    f"{c.get('display_name') or c.get('id') or '?'}  ·  "
                    f"{c.get('base_url') or ''}"
                )
        layout.addRow(self.custom_list)

        cb = QHBoxLayout()
        add_btn = QPushButton("Thêm…")
        add_btn.clicked.connect(self._add_custom_provider)
        del_btn = QPushButton("Xoá chọn")
        del_btn.clicked.connect(self._del_custom_provider)
        cb.addWidget(add_btn)
        cb.addWidget(del_btn)
        cb.addStretch(1)
        layout.addRow(cb)

        self.tabs.addTab(w, "API & Nhà cung cấp")

    def _refresh_api_tab(self):
        pid = self.provider_combo.currentData()
        if not pid or pid == self.engine.provider_id:
            return
        # Tạm thời set provider để cập nhật model combo (chưa save)
        new = stt_providers.get_provider(pid)
        self.model_combo.clear()
        for m in new.get("models") or []:
            self.model_combo.addItem(m, m)
        self.refine_model_combo.clear()
        for m in new.get("refine_models") or []:
            self.refine_model_combo.addItem(m, m)
        # Reset api_edit theo key đã lưu cho provider mới
        from providers import get_api_key
        self.api_edit.setText(get_api_key(pid) or "")

    def _test_provider_connection(self):
        pid = self.provider_combo.currentData()
        if not pid:
            return
        provider = stt_providers.get_provider(pid)
        api_key = self.api_edit.text().strip()
        if not api_key:
            self.test_result.setText("⚠ Chưa có API key.")
            return

        def runner():
            return stt_providers.test_connection(provider, api_key, timeout=6)

        def on_done(ok, msg):
            color = "#2e7" if ok else "#d44"
            mark = "✓" if ok else "✗"
            return f"<span style='color:{color}'>{mark} {msg}</span>"

        _run_test_in_thread(
            self,
            label_widget=self.test_result,
            label_text=f"STT {_label_provider_name(pid)}",
            runner=runner,
            on_done=on_done,
        )

    def _add_custom_provider(self):
        from PySide6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getText(
            self, "Endpoint tùy chỉnh",
            "Nhập JSON cho custom provider, ví dụ:\n"
            '  {"id":"my","display_name":"My Server","base_url":"https://api.example.com/v1",'
            '"model":"whisper-1","chat_model":"gpt-4o-mini","api_key":"..."}',
        )
        if not ok or not text.strip():
            return
        try:
            data = json.loads(text)
            if not isinstance(data, dict) or not data.get("base_url"):
                raise ValueError("thiếu base_url")
        except Exception as e:
            QMessageBox.warning(self, "Lỗi", f"JSON không hợp lệ:\n{e}")
            return
        customs = list(self._cfg.get("custom_providers") or [])
        # Thay thế nếu cùng id
        customs = [c for c in customs
                   if not (isinstance(c, dict) and c.get("id") == data.get("id"))]
        customs.append(data)
        self._cfg["custom_providers"] = customs
        config.save(self._cfg)
        self.custom_list.clear()
        for c in customs:
            if isinstance(c, dict):
                self.custom_list.addItem(
                    f"{c.get('display_name') or c.get('id') or '?'}  ·  "
                    f"{c.get('base_url') or ''}"
                )
        # Refresh provider combo (thêm custom mới)
        self.provider_combo.addItem(
            data.get("display_name") or data.get("id"),
            data.get("id"),
        )

    def _del_custom_provider(self):
        row = self.custom_list.currentRow()
        if row < 0:
            return
        customs = list(self._cfg.get("custom_providers") or [])
        if row >= len(customs):
            return
        removed = customs.pop(row)
        self._cfg["custom_providers"] = customs
        config.save(self._cfg)
        self.custom_list.takeItem(row)
        if isinstance(removed, dict) and removed.get("id"):
            # Xoá khỏi provider_combo
            for i in range(self.provider_combo.count()):
                if self.provider_combo.itemData(i) == removed["id"]:
                    self.provider_combo.removeItem(i)
                    break

    # --------------- Tab Phím tắt ---------------
    def _build_tab_hotkey(self):
        w = QWidget()
        layout = QFormLayout(w)
        layout.addRow(QLabel(
            "<b>Phím bật/tắt thu âm</b> · Giữ phím để nói, nhả để chép."
        ))
        # ComboBox liệt kê HOTKEYS
        from engine import HOTKEY_LABELS
        self.hotkey_combo = QComboBox()
        for name, label in HOTKEY_LABELS.items():
            self.hotkey_combo.addItem(label, name)
        cur_hk = self.engine.hotkey_name
        for i in range(self.hotkey_combo.count()):
            if self.hotkey_combo.itemData(i) == cur_hk:
                self.hotkey_combo.setCurrentIndex(i)
                break
        layout.addRow("Phím tắt:", self.hotkey_combo)

        # Output mode
        self.output_combo = QComboBox()
        self.output_combo.addItem("Gõ tại con trỏ", "type")
        self.output_combo.addItem("Copy vào clipboard", "clipboard")
        cur_om = self.engine.output_mode
        for i in range(self.output_combo.count()):
            if self.output_combo.itemData(i) == cur_om:
                self.output_combo.setCurrentIndex(i)
                break
        layout.addRow("Xuất chữ:", self.output_combo)

        self.tabs.addTab(w, "Phím tắt")

    # --------------- Tab Dịch nhanh (Realtime) ---------------
    def _build_tab_translate(self):
        w = QWidget()
        layout = QFormLayout(w)
        layout.addRow(QLabel(
            "<b>Dịch nhanh (Realtime)</b> · Nghe âm thanh hệ thống và/hoặc mic, "
            "chép chữ (dùng provider STT ở tab API) rồi dịch qua Google Cloud "
            "Translation. Bật/tắt nhanh ở menu khay."
        ))

        # Nguồn nghe: dịch game/video thường chỉ cần "Chỉ hệ thống" (bỏ mic để
        # khỏi lẫn giọng mình / tiếng phòng).
        self.gt_source_audio_combo = QComboBox()
        for code, label in (
            ("both", "Mic + Hệ thống"),
            ("system", "Chỉ hệ thống (game/video — bỏ mic)"),
            ("mic", "Chỉ mic (giọng bạn)"),
        ):
            self.gt_source_audio_combo.addItem(label, code)
        cur_audio_src = self._cfg.get("translate_audio_source") or "both"
        for i in range(self.gt_source_audio_combo.count()):
            if self.gt_source_audio_combo.itemData(i) == cur_audio_src:
                self.gt_source_audio_combo.setCurrentIndex(i)
                break
        layout.addRow("Nguồn nghe:", self.gt_source_audio_combo)

        self.gt_api_edit = QLineEdit()
        self.gt_api_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.gt_api_edit.setPlaceholderText("Dán Google Cloud Translation API key…")
        self.gt_api_edit.setText(self._cfg.get("google_translate_api_key") or "")
        layout.addRow("Google API key:", self.gt_api_edit)

        gt_show_btn = QPushButton("Hiện")
        gt_show_btn.setCheckable(True)
        gt_show_btn.toggled.connect(
            lambda v: self.gt_api_edit.setEchoMode(
                QLineEdit.EchoMode.Normal if v else QLineEdit.EchoMode.Password
            )
        )
        layout.addRow("", gt_show_btn)

        layout.addRow(QLabel(
            'Lấy free API key (500.000 ký tự/tháng, miễn phí vĩnh viễn) tại '
            '<a href="https://console.cloud.google.com/apis/library/translate.googleapis.com">'
            'Google Cloud Console</a> → bật "Cloud Translation API" → tạo API key.'
        ))

        # Ngôn ngữ nguồn / đích
        self.gt_source_combo = QComboBox()
        for code, label in TRANSLATE_SOURCE_LANGS:
            self.gt_source_combo.addItem(label, code)
        cur_src = self._cfg.get("translate_source_lang") or "auto"
        for i in range(self.gt_source_combo.count()):
            if self.gt_source_combo.itemData(i) == cur_src:
                self.gt_source_combo.setCurrentIndex(i)
                break
        layout.addRow("Ngôn ngữ nguồn:", self.gt_source_combo)

        self.gt_target_combo = QComboBox()
        for code, label in TRANSLATE_LANGS:
            self.gt_target_combo.addItem(label, code)
        cur_tgt = self._cfg.get("translate_target_lang") or "en"
        for i in range(self.gt_target_combo.count()):
            if self.gt_target_combo.itemData(i) == cur_tgt:
                self.gt_target_combo.setCurrentIndex(i)
                break
        layout.addRow("Ngôn ngữ đích:", self.gt_target_combo)

        # Test connection
        gt_test_btn = QPushButton("Test kết nối")
        gt_test_btn.clicked.connect(self._test_google_translate_connection)
        layout.addRow("", gt_test_btn)
        self.gt_test_result = QLabel("")
        self.gt_test_result.setStyleSheet("color: #888;")
        layout.addRow("", self.gt_test_result)

        self.tabs.addTab(w, "Dịch nhanh")

    def _test_google_translate_connection(self):
        api_key = self.gt_api_edit.text().strip()
        if not api_key:
            self.gt_test_result.setText("⚠ Chưa có API key.")
            return

        def runner():
            return google_translate.test_connection(api_key, timeout=6)

        def on_done(ok, msg):
            color = "#2e7" if ok else "#d44"
            mark = "✓" if ok else "✗"
            return f"<span style='color:{color}'>{mark} {msg}</span>"

        _run_test_in_thread(
            self,
            label_widget=self.gt_test_result,
            label_text="Google Translate",
            runner=runner,
            on_done=on_done,
        )

    # --------------- Tab Snippets (link) ---------------
    def _build_tab_snippets(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.addWidget(QLabel(
            "Tự thay thế cụm từ khoá (vd <code>@@date</code>) trong transcript."
        ))
        open_btn = QPushButton("Mở editor snippets…")
        open_btn.clicked.connect(self._open_snippets_dialog)
        layout.addWidget(open_btn)
        layout.addStretch(1)
        self.tabs.addTab(w, "Snippets")

    def _open_snippets_dialog(self):
        dlg = SnippetsDialog(self, self.engine)
        dlg.exec()

    # --------------- Tab Lịch sử ---------------
    def _build_tab_history(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.addWidget(QLabel(
            "Lưu các bản chép gần nhất (tối đa ~200) để gõ lại / copy nhanh."
        ))
        s = hist_mod.stats()
        info = QLabel(f"Hiện có: {s['count']} lần · {s['words']} từ")
        info.setStyleSheet("color: #888;")
        layout.addWidget(info)

        row = QHBoxLayout()
        open_btn = QPushButton("Mở file lịch sử")
        open_btn.clicked.connect(self._open_history_file)
        clr_btn = QPushButton("Xoá hết")
        clr_btn.clicked.connect(self._clear_history)
        row.addWidget(open_btn)
        row.addWidget(clr_btn)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addStretch(1)
        self.tabs.addTab(w, "Lịch sử")

    def _open_history_file(self):
        path = hist_mod.history_path()
        if not os.path.exists(path):
            QMessageBox.information(self, "Lịch sử",
                                    "Chưa có lịch sử — hãy nói vài câu trước.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _clear_history(self):
        if QMessageBox.question(
            self, "Xoá lịch sử",
            "Xoá hết lịch sử chép? Không thể khôi phục.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        hist_mod.clear()
        QMessageBox.information(self, "Lịch sử", "Đã xoá.")

    # --------------- Áp dụng ---------------
    def _on_ok(self):
        # Áp dụng vào self.engine + lưu config; main UI sẽ rebuild các menu.
        self.apply_to_engine(self.engine)
        self.accept()

    def apply_to_engine(self, engine):
        """Ghi các thay đổi từ form xuống engine + config."""
        # Ngôn ngữ
        lang = self.lang_combo.currentData() or "auto"
        engine.set_language(lang)
        # Provider + key + model
        pid = self.provider_combo.currentData()
        if pid and pid != engine.provider_id:
            engine.set_provider(pid)
        engine.set_api_key(self.api_edit.text())
        engine.set_model(self.model_combo.currentData() or engine.model)
        engine.set_refine(self.refine_chk.isChecked())
        engine.set_refine_model(self.refine_model_combo.currentData()
                                or engine.refine_model)
        # Prompt
        cfg = config.load()
        cfg["groq_prompt"] = self.prompt_edit.toPlainText().strip()
        config.save(cfg)
        # Hotkey + output mode (cần thiết nếu user đổi qua đây)
        engine.set_hotkey(self.hotkey_combo.currentData() or engine.hotkey_name)
        engine.set_output_mode(self.output_combo.currentData() or engine.output_mode)
        # Dịch nhanh (Realtime) — nếu dialog được tạo kèm translate_engine
        if self.translate_engine is not None:
            self.translate_engine.set_google_api_key(self.gt_api_edit.text())
            self.translate_engine.set_source_lang(
                self.gt_source_combo.currentData() or self.translate_engine.source_lang)
            self.translate_engine.set_target_lang(
                self.gt_target_combo.currentData() or self.translate_engine.target_lang)
            self.translate_engine.set_audio_source(
                self.gt_source_audio_combo.currentData() or self.translate_engine.audio_source)
