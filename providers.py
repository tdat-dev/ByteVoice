"""
WakerVoice — multi-provider STT
==============================
Mỗi provider có:
  - id              ("groq" | "openai" | "openai_compat")
  - display_name    (hiện trong menu tray)
  - audio_url       (endpoint /audio/transcriptions)
  - chat_url        (endpoint /chat/completions — cho refine; provider nào
                     không có chat thì refine bị tắt cho provider đó)
  - models          (list các model id Whisper hỗ trợ)
  - api_key_field   (tên field trong config.json)
  - key_format      ("bearer")
  - supports_refine (bool)
  - needs_multipart (bool)  — Groq dùng multipart/form-data; nếu provider khác
                               yêu cầu JSON base64 thì False

Lưu trong config.json:
    {
      "provider": "groq",
      "providers": {
        "groq":           { "api_key": "..." },
        "openai":         { "api_key": "..." },
        "my_proxy":       { "api_key": "...", "base_url": "https://...",
                            "model": "whisper-1", "chat_model": "gpt-4o-mini" }
      },
      "model": "whisper-large-v3",
      "refine": true,
      "refine_model": "llama-3.3-70b-versatile",
      ...
    }

Provider `openai_compat` là wildcard cho mọi endpoint OpenAI-compatible
(OpenAI, Together, Fireworks, self-hosted). User tự đặt `base_url` và `api_key`
trong config (UI sẽ có textbox cho nó).
"""

import os
import io
import re
import json
import time
import uuid
import wave
import urllib.request
import urllib.error

try:
    import numpy as np
except Exception:                                # pragma: no cover
    np = None


# ----------------------- BUILT-IN -----------------------
BUILTIN_PROVIDERS = {
    "groq": {
        "id": "groq",
        "display_name": "Groq (miễn phí nhanh)",
        "audio_url": "https://api.groq.com/openai/v1/audio/transcriptions",
        "chat_url": "https://api.groq.com/openai/v1/chat/completions",
        "default_model": "whisper-large-v3",
        "models": ["whisper-large-v3", "whisper-large-v3-turbo"],
        "supports_refine": True,
        "default_refine_model": "llama-3.3-70b-versatile",
        "refine_models": [
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
        ],
        "needs_multipart": True,
        "extra_headers": {"User-Agent": "WakerVoice/1.0"},
    },
    "openai": {
        "id": "openai",
        "display_name": "OpenAI (gpt-4o-transcribe)",
        "audio_url": "https://api.openai.com/v1/audio/transcriptions",
        "chat_url": "https://api.openai.com/v1/chat/completions",
        "default_model": "gpt-4o-transcribe",
        "models": ["gpt-4o-transcribe", "gpt-4o-mini-transcribe", "whisper-1"],
        "supports_refine": True,
        "default_refine_model": "gpt-4o-mini",
        "refine_models": ["gpt-4o-mini", "gpt-4o"],
        "needs_multipart": True,
        "extra_headers": {"User-Agent": "WakerVoice/1.0"},
    },
}


def _custom_providers():
    """Đọc user-defined custom providers từ config (custom_providers list)."""
    try:
        import config as cfg
        data = cfg.load()
        customs = data.get("custom_providers") or []
        out = {}
        for c in customs:
            if not isinstance(c, dict):
                continue
            pid = (c.get("id") or "").strip()
            if not pid:
                continue
            base = (c.get("base_url") or "").rstrip("/")
            if not base:
                continue
            out[pid] = {
                "id": pid,
                "display_name": c.get("display_name") or pid,
                "audio_url": f"{base}/audio/transcriptions",
                "chat_url": f"{base}/chat/completions",
                "default_model": c.get("model") or "whisper-1",
                "models": c.get("models") or [c.get("model") or "whisper-1"],
                "supports_refine": bool(c.get("supports_refine", True)),
                "default_refine_model": c.get("chat_model") or "gpt-4o-mini",
                "refine_models": c.get("chat_models")
                                 or [c.get("chat_model") or "gpt-4o-mini"],
                "needs_multipart": bool(c.get("needs_multipart", True)),
                "extra_headers": c.get("extra_headers") or {},
                "is_custom": True,
            }
        return out
    except Exception:
        return {}


def all_providers():
    return {**BUILTIN_PROVIDERS, **_custom_providers()}


def get_provider(pid):
    """Trả dict provider hoặc None. Auto-fallback về Groq nếu pid không tồn tại."""
    allp = all_providers()
    if pid in allp:
        return allp[pid]
    return BUILTIN_PROVIDERS["groq"]


def get_api_key(pid):
    """API key của provider `pid` từ config (nuốt lỗi)."""
    try:
        import config as cfg
        data = cfg.load()
        providers = data.get("providers") or {}
        if isinstance(providers, dict):
            k = providers.get(pid)
            if isinstance(k, dict):
                v = (k.get("api_key") or "").strip()
                if v:
                    return v
        # backward-compat: groq_api_key ở top-level
        if pid == "groq":
            v = (data.get("groq_api_key") or "").strip()
            if v:
                return v
        return ""
    except Exception:
        return ""


# ----------------------- HTTP helpers (stdlib) -----------------------
def _build_wav_bytes(audio):
    """float32 numpy array -> WAV PCM16 mono 16kHz bytes."""
    pcm = np.clip(audio, -1.0, 1.0)
    pcm16 = (pcm * 32767.0).astype("<i2").tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setnampwidth(2)
        w.setframerate(16000)
        w.writeframes(pcm16)
    return buf.getvalue()


def _post_multipart(url, headers, fields, file_name, file_bytes, file_content_type,
                    timeout=60):
    boundary = "----WakerVoiceBoundary" + uuid.uuid4().hex
    body = b""
    for k, v in fields.items():
        body += (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{k}"\r\n\r\n'
            f"{v}\r\n"
        ).encode("utf-8")
    body += (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{file_name}"\r\n'
        f"Content-Type: {file_content_type}\r\n\r\n"
    ).encode("utf-8")
    body += file_bytes + b"\r\n"
    body += f"--{boundary}--\r\n".encode("utf-8")

    req = urllib.request.Request(
        url, data=body, method="POST", headers={
            **headers,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post_json(url, headers, payload, timeout=60):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={**headers, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ----------------------- Transcribe -----------------------
def transcribe(audio, *, provider, api_key, model, language="auto",
               prompt="", timeout=60):
    """Gọi STT provider. Trả (text, lang_code). Raise nếu lỗi.

    `prompt` chỉ gửi khi provider hỗ trợ (Groq/OpenAI đều có).
    `language="auto"` -> KHÔNG gửi trường language (để provider tự nhận).
    """
    if not api_key:
        raise RuntimeError(f"Chưa có API key cho provider '{provider['id']}'")

    headers = {
        "Authorization": f"Bearer {api_key}",
        **provider.get("extra_headers", {}),
    }
    wav = _build_wav_bytes(audio)

    fields = {"model": model, "temperature": "0",
              "response_format": "verbose_json"}
    if language and language != "auto":
        fields["language"] = language
    if prompt:
        fields["prompt"] = prompt

    data = _post_multipart(
        provider["audio_url"], headers, fields,
        file_name="audio.wav", file_bytes=wav,
        file_content_type="audio/wav", timeout=timeout,
    )
    text = (data.get("text") or "").strip()
    lang = (data.get("language") or "").lower()
    return text, lang


# ----------------------- Refine (LLM chỉnh dấu) -----------------------
def refine(text, *, provider, api_key, model, system_prompt, timeout=30):
    """Gọi chat completion để refine. Trả string mới. Lỗi -> trả text gốc."""
    try:
        if not provider.get("supports_refine", True):
            return text
        if not api_key:
            return text
        headers = {
            "Authorization": f"Bearer {api_key}",
            **provider.get("extra_headers", {}),
        }
        max_tok = min(4096, max(256, len(text) // 2 + 64))
        payload = {
            "model": model,
            "temperature": 0,
            "max_tokens": max_tok,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
        }
        data = _post_json(provider["chat_url"], headers, payload, timeout=timeout)
        out = (data.get("choices", [{}])[0].get("message", {}).get("content")
               or "").strip()
        out = re.sub(r"<think>.*?</think>", "", out, flags=re.S).strip()
        if out.startswith('"') and out.endswith('"'):
            out = out[1:-1].strip()
        return out
    except Exception:
        return text


# ----------------------- Connection test -----------------------
def test_connection(provider, api_key, timeout=10):
    """Ping nhẹ: gửi 0.5s silence -> verify 200 OK. Trả (ok, msg)."""
    try:
        if np is None:
            return False, "numpy chưa cài"
        if not api_key:
            return False, "Chưa có API key"
        # 0.3s silence @16kHz
        silence = np.zeros(int(0.3 * 16000), dtype=np.float32)
        text, lang = transcribe(
            silence, provider=provider, api_key=api_key,
            model=provider.get("default_model") or "",
            language="auto", prompt="", timeout=timeout,
        )
        return True, f"OK · {lang or '?'}"
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            body = ""
        return False, f"HTTP {e.code} · {body}"
    except Exception as e:
        return False, str(e)[:200]
