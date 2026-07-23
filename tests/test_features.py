"""
WakerVoice — tests cho history, snippets, providers.
Chạy: python tests/test_features.py
Không cần mạng, không cần Qt — chỉ test logic thuần.
"""

import os
import sys
import json
import tempfile
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# ---- history ----
import history

def test_history_roundtrip():
    """Append + load trả về đúng nội dung, mới nhất trước."""
    tmp = tempfile.mkdtemp()
    os.environ["LOCALAPPDATA"] = tmp
    try:
        history.clear()
        history.append("xin chào", language="vi", refine=True, model="whisper-large-v3", duration_s=1.5)
        history.append("hello", language="en", refine=False, model="whisper-large-v3-turbo", duration_s=0.7)
        items = history.load(limit=10)
        assert len(items) == 2, f"len={len(items)}"
        # mới nhất trước
        assert items[0]["text"] == "hello", items
        assert items[1]["text"] == "xin chào", items
        assert items[0]["language"] == "en", items
        assert items[1]["refine"] is True, items
        assert items[0]["dur"] == 0.7, items
        # stats
        s = history.stats()
        assert s["count"] == 2, s
        assert s["words"] >= 2, s
        # clear
        history.clear()
        assert history.load() == []
        print("test_history_roundtrip OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---- snippets ----
import snippets

def test_snippets_expand_basic():
    text = "hôm nay là @@date và giờ @@time"
    out = snippets.expand(text)
    assert "hôm nay là " in out
    # @@date -> dd/MM/yyyy (10 ký tự)
    # @@time -> HH:MM (5 ký tự)
    assert len(out) > len(text), (len(text), len(out))
    print("test_snippets_expand_basic OK (out len=%d)" % len(out))


def test_snippets_word_boundary():
    """Không thay khi trigger nằm giữa từ."""
    text = "abc@@datexyz"
    out = snippets.expand(text)
    assert out == text, (text, out)
    print("test_snippets_word_boundary OK")


def test_snippets_empty():
    assert snippets.expand("") == ""
    assert snippets.expand(None) is None
    print("test_snippets_empty OK")


def test_snippets_custom():
    data = {
        "trigger_prefix": "!!",
        "items": [
            {"key": "hello", "label": "Chào", "replacement": "Xin chào bạn"},
            {"key": "mail", "label": "Email", "replacement": "[email protected]"},
        ],
    }
    snippets.save(data)
    loaded = snippets.load()
    assert loaded["trigger_prefix"] == "!!"
    items = {it["key"]: it for it in loaded["items"]}
    assert items["hello"]["replacement"] == "Xin chào bạn"
    out = snippets.expand("nói !!hello nhé")
    assert "Xin chào bạn" in out, out
    out2 = snippets.expand("!!mail nhé")
    assert "[email protected]" in out2, out2
    print("test_snippets_custom OK")


def test_snippets_round_trip():
    """save + load phải khớp (trừ field làm sạch)."""
    tmp = tempfile.mkdtemp()
    os.environ["LOCALAPPDATA"] = tmp
    try:
        data = {"trigger_prefix": "@@", "items": [
            {"key": "k", "label": "L", "replacement": "R"},
        ]}
        snippets.save(data)
        loaded = snippets.load()
        assert loaded["trigger_prefix"] == "@@"
        assert loaded["items"][0]["key"] == "k"
        print("test_snippets_round_trip OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_snippets_placeholders_safe():
    """Runtime placeholders KHÔNG để lại {{...}}."""
    text = "@@date @@time @@weekday"
    out = snippets.expand(text)
    assert "{{" not in out, out
    assert "}}" not in out, out
    print("test_snippets_placeholders_safe OK")


# ---- providers ----
import providers as stt_providers

def test_providers_builtin():
    p = stt_providers.get_provider("groq")
    assert p["id"] == "groq"
    assert "whisper-large-v3" in p["models"]
    assert p["supports_refine"] is True
    p2 = stt_providers.get_provider("openai")
    assert p2["id"] == "openai"
    assert "gpt-4o-transcribe" in p2["models"]
    print("test_providers_builtin OK")


def test_providers_fallback_unknown():
    """Provider id không tồn tại -> fallback Groq."""
    p = stt_providers.get_provider("does-not-exist")
    assert p["id"] == "groq", p
    print("test_providers_fallback_unknown OK")


def test_providers_all_lists_custom():
    """all_providers trả Groq + OpenAI + custom nếu có."""
    allp = stt_providers.all_providers()
    assert "groq" in allp
    assert "openai" in allp
    print("test_providers_all_lists_custom OK")


# ---- engine importability smoke test ----
def test_engine_import():
    """Engine import không lỗi (không cần chạy)."""
    # Tạo fake config trước
    import config
    tmp = tempfile.mkdtemp()
    os.environ["APPDATA"] = tmp
    os.environ["LOCALAPPDATA"] = tmp
    try:
        import importlib
        for mod in ["engine"]:
            if mod in sys.modules:
                importlib.reload(sys.modules[mod])
        # Không start, chỉ import
        import engine as eng_mod
        assert hasattr(eng_mod, "SttEngine")
        print("test_engine_import OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---- back-compat cấu hình cũ (chỉ groq_api_key ở top-level) ----
def test_backcompat_old_config():
    """config cũ chỉ có groq_api_key ở top-level vẫn hoạt động."""
    tmp = tempfile.mkdtemp()
    os.environ["APPDATA"] = tmp
    os.environ["LOCALAPPDATA"] = tmp
    cfg_path = os.path.join(tmp, "WakerVoice", "config.json")
    try:
        # Tạo config.json kiểu cũ
        os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump({
                "language": "vi",
                "groq_api_key": "gsk_legacy_key_for_test",
                "groq_model": "whisper-large-v3",
                "refine": True,
                "refine_model": "llama-3.3-70b-versatile",
            }, f)

        import importlib
        for mod in ["config", "providers", "engine"]:
            if mod in sys.modules:
                importlib.reload(sys.modules[mod])
        import providers as stt_providers
        # groq_provider vẫn resolve được key cũ
        k = stt_providers.get_api_key("groq")
        assert k == "gsk_legacy_key_for_test", f"got {k!r}"
        print("test_backcompat_old_config OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---- engine SttEngine cũ vẫn khởi tạo được với config mới + multi-provider ----
def test_engine_init_multiprovider():
    """SttEngine khởi tạo thành công với provider mặc định Groq + config JSON."""
    tmp = tempfile.mkdtemp()
    os.environ["APPDATA"] = tmp
    os.environ["LOCALAPPDATA"] = tmp
    cfg_path = os.path.join(tmp, "WakerVoice", "config.json")
    try:
        os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump({
                "language": "auto",
                "provider": "groq",
                "providers": {"groq": {"api_key": "gsk_test"}},
                "model": "whisper-large-v3",
                "refine": True,
                "refine_model": "llama-3.3-70b-versatile",
                "groq_prompt": "",
            }, f)
        import importlib
        for mod in ["config", "providers", "engine"]:
            if mod in sys.modules:
                importlib.reload(sys.modules[mod])
        # Stub ra module cần thiết — không start (cần Qt / pynput) chỉ init
        import engine as eng_mod
        # Patch SttEngine.start để no-op (tránh pynput runtime issue)
        orig_start = eng_mod.SttEngine.start
        eng_mod.SttEngine.start = lambda self: None
        # Patch keyboard.Listener để no-op
        from pynput import keyboard
        orig_listener = keyboard.Listener
        class FakeListener:
            def __init__(self, *a, **kw): pass
            def start(self): pass
            @property
            def running(self): return True
            def stop(self): pass
        keyboard.Listener = FakeListener
        try:
            e = eng_mod.SttEngine(lambda *a: None)
            assert e.provider_id == "groq", e.provider_id
            assert e.model == "whisper-large-v3", e.model
            assert e.api_key == "gsk_test", e.api_key
            # Đổi provider
            new = e.set_provider("openai")
            assert new["id"] == "openai", new
            assert e.provider_id == "openai", e.provider_id
            assert e.model == "gpt-4o-transcribe", e.model
            assert e.api_key == "", e.api_key   # chưa có key cho openai
            print("test_engine_init_multiprovider OK")
        finally:
            eng_mod.SttEngine.start = orig_start
            keyboard.Listener = orig_listener
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    test_history_roundtrip()
    test_snippets_expand_basic()
    test_snippets_word_boundary()
    test_snippets_empty()
    test_snippets_custom()
    test_snippets_round_trip()
    test_snippets_placeholders_safe()
    test_providers_builtin()
    test_providers_fallback_unknown()
    test_providers_all_lists_custom()
    test_engine_import()
    test_backcompat_old_config()
    test_engine_init_multiprovider()
    print("\nALL TESTS PASSED")
