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


def test_build_wav_bytes_valid():
    """REGRESSION: _build_wav_bytes phải tạo WAV PCM16 16kHz mono ĐỌC LẠI ĐƯỢC.

    Từng có typo `setnampwidth` (thay vì setsampwidth) khiến hàm này LUÔN ném
    `wave.Error: sample width not specified` -> transcribe() luôn fail -> STT
    cloud (v1.4.0) không bao giờ ra chữ. Test này chặn tái diễn mà không cần mạng.
    """
    import io
    import wave
    import numpy as np
    audio = (0.2 * np.sin(2 * np.pi * 220 * np.arange(16000) / 16000)).astype("float32")
    data = stt_providers._build_wav_bytes(audio)
    assert data[:4] == b"RIFF", data[:4]
    with wave.open(io.BytesIO(data), "rb") as w:      # đọc lại: chứng minh header hợp lệ
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2                  # PCM16
        assert w.getframerate() == 16000
        assert w.getnframes() == 16000
    print("test_build_wav_bytes_valid OK")


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


# ---- google_translate (REST v2, stdlib-only) ----
import google_translate


def test_google_translate_no_key():
    """test_connection trả False rõ ràng khi thiếu API key (không raise)."""
    ok, msg = google_translate.test_connection("")
    assert ok is False, (ok, msg)
    assert "API key" in msg, msg
    print("test_google_translate_no_key OK")


def test_google_translate_text_empty_input():
    """translate_text với text rỗng -> trả ('', '') mà KHÔNG gọi network."""
    out, detected = google_translate.translate_text(
        "", api_key="fake-key", target_lang="en")
    assert out == "" and detected == "", (out, detected)
    print("test_google_translate_text_empty_input OK")


def test_google_translate_text_no_key_raises():
    """Thiếu API key -> raise (caller tự bắt để fallback về text gốc)."""
    try:
        google_translate.translate_text("hello", api_key="", target_lang="en")
        assert False, "phải raise khi thiếu API key"
    except RuntimeError:
        print("test_google_translate_text_no_key_raises OK")


# ---- translate_audio (VAD đơn giản) ----
import numpy as np
import translate_audio


class _FakeClock:
    """Đồng hồ giả để test VAD không phụ thuộc wall-clock thật (tránh flaky)."""

    def __init__(self, start=0.0):
        self.t = start

    def advance(self, dt):
        self.t += dt
        return self.t

    def now(self):
        return self.t


def test_translate_audio_vad_cuts_on_silence():
    """Nói 1s (RMS cao) rồi im lặng đủ lâu -> callback được gọi đúng 1 lần với audio đúng độ dài."""
    calls = []

    def on_chunk(source, audio):
        calls.append((source, audio))

    clock = _FakeClock()
    orig_monotonic = translate_audio.time.monotonic
    translate_audio.time.monotonic = clock.now
    try:
        cap = translate_audio.AudioCaptureThread("mic", on_chunk)
        sr = translate_audio.SAMPLE_RATE
        chunk_n = translate_audio.CHUNK_FRAMES
        chunk_dt = chunk_n / sr

        # 1s "nói" (biên độ đủ lớn để vượt ngưỡng RMS/peak)
        speech = (0.2 * np.ones(sr, dtype=np.float32))
        for i in range(0, len(speech), chunk_n):
            cap._process_chunk(speech[i:i + chunk_n])
            clock.advance(chunk_dt)
        assert calls == [], "chưa im lặng thì chưa được cắt đoạn"

        # im lặng đủ lâu (> SILENCE_DURATION_S) để trigger cắt đoạn
        silence = np.zeros(chunk_n, dtype=np.float32)
        n_silence_chunks = int(
            (translate_audio.SILENCE_DURATION_S + 0.3) / chunk_dt) + 1
        for _ in range(n_silence_chunks):
            clock.advance(chunk_dt)
            cap._process_chunk(silence)

        assert len(calls) == 1, f"expected 1 call, got {len(calls)}"
        got_source, got_audio = calls[0]
        assert got_source == "mic", got_source
        assert got_audio.shape[0] >= sr * translate_audio.MIN_SPEECH_DURATION_S, \
            got_audio.shape[0]
        print("test_translate_audio_vad_cuts_on_silence OK")
    finally:
        translate_audio.time.monotonic = orig_monotonic


def test_translate_audio_vad_skips_short_noise():
    """Đoạn nói quá ngắn (< MIN_SPEECH_DURATION_S) -> KHÔNG gọi callback (tránh tiếng động vặt)."""
    calls = []
    clock = _FakeClock()
    orig_monotonic = translate_audio.time.monotonic
    translate_audio.time.monotonic = clock.now
    try:
        cap = translate_audio.AudioCaptureThread("system", lambda s, a: calls.append((s, a)))
        sr = translate_audio.SAMPLE_RATE
        chunk_n = translate_audio.CHUNK_FRAMES
        chunk_dt = chunk_n / sr

        # Chỉ 0.1s "nói" (< MIN_SPEECH_DURATION_S = 0.5s)
        short_speech = (0.2 * np.ones(int(sr * 0.1), dtype=np.float32))
        cap._process_chunk(short_speech)
        clock.advance(0.1)

        silence = np.zeros(chunk_n, dtype=np.float32)
        n_silence_chunks = int(
            (translate_audio.SILENCE_DURATION_S + 0.3) / chunk_dt) + 1
        for _ in range(n_silence_chunks):
            clock.advance(chunk_dt)
            cap._process_chunk(silence)

        assert calls == [], f"đoạn ngắn phải bị loại, got {calls}"
        print("test_translate_audio_vad_skips_short_noise OK")
    finally:
        translate_audio.time.monotonic = orig_monotonic


# ---- translate_engine (mock STT + mock Google Translate) ----
import translate_engine as tr_eng_mod


def test_translate_engine_init_defaults():
    """TranslateEngine khởi tạo với config mặc định (chưa có key nào)."""
    tmp = tempfile.mkdtemp()
    os.environ["APPDATA"] = tmp
    os.environ["LOCALAPPDATA"] = tmp
    try:
        import importlib
        for mod in ["config", "providers", "translate_engine"]:
            if mod in sys.modules:
                importlib.reload(sys.modules[mod])
        import translate_engine as te_mod
        eng = te_mod.TranslateEngine(lambda *a: None)
        assert eng.target_lang == "en", eng.target_lang
        assert eng.source_lang == "auto", eng.source_lang
        assert eng.google_api_key == "", eng.google_api_key
        assert eng._running is False
        print("test_translate_engine_init_defaults OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_translate_engine_worker_stt_and_translate(monkeypatch=None):
    """Worker: audio -> STT (mock) -> translate (mock) -> emit('translate_result', ...)."""
    tmp = tempfile.mkdtemp()
    os.environ["APPDATA"] = tmp
    os.environ["LOCALAPPDATA"] = tmp
    cfg_path = os.path.join(tmp, "WakerVoice", "config.json")
    try:
        os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump({
                "provider": "groq",
                "providers": {"groq": {"api_key": "gsk_test"}},
                "model": "whisper-large-v3",
                "translate_target_lang": "en",
                "translate_source_lang": "auto",
                "google_translate_api_key": "fake-google-key",
            }, f)

        import importlib
        for mod in ["config", "providers", "translate_engine"]:
            if mod in sys.modules:
                importlib.reload(sys.modules[mod])
        import translate_engine as te_mod
        import providers as stt_mod
        import google_translate as gt_mod

        events = []
        eng = te_mod.TranslateEngine(lambda ev, pl=None: events.append((ev, pl)))
        assert eng.stt_api_key == "gsk_test", eng.stt_api_key
        assert eng.google_api_key == "fake-google-key", eng.google_api_key

        # Mock STT: trả text tiếng Việt cố định (không gọi network thật)
        stt_mod.transcribe = lambda *a, **kw: ("xin chào", "vi")
        te_mod.stt_providers.transcribe = stt_mod.transcribe
        # Mock Google Translate: trả bản dịch cố định
        gt_mod.translate_text = lambda text, *, api_key, target_lang, source_lang=None, timeout=15: ("hello", "vi")
        te_mod.google_translate.translate_text = gt_mod.translate_text

        eng._running = True     # giả lập đang chạy (không start audio thật)
        fake_audio = np.zeros(16000, dtype=np.float32)
        eng._work_queue.put(("mic", fake_audio))

        # Chạy 1 vòng worker thủ công (không spawn thread để test tất định)
        source, audio = eng._work_queue.get(timeout=1.0)
        text, lang = eng._transcribe(audio)
        translated = eng._translate_text(text, lang)
        eng.emit("translate_result", {
            "source": source, "original": text,
            "translated": translated, "lang_detected": lang,
        })

        assert text == "xin chào", text
        assert lang == "vi", lang
        assert translated == "hello", translated
        assert len(events) == 1, events
        ev, pl = events[0]
        assert ev == "translate_result", ev
        assert pl["source"] == "mic", pl
        assert pl["translated"] == "hello", pl
        print("test_translate_engine_worker_stt_and_translate OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_translate_engine_translate_skips_same_lang():
    """Nếu ngôn ngữ đã nhận diện == ngôn ngữ đích -> khỏi gọi Google Translate (tiết kiệm quota)."""
    tmp = tempfile.mkdtemp()
    os.environ["APPDATA"] = tmp
    os.environ["LOCALAPPDATA"] = tmp
    try:
        import importlib
        for mod in ["config", "providers", "translate_engine"]:
            if mod in sys.modules:
                importlib.reload(sys.modules[mod])
        import translate_engine as te_mod

        called = {"n": 0}

        def fake_translate(text, *, api_key, target_lang, source_lang=None, timeout=15):
            called["n"] += 1
            return "SHOULD NOT BE CALLED", "en"

        te_mod.google_translate.translate_text = fake_translate
        eng = te_mod.TranslateEngine(lambda *a: None)
        eng.target_lang = "en"
        eng.google_api_key = "fake-key"

        out = eng._translate_text("hello there", "en")
        assert out == "hello there", out
        assert called["n"] == 0, "không được gọi Google Translate khi cùng ngôn ngữ"
        print("test_translate_engine_translate_skips_same_lang OK")
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
    test_google_translate_no_key()
    test_google_translate_text_empty_input()
    test_google_translate_text_no_key_raises()
    test_translate_audio_vad_cuts_on_silence()
    test_translate_audio_vad_skips_short_noise()
    test_translate_engine_init_defaults()
    test_translate_engine_worker_stt_and_translate()
    test_translate_engine_translate_skips_same_lang()
    print("\nALL TESTS PASSED")
