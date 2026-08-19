"""
WakerVoice — Google Cloud Translation (REST v2, stdlib-only)
==============================================================
Gọi trực tiếp REST API v2 của Google Cloud Translation bằng urllib, KHÔNG
dùng SDK `google-cloud-translate` (tránh kéo theo grpc/protobuf nặng — giữ
đúng triết lý "nhẹ máy" của project, giống cách providers.py tự làm HTTP).

Yêu cầu: một API key đơn giản (không phải service-account JSON), tạo tại
Google Cloud Console -> APIs & Services -> Credentials, đã enable
"Cloud Translation API". Free tier: 500,000 ký tự/tháng vĩnh viễn.

Endpoint: https://translation.googleapis.com/language/translate/v2
"""

import json
import urllib.request
import urllib.parse
import urllib.error

TRANSLATE_URL = "https://translation.googleapis.com/language/translate/v2"
DETECT_URL = "https://translation.googleapis.com/language/translate/v2/detect"


def translate_text(text, *, api_key, target_lang, source_lang=None, timeout=15):
    """Dịch `text` sang `target_lang`. Trả (translated_text, detected_source_lang).

    `source_lang=None` -> Google tự nhận diện ngôn ngữ nguồn.
    Raise Exception nếu lỗi (caller tự quyết định fallback).
    """
    if not api_key:
        raise RuntimeError("Chưa có Google Translate API key")
    if not text or not text.strip():
        return "", ""

    params = {"key": api_key}
    body = {"q": text, "target": target_lang, "format": "text"}
    if source_lang and source_lang != "auto":
        body["source"] = source_lang

    url = f"{TRANSLATE_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    translations = data.get("data", {}).get("translations") or []
    if not translations:
        raise RuntimeError(f"Phản hồi Google Translate không hợp lệ: {data}")
    first = translations[0]
    out_text = first.get("translatedText") or ""
    detected = first.get("detectedSourceLanguage") or (source_lang or "")
    return out_text, detected


def test_connection(api_key, timeout=10):
    """Ping nhẹ: dịch 1 chữ ngắn -> verify key hợp lệ. Trả (ok, msg)."""
    try:
        if not api_key:
            return False, "Chưa có API key"
        text, detected = translate_text(
            "hello", api_key=api_key, target_lang="vi", timeout=timeout
        )
        return True, f"OK · {text!r} (detected={detected or '?'})"
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            body = ""
        return False, f"HTTP {e.code} · {body}"
    except Exception as e:
        return False, str(e)[:200]
