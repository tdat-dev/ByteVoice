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

try:
    import numpy as np
except Exception:
    np = None

import config
import providers as stt_providers
import google_translate
import text_filters


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
        self._dg_streams = {}          # {source: DeepgramStream} — chế độ streaming
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

        # Chế độ STT: "batch" (Groq gửi cả cụm) | "streaming" (Deepgram WebSocket ~0.3s)
        self.stt_mode = cfg.get("translate_stt_mode", "batch")
        self.deepgram_api_key = (cfg.get("deepgram_api_key") or "").strip()

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

        streaming = (self.stt_mode == "streaming" and bool(self.deepgram_api_key))
        cap_mic = self.audio_source in ("both", "mic")
        cap_sys = self.audio_source in ("both", "system")

        if streaming and not self._start_deepgram(cap_mic, cap_sys):
            # Không mở được Deepgram -> rơi về batch để không mất tính năng
            streaming = False

        try:
            from translate_audio import TranslateAudioManager
            raw_sink = self._dg_raw_sink if streaming else None
            self._audio_manager = TranslateAudioManager(
                self._on_audio_chunk, capture_mic=cap_mic, capture_system=cap_sys,
                raw_sink=raw_sink)
            self._audio_manager.start()
        except Exception as e:
            print(f"[TranslateEngine] audio manager lỗi: {e}", file=sys.stderr, flush=True)
            self.emit("translate_error", f"Không bật được thu âm: {e}")
            self._stop_deepgram()
            self._running = False
            return

        # Tầng dịch luôn chạy (batch dùng cả STT+dịch; streaming chỉ dùng dịch).
        if not streaming:
            self._stt_worker = threading.Thread(target=self._stt_loop, daemon=True)
            self._stt_worker.start()
        self._xlate_worker = threading.Thread(target=self._xlate_loop, daemon=True)
        self._xlate_worker.start()
        self.emit("translate_state", "listening")
        print(f"[TranslateEngine] started mode={'streaming' if streaming else 'batch'}",
              file=sys.stderr, flush=True)

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

        # Đóng các kết nối Deepgram (chế độ streaming)
        self._stop_deepgram()

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
        """Đổi ngôn ngữ nguồn ("auto" = tự nhận). Batch đọc live; streaming cần
        restart vì Deepgram khoá ngôn ngữ lúc bắt tay kết nối."""
        self.source_lang = lang
        cfg = config.load()
        cfg["translate_source_lang"] = lang
        config.save(cfg)
        if self._running and self.stt_mode == "streaming":
            self.stop()
            self.start()

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

    def set_stt_mode(self, mode):
        """Đổi chế độ STT: "batch" (Groq) | "streaming" (Deepgram). Restart nếu đang chạy."""
        if mode not in ("batch", "streaming"):
            return
        self.stt_mode = mode
        cfg = config.load()
        cfg["translate_stt_mode"] = mode
        config.save(cfg)
        if self._running:
            self.stop()
            self.start()

    def set_deepgram_api_key(self, key):
        """Lưu Deepgram API key. Restart nếu đang chạy streaming để áp key mới."""
        self.deepgram_api_key = (key or "").strip()
        cfg = config.load()
        cfg["deepgram_api_key"] = self.deepgram_api_key
        config.save(cfg)
        if self._running and self.stt_mode == "streaming":
            self.stop()
            self.start()

    def test_deepgram_key(self):
        """Ping thử Deepgram. Trả (ok, msg)."""
        try:
            import deepgram_stream as dg
        except Exception as e:
            return False, f"Không nạp được Deepgram: {e}"
        return dg.test_connection(self.deepgram_api_key, language=self._dg_language())

    # ------------------- Streaming (Deepgram) -------------------
    def _dg_language(self):
        """Ngôn ngữ đưa cho Deepgram: ISO ngắn, "auto" -> "multi" (nova-3 đa ngữ)."""
        lang = (self.source_lang or "auto").strip()
        if lang == "auto":
            return "multi"
        return lang.split("-")[0].lower()

    def _start_deepgram(self, cap_mic, cap_sys):
        """Mở kết nối Deepgram cho mỗi nguồn đang bật. Trả True nếu có ít nhất 1 OK."""
        try:
            import deepgram_stream as dg
        except Exception as e:
            self.emit("translate_error", f"Không nạp được Deepgram: {e}")
            return False
        lang = self._dg_language()
        sources = ([s for s, on in (("mic", cap_mic), ("system", cap_sys)) if on])
        ok_any = False
        for src in sources:
            stream = dg.DeepgramStream(
                self.deepgram_api_key, language=lang,
                on_interim=(lambda t, s=src: self._on_dg_interim(s, t)),
                on_final=(lambda t, s=src: self._on_dg_final(s, t)),
                on_error=(lambda m, s=src: self._on_dg_error(s, m)),
            )
            if stream.start():
                self._dg_streams[src] = stream
                ok_any = True
        if not ok_any:
            self.emit("translate_error",
                      "Không kết nối được Deepgram — kiểm tra API key ở tab Dịch nhanh")
        return ok_any

    def _stop_deepgram(self):
        for stream in list(self._dg_streams.values()):
            try:
                stream.stop()
            except Exception:
                pass
        self._dg_streams = {}

    def _dg_raw_sink(self, source, frame):
        """Nhận frame audio liên tục -> đẩy vào kết nối Deepgram của đúng nguồn."""
        stream = self._dg_streams.get(source)
        if stream is not None:
            stream.feed_float32(frame)
            # Log mức âm lượng định kỳ để chẩn đoán: audio có TỚI Deepgram không
            # (peak≈0 = không có tiếng / sai thiết bị; peak>0 = có tiếng, im lời = do nhạc).
            self._lvl_n = getattr(self, "_lvl_n", 0) + 1
            self._lvl_peak = max(getattr(self, "_lvl_peak", 0.0), float(np.max(np.abs(frame))) if np is not None and frame is not None and len(frame) else 0.0)
            if self._lvl_n >= 100:      # ~ mỗi vài giây
                print(f"[audio-lvl] {source} peak={self._lvl_peak:.4f} (100 frame)",
                      file=sys.stderr, flush=True)
                # Báo UI mức âm lượng -> placeholder biết "có tiếng nhưng chưa ra lời"
                self.emit("translate_audio_level", {"peak": self._lvl_peak})
                self._lvl_n = 0
                self._lvl_peak = 0.0

    def _on_dg_interim(self, source, text):
        """Kết quả TẠM từ Deepgram -> hiện bản gốc chảy realtime (chưa dịch)."""
        if not self._running:
            return
        text = (text or "").strip()
        print(f"[dg-interim] {source}: {text!r}", file=sys.stderr, flush=True)
        self.emit("translate_interim", {"source": source, "text": text})

    def _on_dg_final(self, source, text):
        """Đoạn đã CHỐT -> lọc ảo giác rồi đưa sang tầng dịch (kèm cờ streaming)."""
        if not self._running:
            return
        text = (text or "").strip()
        print(f"[dg-final] {source}: {text!r}", file=sys.stderr, flush=True)
        if not text or text_filters.is_hallucination(text):
            return
        lang = self.source_lang if self.source_lang and self.source_lang != "auto" else ""
        try:
            self._xlate_queue.put_nowait((source, text, lang, True))
        except queue.Full:
            pass

    def _on_dg_error(self, source, msg):
        print(f"[TranslateEngine] Deepgram({source}) lỗi: {msg}", file=sys.stderr, flush=True)
        self.emit("translate_error", f"Deepgram ({source}): {msg}")

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

            # Chặn ẢO GIÁC Whisper (Ghiền Mì Gõ / subscribe...) — hay phọt ra khi
            # gặp nhạc/hát/khoảng lặng, không phải lời thật -> bỏ, khỏi dịch/hiện.
            if text_filters.is_hallucination(text):
                print(f"[TranslateEngine] {source}: BỎ ảo giác {text!r}",
                      file=sys.stderr, flush=True)
                continue

            print(f"[TranslateEngine] {source}: {text!r} (lang={lang})",
                  file=sys.stderr, flush=True)

            # Chuyển sang tầng dịch (FIFO -> giữ đúng thứ tự trong cùng nguồn).
            # cờ is_stream=False: đây là kết quả batch (dòng mới trên overlay).
            try:
                self._xlate_queue.put_nowait((source, text, lang, False))
            except queue.Full:
                pass

    def _xlate_loop(self):
        """Tầng 2: text (từ STT batch HOẶC Deepgram final) -> dịch -> emit về UI."""
        while not self._stop.is_set():
            try:
                item = self._xlate_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            # Tương thích tuple 3 (cũ) lẫn 4 (kèm cờ streaming).
            if len(item) == 4:
                source, text, lang, is_stream = item
            else:
                source, text, lang = item
                is_stream = False

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
                # final_stream=True -> đây là bản CHỐT của dòng đang chảy (streaming),
                # overlay finalize dòng interim thay vì thêm dòng mới.
                "final_stream": is_stream,
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
            # KHOÁ ngôn ngữ theo lựa chọn của user thay vì luôn "auto": auto-detect
            # trên nhạc/hát hay đoán bừa sang Hàn/Trung. Chọn "Tiếng Việt" -> Whisper
            # bị ép nghe tiếng Việt, hết nhận nhầm. Whisper cần ISO ngắn (zh-CN -> zh).
            language=self._stt_language(),
            prompt="",                     # không dùng prompt code-switch -> tránh leak
            timeout=60,
        )

    def _stt_language(self):
        """Mã ngôn ngữ đưa cho Whisper: 'auto' hoặc ISO ngắn (vi/en/ja/ko/zh...)."""
        lang = (self.source_lang or "auto").strip()
        if lang == "auto":
            return "auto"
        return lang.split("-")[0].lower()      # "zh-CN" -> "zh"

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
