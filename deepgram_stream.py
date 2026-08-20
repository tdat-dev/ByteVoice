"""
WakerVoice — Deepgram streaming STT (realtime WebSocket)
========================================================
Streaming ASR: đẩy PCM 16-bit liên tục lên Deepgram qua WebSocket, nhận transcript
TỪNG PHẦN (~200-300ms) trong lúc đang nói -> độ trễ thấp hơn hẳn kiểu batch (gửi
cả cụm rồi chờ). Dùng cho "dịch nhanh" khi user muốn phụ đề chảy realtime.

Nova-3 hỗ trợ tiếng Việt (kể cả thanh điệu). Model batch (Groq) vẫn giữ song song
cho ai không có key Deepgram.

Callback:
    on_interim(text)         # kết quả tạm (is_final=False) — cập nhật dòng đang chạy
    on_final(text)           # đoạn đã chốt (speech_final=True) — dịch + xuống dòng
    on_error(msg)            # lỗi kết nối/parse

Tách rời hẳn: KHÔNG import Qt, KHÔNG đụng config. Thuần audio bytes vào -> text ra.
"""

import sys
import json
import time
import queue
import threading

try:
    import websocket            # websocket-client (sync)
except ImportError:             # pragma: no cover
    websocket = None

try:
    import numpy as np
except Exception:               # pragma: no cover
    np = None

DG_WS_URL = "wss://api.deepgram.com/v1/listen"


def float32_to_pcm16_bytes(audio):
    """float32 [-1,1] -> bytes PCM 16-bit little-endian (định dạng linear16 Deepgram)."""
    if np is None:
        raise RuntimeError("numpy chưa sẵn sàng")
    clipped = np.clip(audio, -1.0, 1.0)
    return (clipped * 32767.0).astype("<i2").tobytes()


class DeepgramStream:
    """Một kết nối streaming Deepgram (một nguồn audio, một ngôn ngữ)."""

    def __init__(self, api_key, *, language="vi", model="nova-3",
                 sample_rate=16000, on_interim=None, on_final=None, on_error=None):
        self.api_key = (api_key or "").strip()
        self.language = language or "vi"
        self.model = model or "nova-3"
        self.sample_rate = int(sample_rate)
        self.on_interim = on_interim or (lambda t: None)
        self.on_final = on_final or (lambda t: None)
        self.on_error = on_error or (lambda m: None)

        self._ws = None
        self._send_q = queue.Queue()
        self._stop = threading.Event()
        self._threads = []
        self._last_send = 0.0
        self._running = False

    # ----------------------- URL -----------------------
    def _url(self):
        # interim_results=true -> nhận kết quả tạm; endpointing=300ms -> chốt câu
        # nhanh; smart_format+punctuate -> có dấu câu/viết hoa.
        p = (
            f"?model={self.model}&language={self.language}"
            f"&encoding=linear16&sample_rate={self.sample_rate}&channels=1"
            "&interim_results=true&punctuate=true&smart_format=true"
            # endpointing thấp -> câu CHỐT (bản dịch) đến nhanh hơn (bớt cảm giác ỳ).
            # 150ms đủ để không cắt vụn giữa câu mà vẫn nhạy.
            "&endpointing=150"
        )
        return DG_WS_URL + p

    # ----------------------- Vòng đời -----------------------
    def start(self):
        if websocket is None:
            self.on_error("Chưa cài websocket-client")
            return False
        if not self.api_key:
            self.on_error("Chưa có Deepgram API key")
            return False
        try:
            self._ws = websocket.create_connection(
                self._url(),
                header=[f"Authorization: Token {self.api_key}"],
                timeout=10,                 # chỉ áp cho lúc BẮT TAY kết nối
                enable_multithread=True,
            )
            # Sau khi kết nối: recv BLOCKING (timeout=None). Nếu để timeout ngắn thì
            # lúc im lặng (Deepgram không gửi gì) recv() sẽ tự văng "timed out" và
            # giết stream. Blocking + dựa vào close() để thoát khi stop().
            self._ws.settimeout(None)
        except Exception as e:
            self.on_error(f"Không kết nối được Deepgram: {e}")
            return False

        self._stop.clear()
        self._running = True
        self._last_send = time.monotonic()
        self._threads = [
            threading.Thread(target=self._send_loop, daemon=True),
            threading.Thread(target=self._recv_loop, daemon=True),
            threading.Thread(target=self._keepalive_loop, daemon=True),
        ]
        for t in self._threads:
            t.start()
        print(f"[deepgram] connected lang={self.language} model={self.model}",
              file=sys.stderr, flush=True)
        return True

    def is_running(self):
        return self._running

    def feed(self, pcm16_bytes):
        """Đẩy 1 khối audio (bytes PCM16) vào hàng đợi gửi. Bỏ nếu chưa chạy."""
        if not self._running or not pcm16_bytes:
            return
        try:
            self._send_q.put_nowait(pcm16_bytes)
        except Exception:
            pass

    def feed_float32(self, audio):
        """Tiện ích: đẩy trực tiếp float32 (tự đổi sang PCM16)."""
        try:
            self.feed(float32_to_pcm16_bytes(audio))
        except Exception:
            pass

    def stop(self):
        if not self._running:
            return
        self._running = False
        self._stop.set()
        # Báo Deepgram flush nốt rồi đóng
        try:
            if self._ws is not None:
                self._ws.send(json.dumps({"type": "CloseStream"}))
        except Exception:
            pass
        try:
            if self._ws is not None:
                self._ws.close()
        except Exception:
            pass
        self._ws = None
        for t in self._threads:
            t.join(timeout=1.5)
        self._threads = []
        print("[deepgram] stopped", file=sys.stderr, flush=True)

    # ----------------------- Loops -----------------------
    def _send_loop(self):
        while not self._stop.is_set():
            try:
                data = self._send_q.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self._ws.send_binary(data)
                self._last_send = time.monotonic()
            except Exception as e:
                if not self._stop.is_set():
                    self.on_error(f"Deepgram gửi lỗi: {e}")
                    self._running = False
                break

    def _recv_loop(self):
        _Timeout = getattr(websocket, "WebSocketTimeoutException", None)
        while not self._stop.is_set():
            try:
                raw = self._ws.recv()
            except Exception as e:
                # Timeout khi im lặng = KHÔNG chết, chờ tiếp.
                if _Timeout is not None and isinstance(e, _Timeout):
                    continue
                if not self._stop.is_set():
                    self.on_error(f"Deepgram nhận lỗi: {e}")
                    self._running = False
                break
            if not raw:
                continue
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            if msg.get("type") != "Results":
                continue
            try:
                alt = msg["channel"]["alternatives"][0]
                text = (alt.get("transcript") or "").strip()
            except Exception:
                continue
            if not text:
                continue
            # is_final: đoạn ổn định; speech_final: hết câu (im lặng/endpoint)
            if msg.get("speech_final") or msg.get("is_final"):
                self.on_final(text)
            else:
                self.on_interim(text)

    def _keepalive_loop(self):
        # Nếu >5s không gửi audio (im lặng), gửi KeepAlive để Deepgram không đóng.
        while not self._stop.is_set():
            self._stop.wait(3.0)
            if self._stop.is_set():
                break
            if time.monotonic() - self._last_send > 5.0:
                try:
                    self._ws.send(json.dumps({"type": "KeepAlive"}))
                    self._last_send = time.monotonic()
                except Exception:
                    break


def test_connection(api_key, language="vi", timeout=8):
    """Ping thử: mở kết nối rồi đóng ngay. Trả (ok, msg)."""
    if websocket is None:
        return False, "Chưa cài websocket-client"
    if not (api_key or "").strip():
        return False, "Chưa có API key"
    try:
        ws = websocket.create_connection(
            DG_WS_URL + f"?model=nova-3&language={language}&encoding=linear16"
            "&sample_rate=16000&channels=1",
            header=[f"Authorization: Token {api_key.strip()}"],
            timeout=timeout,
        )
        ws.send(json.dumps({"type": "CloseStream"}))
        ws.close()
        return True, "OK · kết nối Deepgram thành công"
    except Exception as e:
        return False, f"Lỗi: {e}"
