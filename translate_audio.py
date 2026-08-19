"""
WakerVoice — Thu âm liên tục cho Translate Mode
================================================
VAD đơn giản: phát hiện khi người nói ngừng (im lặng ~0.8s) -> cắt đoạn -> emit.
Hỗ trợ 2 nguồn:
  - Mic: sounddevice.InputStream (16kHz mono float32)
  - System audio: PyAudioWPatch WASAPI loopback (resample về 16kHz mono)

Không chạy STT/dịch ở đây — chỉ capture + VAD + emit chunks qua callback.
"""

import sys
import time
import queue
import threading
import numpy as np
import sounddevice as sd

try:
    import pyaudiowpatch as pyaudio
except ImportError:
    pyaudio = None

SAMPLE_RATE = 16000
CHANNELS = 1
CHUNK_MS = 100              # mỗi callback ~100ms
CHUNK_FRAMES = int(SAMPLE_RATE * CHUNK_MS / 1000)
SILENCE_THRESHOLD_RMS = 0.012   # dưới ngưỡng này = im lặng
SILENCE_DURATION_S = 0.5        # ngừng 0.5s -> cắt đoạn (giảm từ 0.8 để bớt độ trễ)
MIN_SPEECH_DURATION_S = 0.5     # đoạn ngắn hơn 0.5s = bỏ (tiếng hộ/tiếng động)
# Cắt mềm: audio liên tục (bình luận game, nhạc nền) hiếm khi im đủ ngưỡng ->
# đoạn phình dài rồi mới cắt = độ trễ khổng lồ. Ép flush mỗi ~3s để phụ đề chảy
# ra đều thay vì đợi một quãng lặng không bao giờ tới. Đổi tại đây để cân latency.
MAX_SPEECH_DURATION_S = 3.0


class AudioCaptureThread(threading.Thread):
    """Base class cho mic + system audio capture. Chạy liên tục khi start(), dừng khi stop()."""

    def __init__(self, source_name, callback):
        super().__init__(daemon=True)
        self.source_name = source_name  # "mic" | "system"
        self.callback = callback        # callback(source_name, audio_float32) khi phát hiện đoạn nói
        self._stop = threading.Event()
        self._buffer = []               # list of float32 arrays
        self._silence_start = None      # thời điểm bắt đầu im lặng
        self._last_rms = 0.0

    def stop(self):
        """Dừng thread capture."""
        self._stop.set()

    def _process_chunk(self, chunk):
        """Xử lý chunk audio (float32 mono). Triển khai VAD đơn giản."""
        rms = float(np.sqrt(np.mean(chunk ** 2)))
        self._last_rms = rms

        is_silence = rms < SILENCE_THRESHOLD_RMS
        now = time.monotonic()

        if is_silence:
            if self._silence_start is None:
                self._silence_start = now
            silence_dur = now - self._silence_start

            # Im lặng đủ lâu -> cắt đoạn nếu có
            if silence_dur >= SILENCE_DURATION_S and self._buffer:
                audio = np.concatenate(self._buffer, axis=0).flatten().astype(np.float32)
                dur = audio.shape[0] / SAMPLE_RATE
                # Loại đoạn quá ngắn (tiếng động nhỏ)
                if dur >= MIN_SPEECH_DURATION_S:
                    # Kiểm tra peak/rms tổng đoạn (tránh đoạn im lặng hoàn toàn)
                    peak = float(np.max(np.abs(audio)))
                    avg_rms = float(np.sqrt(np.mean(audio ** 2)))
                    if peak >= 0.02 and avg_rms >= 0.008:
                        try:
                            self.callback(self.source_name, audio)
                        except Exception as e:
                            print(f"[{self.source_name}] callback lỗi: {e}", file=sys.stderr, flush=True)
                self._buffer = []
                self._silence_start = None
        else:
            # Có tiếng -> reset silence timer, append chunk
            self._silence_start = None
            self._buffer.append(chunk.copy())
            # Cắt mềm sau MAX_SPEECH_DURATION_S: audio liên tục không có quãng lặng
            # thì vẫn flush đều để phụ đề chảy ra (không đợi tới lúc im).
            total_frames = sum(c.shape[0] for c in self._buffer)
            if total_frames > SAMPLE_RATE * MAX_SPEECH_DURATION_S:
                # Cắt đoạn hiện tại ra
                audio = np.concatenate(self._buffer, axis=0).flatten().astype(np.float32)
                dur = audio.shape[0] / SAMPLE_RATE
                if dur >= MIN_SPEECH_DURATION_S:
                    peak = float(np.max(np.abs(audio)))
                    avg_rms = float(np.sqrt(np.mean(audio ** 2)))
                    if peak >= 0.02 and avg_rms >= 0.008:
                        try:
                            self.callback(self.source_name, audio)
                        except Exception as e:
                            print(f"[{self.source_name}] callback lỗi: {e}", file=sys.stderr, flush=True)
                self._buffer = []


class MicCapture(AudioCaptureThread):
    """Capture mic qua sounddevice (giống engine.py hiện có)."""

    def __init__(self, callback):
        super().__init__("mic", callback)
        self.audio_queue = queue.Queue()
        self.stream = None

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            print(f"[mic] {status}", file=sys.stderr, flush=True)
        self.audio_queue.put(indata.copy())

    def run(self):
        """Mở stream liên tục, đọc từ queue, xử lý VAD."""
        try:
            self.stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype="float32",
                latency="low",
                callback=self._audio_callback,
            )
            self.stream.start()
            print(f"[mic] started", file=sys.stderr, flush=True)

            while not self._stop.is_set():
                try:
                    chunk = self.audio_queue.get(timeout=0.2)
                    self._process_chunk(chunk.flatten())
                except queue.Empty:
                    continue
        except Exception as e:
            print(f"[mic] lỗi: {e}", file=sys.stderr, flush=True)
        finally:
            if self.stream is not None:
                try:
                    self.stream.stop()
                    self.stream.close()
                except Exception:
                    pass
            print(f"[mic] stopped", file=sys.stderr, flush=True)


class SystemAudioCapture(AudioCaptureThread):
    """Capture system audio qua PyAudioWPatch WASAPI loopback."""

    def __init__(self, callback):
        super().__init__("system", callback)

    def run(self):
        """Mở WASAPI loopback, resample về 16kHz mono, xử lý VAD."""
        if pyaudio is None:
            print("[system] PyAudioWPatch chưa cài — bỏ qua system audio", file=sys.stderr, flush=True)
            return

        p = None
        stream = None
        try:
            p = pyaudio.PyAudio()
            # Tìm WASAPI loopback device (default loopback)
            wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
            default_speakers = p.get_device_info_by_index(wasapi_info["defaultOutputDevice"])

            if not default_speakers["isLoopbackDevice"]:
                # Windows 10+: loopback device có flag riêng
                for i in range(p.get_device_count()):
                    dev = p.get_device_info_by_index(i)
                    if dev["hostApi"] == wasapi_info["index"] and dev.get("isLoopbackDevice"):
                        default_speakers = dev
                        break

            # Mở stream loopback
            channels_sys = int(default_speakers["maxInputChannels"])
            rate_sys = int(default_speakers["defaultSampleRate"])
            print(f"[system] loopback: {rate_sys}Hz {channels_sys}ch", file=sys.stderr, flush=True)

            stream = p.open(
                format=pyaudio.paInt16,
                channels=channels_sys,
                rate=rate_sys,
                input=True,
                frames_per_buffer=CHUNK_FRAMES,
                input_device_index=default_speakers["index"],
            )

            print(f"[system] started", file=sys.stderr, flush=True)

            while not self._stop.is_set():
                try:
                    raw = stream.read(CHUNK_FRAMES, exception_on_overflow=False)
                    # int16 -> float32
                    pcm16 = np.frombuffer(raw, dtype=np.int16)
                    pcm_float = pcm16.astype(np.float32) / 32768.0

                    # Downmix về mono nếu stereo
                    if channels_sys == 2:
                        pcm_float = pcm_float.reshape(-1, 2).mean(axis=1)
                    elif channels_sys > 2:
                        pcm_float = pcm_float.reshape(-1, channels_sys).mean(axis=1)

                    # Resample về 16kHz nếu khác (giả sử rate_sys = 48kHz hoặc 44.1kHz)
                    if rate_sys != SAMPLE_RATE:
                        pcm_float = self._resample_simple(pcm_float, rate_sys, SAMPLE_RATE)

                    self._process_chunk(pcm_float)
                except Exception as e:
                    if not self._stop.is_set():
                        print(f"[system] read lỗi: {e}", file=sys.stderr, flush=True)
                    break
        except Exception as e:
            print(f"[system] lỗi: {e}", file=sys.stderr, flush=True)
        finally:
            if stream is not None:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:
                    pass
            if p is not None:
                try:
                    p.terminate()
                except Exception:
                    pass
            print(f"[system] stopped", file=sys.stderr, flush=True)

    def _resample_simple(self, audio, src_rate, dst_rate):
        """Resample đơn giản (linear interpolation) từ src_rate -> dst_rate."""
        if src_rate == dst_rate:
            return audio
        ratio = dst_rate / src_rate
        new_len = int(len(audio) * ratio)
        indices = np.linspace(0, len(audio) - 1, new_len)
        return np.interp(indices, np.arange(len(audio)), audio).astype(np.float32)


# ----------------------- API cao cấp -----------------------
class TranslateAudioManager:
    """Quản lý mic + system audio capture cùng lúc. start()/stop() đơn giản."""

    def __init__(self, callback, capture_mic=True, capture_system=True):
        """callback(source, audio_float32) được gọi khi phát hiện đoạn nói.

        capture_mic / capture_system: bật/tắt từng nguồn. Dịch game thường chỉ
        cần system audio (bỏ mic để khỏi lẫn giọng mình / tiếng phòng)."""
        self.callback = callback
        self.capture_mic = bool(capture_mic)
        self.capture_system = bool(capture_system)
        self.mic_thread = None
        self.system_thread = None

    def start(self):
        """Bật các nguồn audio đã chọn (mic và/hoặc system)."""
        if self.mic_thread is not None or self.system_thread is not None:
            return  # đã chạy
        if self.capture_mic:
            self.mic_thread = MicCapture(self.callback)
            self.mic_thread.start()
        if self.capture_system:
            self.system_thread = SystemAudioCapture(self.callback)
            self.system_thread.start()
        print(f"[TranslateAudio] started mic={self.capture_mic} "
              f"system={self.capture_system}", file=sys.stderr, flush=True)

    def stop(self):
        """Dừng cả mic và system audio capture."""
        if self.mic_thread is not None:
            self.mic_thread.stop()
            self.mic_thread.join(timeout=2.0)
            self.mic_thread = None
        if self.system_thread is not None:
            self.system_thread.stop()
            self.system_thread.join(timeout=2.0)
            self.system_thread = None
        print("[TranslateAudio] stopped", file=sys.stderr, flush=True)
