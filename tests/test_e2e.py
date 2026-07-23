"""
WakerVoice — end-to-end test (không cần mạng, không cần Qt).
=========================================================
Mục đích: verify LUỒNG ĐẦY ĐỦ từ SttEngine -> Provider (mock) -> History ->
Snippets -> Output (type/clipboard) hoạt động đúng.

Mock provider.transcribe để không cần gọi Groq thật; verify chuỗi cuối cùng
đã được refine + expand + ghi history đúng cách.
"""

import os
import sys
import json
import tempfile
import shutil
import importlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _isolated_env():
    """Tạo env tách biệt với máy thật, trả (tmp, cleanup)."""
    tmp = tempfile.mkdtemp(prefix="wakervoice_e2e_")
    os.environ["APPDATA"] = tmp
    os.environ["LOCALAPPDATA"] = tmp
    return tmp


def _reload_all():
    """Reload tất cả module liên quan (để config mới có hiệu lực)."""
    for mod in list(sys.modules):
        if mod in ("config", "providers", "engine", "history", "snippets"):
            importlib.reload(sys.modules[mod])


def _write_config(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _stub_pynput_listener():
    """Chặn keyboard.Listener thật (cần UAC / desktop session)."""
    from pynput import keyboard
    class _Fake:
        def __init__(self, *a, **kw): pass
        def start(self): pass
        @property
        def running(self): return True
        def stop(self): pass
    keyboard.Listener = _Fake


def _make_audio(dur=1.5, freq=440):
    """Tạo float32 audio có sine wave (tránh bị skip im lặng)."""
    import numpy as np
    sr = 16000
    t = np.linspace(0, dur, int(sr * dur), endpoint=False)
    audio = (0.2 * np.sin(2 * 3.14159 * freq * t)).astype(np.float32)
    return audio


def test_e2e_full_flow():
    """SttEngine -> mock provider -> history + snippets + output."""
    tmp = _isolated_env()
    try:
        cfg_path = os.path.join(tmp, "WakerVoice", "config.json")
        _write_config(cfg_path, {
            "language": "vi",
            "provider": "groq",
            "providers": {"groq": {"api_key": "gsk_fake"}},
            "model": "whisper-large-v3",
            "refine": False,            # tắt refine để verify flow đơn giản
            "refine_model": "llama-3.3-70b-versatile",
            "groq_prompt": "",
        })

        _reload_all()
        _stub_pynput_listener()

        # Patch SttEngine.start để không cần Qt pump
        import engine
        engine.SttEngine.start = lambda self: None

        # Mock provider.transcribe/refine
        def fake_transcribe(audio, **kw):
            return "hôm nay là @@date và @@sign", "vietnamese"

        engine.stt_providers.transcribe = fake_transcribe
        engine.stt_providers.refine = lambda text, **kw: text  # no-op

        # Snippets setup
        import snippets
        snippets.save({
            "trigger_prefix": "@@",
            "items": [
                {"key": "date", "label": "date",
                 "replacement": "23/07/2026"},
                {"key": "sign", "label": "sign",
                 "replacement": "Trân trọng,\nTấn Đạt"},
            ],
        })

        e = engine.SttEngine(lambda *a: None)
        e.output_mode = "clipboard"  # tránh pynput gõ phím

        # Gọi _transcribe_and_emit trực tiếp (không cần qua toggle)
        audio = _make_audio(dur=1.5, freq=440)
        e._transcribe_and_emit(audio)

        # Verify history đã ghi
        import history
        items = history.load(limit=10)
        assert len(items) == 1, f"expected 1, got {len(items)}"
        rec = items[0]
        # Snippets phải được expand
        assert rec["text"] == "hôm nay là 23/07/2026 và Trân trọng,\nTấn Đạt", \
            f"got: {rec['text']!r}"
        assert rec["language"] == "vi"
        assert rec["model"] == "whisper-large-v3"
        # duration ~1.5s
        assert 1.0 < rec["dur"] < 3.0, f"dur={rec['dur']}"

        # Verify clipboard được set
        import pyperclip
        clip = pyperclip.paste()
        assert "23/07/2026" in clip, f"clip: {clip!r}"
        assert "Trân trọng" in clip, f"clip: {clip!r}"

        print(f"test_e2e_full_flow OK (text len={len(rec['text'])})")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_e2e_provider_switch():
    """Đổi provider Groq -> OpenAI giữ config, key OpenAI đọc đúng từ slot."""
    tmp = _isolated_env()
    try:
        cfg_path = os.path.join(tmp, "WakerVoice", "config.json")
        _write_config(cfg_path, {
            "language": "auto",
            "provider": "groq",
            "providers": {
                "groq": {"api_key": "gsk_groq"},
                "openai": {"api_key": "sk_openai"},
            },
            "model": "whisper-large-v3",
            "refine": True,
            "refine_model": "llama-3.3-70b-versatile",
        })
        _reload_all()
        _stub_pynput_listener()

        import engine
        engine.SttEngine.start = lambda self: None
        e = engine.SttEngine(lambda *a: None)
        assert e.provider_id == "groq"
        assert e.api_key == "gsk_groq"

        # Chuyển sang OpenAI
        new = e.set_provider("openai")
        assert new["id"] == "openai"
        assert e.api_key == "sk_openai"
        assert e.model == "gpt-4o-transcribe"
        assert e.refine_model == "gpt-4o-mini"

        # Chuyển lại Groq
        new2 = e.set_provider("groq")
        assert new2["id"] == "groq"
        assert e.api_key == "gsk_groq"
        assert e.model == "whisper-large-v3"
        print("test_e2e_provider_switch OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_e2e_empty_audio_skipped():
    """Audio im lặng < 0.3s sẽ bị skip — không ghi history."""
    tmp = _isolated_env()
    try:
        cfg_path = os.path.join(tmp, "WakerVoice", "config.json")
        _write_config(cfg_path, {
            "language": "auto",
            "provider": "groq",
            "providers": {"groq": {"api_key": "gsk_x"}},
            "model": "whisper-large-v3",
            "refine": False,
            "refine_model": "x",
        })
        _reload_all()
        _stub_pynput_listener()
        import engine
        engine.SttEngine.start = lambda self: None
        e = engine.SttEngine(lambda *a: None)
        e.output_mode = "clipboard"

        import numpy as np
        silent = np.zeros(int(0.1 * 16000), dtype=np.float32)  # 0.1s im lặng
        e._transcribe_and_emit(silent)

        import history
        items = history.load()
        assert len(items) == 0, f"silent phải KHÔNG ghi history, got {len(items)}"
        print("test_e2e_empty_audio_skipped OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_e2e_api_key_roundtrip():
    """set_api_key lưu đúng -> load lại thấy key mới."""
    tmp = _isolated_env()
    try:
        cfg_path = os.path.join(tmp, "WakerVoice", "config.json")
        _write_config(cfg_path, {
            "language": "auto",
            "provider": "openai",
            "providers": {"openai": {"api_key": "sk_first"}},
            "model": "gpt-4o-transcribe",
            "refine": False,
            "refine_model": "gpt-4o-mini",
        })
        _reload_all()
        _stub_pynput_listener()
        import engine
        engine.SttEngine.start = lambda self: None
        e = engine.SttEngine(lambda *a: None)
        assert e.api_key == "sk_first"
        e.set_api_key("sk_second")
        assert e.api_key == "sk_second"

        # Reload config từ đĩa, verify key đã save
        import config
        data = config.load()
        assert data["providers"]["openai"]["api_key"] == "sk_second"
        print("test_e2e_api_key_roundtrip OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    test_e2e_full_flow()
    test_e2e_provider_switch()
    test_e2e_empty_audio_skipped()
    test_e2e_api_key_roundtrip()
    print("\nALL E2E TESTS PASSED")
