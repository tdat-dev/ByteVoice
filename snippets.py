"""
WakerVoice — snippets (text-expansion)
=====================================
Cho phép user đặt cụm từ khoá (trigger) để tự động thay thế trong transcript.

Ví dụ:
    @@date       -> "Hôm nay là 23/07/2026"
    @@mail       -> "[email protected]"
    @@sign       -> "Trân trọng,\\nTấn Đạt"

Cú pháp trigger: chuỗi ASCII ngắn, có thể có ký tự đặc biệt (mặc định `@@`).

Lưu ở %LOCALAPPDATA%\\WakerVoice\\snippets.json (atomic: ghi vào .tmp rồi rename).

Áp dụng: SAU khi engine ra text cuối cùng (đã refine), quét trigger xuất hiện
TRONG text -> thay bằng replacement.

Lưu ý: chỉ thay khi trigger nằm RIÊNG (có biên là khoảng trắng / đầu / cuối / dấu
câu). Tránh nuốt nhầm "abc@@def" -> "abc...def".
"""

import os
import json
import threading
import time
import re

_LOCK = threading.Lock()

# Map placeholder -> chuỗi thay thế runtime. Người dùng nhúng {{...}} trong replacement.
_RUNTIME_PATTERNS = None  # cache, build khi cần


def _runtime_patterns():
    """Trả list (regex, repl) áp dụng LÊN replacement string TRƯỚC khi gõ ra.

    Hỗ trợ:
      {{date}}        -> dd/MM/yyyy
      {{time}}        -> HH:MM
      {{datetime}}    -> dd/MM/yyyy HH:MM
      {{weekday}}     -> Thứ + tên tiếng Việt
      {{clipboard}}   -> nội dung clipboard hiện tại
    """
    global _RUNTIME_PATTERNS
    if _RUNTIME_PATTERNS is not None:
        return _RUNTIME_PATTERNS

    def repl_date(_m):
        return time.strftime("%d/%m/%Y")

    def repl_time(_m):
        return time.strftime("%H:%M")

    def repl_datetime(_m):
        return time.strftime("%d/%m/%Y %H:%M")

    _WEEKDAYS = {
        "0": "Chủ nhật", "1": "Thứ hai", "2": "Thứ ba", "3": "Thứ tư",
        "4": "Thứ năm", "5": "Thứ sáu", "6": "Thứ bảy",
    }

    def repl_weekday(_m):
        return _WEEKDAYS[time.strftime("%w")]

    def repl_clipboard(_m):
        try:
            import pyperclip
            return pyperclip.paste() or ""
        except Exception:
            return ""

    _RUNTIME_PATTERNS = [
        (re.compile(r"\{\{date\}\}"), repl_date),
        (re.compile(r"\{\{time\}\}"), repl_time),
        (re.compile(r"\{\{datetime\}\}"), repl_datetime),
        (re.compile(r"\{\{weekday\}\}"), repl_weekday),
        (re.compile(r"\{\{clipboard\}\}"), repl_clipboard),
    ]
    return _RUNTIME_PATTERNS


def snippets_path():
    base = os.environ.get("LOCALAPPDATA") or os.path.join(
        os.path.expanduser("~"), ".config"
    )
    d = os.path.join(base, "WakerVoice")
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    return os.path.join(d, "snippets.json")


_DEFAULTS = {
    "trigger_prefix": "@@",
    # Mặc định VÍ DỤ — user tự sửa trong Settings. Không ép dùng.
    "items": [
        {
            "key": "date",
            "label": "Ngày hôm nay",
            "replacement": "Hôm nay là {{date}}",
        },
        {
            "key": "time",
            "label": "Giờ hiện tại",
            "replacement": "Bây giờ là {{time}}",
        },
        {
            "key": "sign",
            "label": "Chữ ký mặc định",
            "replacement": "Trân trọng,\nTấn Đạt",
        },
    ],
}


def load():
    """Trả dict {trigger_prefix, items: [...]}. items là list các {key, label, replacement}."""
    p = snippets_path()
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            prefix = data.get("trigger_prefix") or _DEFAULTS["trigger_prefix"]
            # Làm sạch: chỉ giữ các field string cần thiết
            items = []
            for it in data["items"]:
                if not isinstance(it, dict):
                    continue
                k = str(it.get("key") or "").strip()
                if not k:
                    continue
                items.append({
                    "key": k,
                    "label": str(it.get("label") or k),
                    "replacement": str(it.get("replacement") or ""),
                })
            return {"trigger_prefix": prefix, "items": items}
    except FileNotFoundError:
        pass
    except Exception:
        pass
    return {
        "trigger_prefix": _DEFAULTS["trigger_prefix"],
        "items": [dict(x) for x in _DEFAULTS["items"]],
    }


def save(data):
    """Ghi snippets. Atomic: .tmp -> os.replace. Nuốt lỗi."""
    if not isinstance(data, dict):
        return
    prefix = str(data.get("trigger_prefix") or _DEFAULTS["trigger_prefix"])
    items = data.get("items") or []
    clean_items = []
    for it in items:
        if not isinstance(it, dict):
            continue
        k = str(it.get("key") or "").strip()
        if not k:
            continue
        clean_items.append({
            "key": k,
            "label": str(it.get("label") or k),
            "replacement": str(it.get("replacement") or ""),
        })
    payload = {"trigger_prefix": prefix, "items": clean_items}
    p = snippets_path()
    tmp = p + ".tmp"
    with _LOCK:
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp, p)
        except Exception:
            pass


def expand(text, snippets=None):
    """Áp dụng snippets vào `text`. Trả text MỚI (không mutate input).

    Quy tắc: tìm `<prefix><key>` xuất hiện trong text ở dạng RANH GIỚI (đầu/cuối
    string, hoặc sau khoảng trắng, hoặc sau dấu câu). Thay bằng replacement.

    KHÔNG thay nếu chuỗi bị cắt ngang (vd "abc@@datexyz" -> giữ nguyên vì key
    là "date" mà theo sau là "xyz" — không phải biên từ).
    """
    if not text:
        return text
    snippets = snippets if snippets is not None else load()
    prefix = snippets.get("trigger_prefix") or "@@"
    items = snippets.get("items") or []
    if not items or not prefix:
        return text

    # Escape regex special chars trong prefix
    pref_re = re.escape(prefix)
    out = text
    for it in items:
        key = (it.get("key") or "").strip()
        repl_raw = it.get("replacement") or ""
        if not key:
            continue
        # Áp dụng placeholder runtime lên replacement
        repl = repl_raw
        for rx, fn in _runtime_patterns():
            repl = rx.sub(fn, repl)
        # Pattern: biên từ phía trước + prefix + key + biên từ phía sau
        # (?<![\wÀ-ỹ]) -> KHÔNG theo sau là chữ cái (để tránh ăn giữa từ dài)
        # (?!\w)        -> KHÔNG theo trước là chữ cái
        # Lưu ý: tiếng Việt có dấu, nên dùng \w với locale Unicode không hoàn toàn
        # chính xác. Dùng lookbehind/lookahead cho khoảng trắng + dấu câu + start/end.
        key_re = re.escape(key)
        # Dùng flag UNICODE \w mặc định OK cho cả tiếng Việt có dấu.
        # Biên trước: KHÔNG theo sau là chữ/số -> (?<!\w)
        # Biên sau: KHÔNG theo trước là chữ/số -> (?!\w)
        pattern = re.compile(r"(?<!\w)" + pref_re + key_re + r"(?!\w)")
        out = pattern.sub(repl, out)
    return out


def reset_defaults():
    """Trả về snippets mặc định + lưu lại (cho menu 'Khôi phục mặc định')."""
    data = {
        "trigger_prefix": _DEFAULTS["trigger_prefix"],
        "items": [dict(x) for x in _DEFAULTS["items"]],
    }
    save(data)
    return data
