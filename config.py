"""
WakerVoice — cấu hình người dùng
============================
Lưu Groq API key + tuỳ chọn ở %APPDATA%\\WakerVoice\\config.json (Windows) /
~/.config/WakerVoice (khác). Cố tình tối giản: không phụ thuộc thư viện ngoài,
đọc/ghi an toàn khi lỗi.
"""

import os
import json
import threading

_LOCK = threading.Lock()

# Schema các key "biết tên" mà DEFAULTS định nghĩa. Tất cả key khác (provider,
# providers, model, custom_providers, ...) đều được giữ nguyên qua load/save.
DEFAULTS = {
    "language": "auto",                       # "auto" (Việt+Anh) | "vi" | "en"
    "groq_api_key": "",
    "groq_model": "whisper-large-v3",         # chuẩn hơn cho tiếng Việt (turbo nhanh nhưng kém dấu)
    "groq_prompt": "",                        # gợi ý từ vựng/tên riêng để chép đúng hơn
    "refine": True,                           # LLM dọn dấu/chính tả tiếng Việt sau khi chép (+~0.5s)
    "refine_model": "llama-3.3-70b-versatile",  # nhanh + trung thực (không bịa/đổi từ)
    "installed": False,                       # đã tạo lối tắt + bật startup lần đầu chưa
}


def _config_dir():
    base = os.environ.get("APPDATA")
    if not base:
        base = os.path.join(os.path.expanduser("~"), ".config")
    d = os.path.join(base, "WakerVoice")
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    return d


def _config_path():
    return os.path.join(_config_dir(), "config.json")


def load():
    """Trả về cấu hình đầy đủ (mặc định + đã lưu + override từ env GROQ_API_KEY).

    QUAN TRỌNG: giữ TẤT CẢ key từ file lưu (kể cả key không có trong DEFAULTS —
    vd 'provider', 'providers', 'model', 'custom_providers'). DEFAULTS chỉ để
    fallback khi key thiếu.
    """
    cfg = dict(DEFAULTS)
    try:
        with open(_config_path(), encoding="utf-8") as f:
            saved = json.load(f)
        if isinstance(saved, dict):
            # merge: file lưu đè mặc định, nhưng vẫn giữ DEFAULTS cho key thiếu
            for k, v in saved.items():
                cfg[k] = v
    except Exception:
        pass
    env_key = os.environ.get("GROQ_API_KEY")
    if env_key and not cfg.get("groq_api_key"):
        cfg["groq_api_key"] = env_key.strip()
    return cfg


def save(cfg):
    """Ghi cấu hình. Giữ TẤT CẢ key user truyền vào (không lọc theo DEFAULTS)."""
    if not isinstance(cfg, dict):
        return {}
    # Bù DEFAULTS cho key thiếu (để file luôn đầy đủ)
    out = dict(DEFAULTS)
    for k, v in cfg.items():
        out[k] = v
    with _LOCK:
        try:
            with open(_config_path(), "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
    return out
