"""
WakerVoice — lịch sử phiên chép (append-only, JSONL).
=====================================================
Mỗi lần engine chép thành công (không bị lọc ảo giác) -> append một dòng vào
file JSONL ở %LOCALAPPDATA%\\WakerVoice\\history.jsonl.

Mục đích:
  - Cho user gõ lại / copy lại những gì vừa chép (hữu ích khi vừa chép xong quên
    mất, hoặc paste nhầm chỗ).
  - Hỗ trợ thống kê usage / word-count / thời lượng nói.

File JSONL an toàn vì:
  - Mỗi dòng là JSON độc lập (ghi xuống atomic enough cho mục đích này).
  - Append-only: ghi lỗi không phá các dòng cũ.
  - Append duyệt/đọc bằng load() trả list dict.
"""

import os
import json
import threading
import time


_LOCK = threading.Lock()


def history_dir():
    """%LOCALAPPDATA%\\WakerVoice (tạo nếu thiếu)."""
    base = os.environ.get("LOCALAPPDATA") or os.path.join(
        os.path.expanduser("~"), ".config"
    )
    d = os.path.join(base, "WakerVoice")
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    return d


def history_path():
    return os.path.join(history_dir(), "history.jsonl")


def _truncate_for_storage(text, limit=4000):
    """Cắt chuỗi quá dài (tránh nặng file + UI lag khi render dòng dài)."""
    if not text:
        return ""
    s = str(text).strip()
    if len(s) <= limit:
        return s
    return s[: limit - 1] + "…"


def append(text, *, language="auto", refine=False, model="", duration_s=0.0):
    """Append một bản ghi. Nuốt MỌI lỗi — không bao giờ làm phiền flow chính."""
    rec = {
        "ts": time.time(),
        "iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "hhmm": time.strftime("%H:%M"),
        "text": _truncate_for_storage(text),
        "language": language or "",
        "refine": bool(refine),
        "model": model or "",
        "dur": round(float(duration_s or 0.0), 1),
    }
    with _LOCK:
        try:
            with open(history_path(), "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:
            pass


def load(limit=200):
    """Trả list dict, mới nhất trước, tối đa `limit` dòng. Lỗi file -> [].

    Trả về MỚI TRƯỚC để UI submenu dễ hiển thị.
    """
    out = []
    try:
        with open(history_path(), "r", encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        return out
    except Exception:
        return out
    for line in reversed(lines[-limit:]):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def clear():
    """Xoá file lịch sử (cho menu UI)."""
    with _LOCK:
        try:
            os.remove(history_path())
        except FileNotFoundError:
            pass
        except Exception:
            pass


def stats():
    """Tổng quan nhỏ cho menu: tổng số lần chép, tổng từ (xấp xỉ)."""
    items = load(limit=10000)
    n = len(items)
    word = sum(len((it.get("text") or "").split()) for it in items)
    return {"count": n, "words": word}
