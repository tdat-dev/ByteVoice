"""
WakerVoice — Translate Engine (STT + Google Translate)
========================================================
Nhận audio chunks từ translate_audio -> STT qua providers.transcribe (Groq/OpenAI,
provider đã cấu hình sẵn cho push-to-talk) -> dịch text qua Google Cloud
Translation API (REST v2, stdlib-only) -> emit events về UI.

Hoàn toàn tách biệt khỏi SttEngine (push-to-talk) hiện có: không share thread,
không share audio stream, không đụng config key nào của SttEngine.

Engine tách rời UI qua callback emit(event, payload):
    emit("translate_state", "idle" | "listening" | "error")
    emit("translate_result", {"source": "mic"|"system", "original": str,
                              "translated": str, "lang_detected": str})
    emit("translate_error", str)
"""

import sys
import threading
import queue

import config
import providers as stt_providers
import google_translate


# Tối đa 4 đoạn audio chờ xử lý — tránh worker bị dồn, tránh queue tràn gây
# crash native trên Python 3.14 + Qt + PyAudioWPatch.
_MAX_QUEUE = 4


class TranslateEngine:
    """Engine dịch realtime: audio (mic + system) -> STT -> translate -> emit."""

    def __init__(self, emit):
        self.emit = emit
        self._running = False
        self._audio_manager = None
        # Pipeline 2 tầng: _work_queue (audio) -> STT -> _xlate_queue (text) -> dịch.
        # Tách 2 tầng để STT đoạn N+1 chạy CHỒNG lên lúc đang dịch đoạn N; mỗi tầng
        # một thread FIFO nên thứ tự phụ đề trong cùng nguồn không bị đảo.
        self._work_queue = queue.Queue()
        self._xlate_queue = queue.Queue()
        self._stt_worker = None
        self._xlate_worker = None
        self._stop = threading.Event()

        self._load_config()

    def _load_config(self):
        cfg = config.load()
        self.target_lang = cfg.get("translate_target_lang", "en")
        self.source_lang = cfg.get("translate_source_lang", "auto")  # "auto" = detect
        self.google_api_key = (cfg.get("google_translate_api_key") or "").strip()
        # Nguồn nghe: "both" (mic+system) | "system" (chỉ tiếng máy, vd game) | "mic"
        self.audio_source = cfg.get("translate_audio_source", "both")

        # STT provider: dùng CHUNG provider/key mà SttEngine đang cấu hình
        # (đỡ phải nhập API key thêm lần nữa — user đã có key Groq/OpenAI để nói).
        self.provider_id = cfg.get("provider") or "groq"
        self.provider = stt_providers.get_provider(self.provider_id)
        self.stt_api_key = stt_providers.get_api_key(self.provider_id) \
            or cfg.get("groq_api_key", "")
        # Model STT RIÊNG cho translate mode: ưu tiên bản NHANH nhất để bớt độ trễ.
        # Dấu tiếng Việt kém không quan trọng khi mục tiêu là phụ đề dịch realtime.
        # translate_model chỉ dùng nếu HỢP LỆ với provider hiện tại (turbo là model
        # Groq, không phải OpenAI) — nếu không thì tự chọn bản nhanh của provider,
        # cuối cùng mới rơi về model push-to-talk / default_model.
        self.model = self._pick_translate_model(cfg)

    # Model STT nhanh nhất đã biết theo từng provider (dùng cho translate mode).
    _FAST_STT = {
        "groq": "whisper-large-v3-turbo",
        "openai": "gpt-4o-mini-transcribe",
    }

    def _pick_translate_model(self, cfg):
        """Chọn model STT cho translate mode, đảm bảo hợp lệ với provider hiện tại."""
        models = self.provider.get("models") or []
        tm = (cfg.get("translate_model") or "").strip()
        if tm and (not models or tm in models):
            return tm
        fast = self._FAST_STT.get(self.provider_id)
        if fast and fast in models:
            return fast
        return cfg.get("model") or self.provider["default_model"]

    # ----------------------- Vòng đời -----------------------
    def start(self):
        """Bật translate mode: capture audio (mic + system) + worker xử lý."""
        if self._running:
            return
        self._load_config()      # lấy cấu hình mới nhất (user có thể đổi trong Settings)
        self._running = True
        self._stop.clear()

        try:
            from translate_audio import TranslateAudioManager
            cap_mic = self.audio_source in ("both", "mic")
            cap_sys = self.audio_source in ("both", "system")
            self._audio_manager = TranslateAudioManager(
                self._on_audio_chunk, capture_mic=cap_mic, capture_system=cap_sys)
            self._audio_manager.start()
        except Exception as e:
            print(f"[TranslateEngine] audio manager lỗi: {e}", file=sys.stderr, flush=True)
            self.emit("translate_error", f"Không bật được thu âm: {e}")
            self._running = False
            return

        self._stt_worker = threading.Thread(target=self._stt_loop, daemon=True)
        self._stt_worker.start()
        self._xlate_worker = threading.Thread(target=self._xlate_loop, daemon=True)
        self._xlate_worker.start()
        self.emit("translate_state", "listening")
        print("[TranslateEngine] started", file=sys.stderr, flush=True)

    def is_running(self):
        """True nếu đang capture + worker xử lý audio."""
        return bool(self._running)

    def stop(self):
        """Dừng translate mode, giải phóng audio stream + worker thread."""
        if not self._running:
            return
        self._running = False
        self._stop.set()

        if self._audio_manager is not None:
            try:
                self._audio_manager.stop()
            except Exception as e:
                print(f"[TranslateEngine] stop audio lỗi: {e}", file=sys.stderr, flush=True)
            self._audio_manager = None

        if self._stt_worker is not None:
            self._stt_worker.join(timeout=3.0)
            self._stt_worker = None
        if self._xlate_worker is not None:
            self._xlate_worker.join(timeout=3.0)
            self._xlate_worker = None

        with self._work_queue.mutex:
            self._work_queue.queue.clear()
        with self._xlate_queue.mutex:
            self._xlate_queue.queue.clear()

        self.emit("translate_state", "idle")
        print("[TranslateEngine] stopped", file=sys.stderr, flush=True)

    def shutdown(self):
        self.stop()

    # ----------------------- Cấu hình -----------------------
    def set_target_lang(self, lang):
        """Đổi ngôn ngữ đích (en, vi, ja, zh-CN, ...)."""
        self.target_lang = lang
        cfg = config.load()
        cfg["translate_target_lang"] = lang
        config.save(cfg)

    def set_source_lang(self, lang):
        """Đổi ngôn ngữ nguồn ("auto" = tự nhận)."""
        self.source_lang = lang
        cfg = config.load()
        cfg["translate_source_lang"] = lang
        config.save(cfg)

    def set_audio_source(self, mode):
        """Đổi nguồn nghe: "both" | "system" | "mic". Đang chạy thì restart capture."""
        if mode not in ("both", "system", "mic"):
            return
        self.audio_source = mode
        cfg = config.load()
        cfg["translate_audio_source"] = mode
        config.save(cfg)
        if self._running:
            self.stop()
            self.start()

    def set_google_api_key(self, key):
        """Lưu Google Cloud Translation API key."""
        self.google_api_key = (key or "").strip()
        cfg = config.load()
        cfg["google_translate_api_key"] = self.google_api_key
        config.save(cfg)

    def test_google_key(self):
        """Ping thử Google Translate API. Trả (ok, msg)."""
        return google_translate.test_connection(self.google_api_key)

    # ----------------------- Internal -----------------------
    def _on_audio_chunk(self, source, audio):
        """Callback từ translate_audio khi VAD phát hiện hết 1 đoạn nói.

        Có giới hạn queue + rate-limit: nếu queue đầy thì BỎ QUA chunk mới (tránh
        native thread của PyAudioWPatch liên tục put() trên hàng đợi đầy làm
        tràn bộ nhớ / segfault trên Python 3.14 + Qt).
        """
        if not self._running:
            return
        try:
            # Drop nếu queue đã tồn đọng quá nhiều đoạn — worker không kịp xử lý.
            if self._work_queue.qsize() >= _MAX_QUEUE:
                return
            self._work_queue.put_nowait((source, audio))
        except queue.Full:
            return
        except Exception:
            return

    def _stt_loop(self):
        """Tầng 1: audio đã cắt đoạn -> STT -> đẩy text sang _xlate_queue.
        Tầng này chỉ làm STT nên đoạn N+1 được nhận diện CHỒNG lên lúc tầng dịch
        đang xử lý đoạn N (không còn chờ nhau tuần tự)."""
        while not self._stop.is_set():
            try:
                source, audio = self._work_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            try:
                text, lang = self._transcribe(audio)
            except Exception as e:
                print(f"[TranslateEngine] STT lỗi: {e}", file=sys.stderr, flush=True)
                self.emit("translate_error", f"STT lỗi ({source}): {e}")
                continue
            finally:
                del audio

            text = (text or "").strip()
            if not text:
                continue

            print(f"[TranslateEngine] {source}: {text!r} (lang={lang})",
                  file=sys.stderr, flush=True)

            # Chuyển sang tầng dịch (FIFO -> giữ đúng thứ tự trong cùng nguồn).
            try:
                self._xlate_queue.put_nowait((source, text, lang))
            except queue.Full:
                pass

    def _xlate_loop(self):
        """Tầng 2: text từ STT -> dịch Google -> emit về UI."""
        while not self._stop.is_set():
            try:
                source, text, lang = self._xlate_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            try:
                translated = self._translate_text(text, lang)
            except Exception as e:
                print(f"[TranslateEngine] translate lỗi: {e}", file=sys.stderr, flush=True)
                translated = text          # fallback: vẫn hiện bản gốc, không mất chữ

            self.emit("translate_result", {
                "source": source,
                "original": text,
                "translated": translated,
                "lang_detected": lang,
            })

    def _transcribe(self, audio):
        """Gọi STT qua providers.transcribe (dùng chung provider của SttEngine)."""
        if not self.stt_api_key:
            raise RuntimeError(f"Chưa có API key cho {self.provider['display_name']}")
        return stt_providers.transcribe(
            audio,
            provider=self.provider,
            api_key=self.stt_api_key,
            model=self.model,
            language="auto",
            prompt="",                     # không dùng prompt code-switch -> tránh leak
            timeout=60,
        )

    def _translate_text(self, text, detected_lang):
        """Dịch text qua Google Cloud Translation REST v2. Lỗi/thiếu key -> trả gốc."""
        if not self.google_api_key:
            return text
        # Đã đúng ngôn ngữ đích -> khỏi tốn quota dịch
        if detected_lang and self.target_lang \
                and detected_lang.lower().startswith(self.target_lang.lower()[:2]):
            return text
        out_text, _detected = google_translate.translate_text(
            text,
            api_key=self.google_api_key,
            target_lang=self.target_lang,
            source_lang=None if self.source_lang == "auto" else self.source_lang,
        )
        return out_text or text
