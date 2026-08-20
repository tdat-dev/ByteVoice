"""
Test độc lập: streaming Deepgram từ system-audio (hoặc mic) — đo độ trễ + chất
lượng tiếng Việt TRƯỚC khi ráp vào app.

Chạy (PowerShell, trong thư mục WakerVoice):
    .venv\\Scripts\\python.exe tools\\test_deepgram.py <DEEPGRAM_KEY> [giây] [system|mic] [lang]

Ví dụ (nghe loa máy tính, 40s, tiếng Việt):
    .venv\\Scripts\\python.exe tools\\test_deepgram.py dg_xxx 40 system vi

Mở sẵn video/nhạc tiếng Việt rồi chạy. Script in:
    [   1.8s] ~ (tạm) transcript đang chảy...
    [   2.1s] ==> (chốt) câu đã hoàn chỉnh.
Nhìn mốc giây để thấy chữ ra nhanh cỡ nào so với ~3s hiện tại.
"""

import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np
import deepgram_stream as dg

SAMPLE_RATE = 16000


def _resample(audio, src, dst):
    if src == dst:
        return audio
    n = int(len(audio) * dst / src)
    idx = np.linspace(0, len(audio) - 1, n)
    return np.interp(idx, np.arange(len(audio)), audio).astype(np.float32)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    key = sys.argv[1]
    seconds = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    source = sys.argv[3] if len(sys.argv) > 3 else "system"
    lang = sys.argv[4] if len(sys.argv) > 4 else "vi"

    ok, msg = dg.test_connection(key, language=lang)
    print(f"[ping] {msg}")
    if not ok:
        return

    t0 = time.monotonic()

    def stamp():
        return f"[{time.monotonic() - t0:6.1f}s]"

    stream = dg.DeepgramStream(
        key, language=lang,
        on_interim=lambda t: print(f"{stamp()}  ~   {t}"),
        on_final=lambda t: print(f"{stamp()}  ==> {t}"),
        on_error=lambda m: print(f"{stamp()}  [ERR] {m}"),
    )
    if not stream.start():
        return
    print(f"[cfg] nghe '{source}' {seconds}s, lang={lang}. Hãy phát tiếng ngay bây giờ…")

    try:
        if source == "mic":
            _run_mic(stream, seconds)
        else:
            _run_system(stream, seconds)
    finally:
        time.sleep(1.0)          # chờ nốt transcript cuối
        stream.stop()
        print("[done]")


def _run_mic(stream, seconds):
    import sounddevice as sd
    end = time.monotonic() + seconds

    def cb(indata, frames, tinfo, status):
        stream.feed_float32(indata[:, 0].copy())

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                        latency="low", callback=cb):
        while time.monotonic() < end:
            time.sleep(0.1)


def _run_system(stream, seconds):
    import pyaudiowpatch as pyaudio
    p = pyaudio.PyAudio()
    wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
    spk = p.get_device_info_by_index(wasapi["defaultOutputDevice"])
    if not spk.get("isLoopbackDevice"):
        for i in range(p.get_device_count()):
            d = p.get_device_info_by_index(i)
            if d["hostApi"] == wasapi["index"] and d.get("isLoopbackDevice"):
                spk = d
                break
    ch = int(spk["maxInputChannels"])
    rate = int(spk["defaultSampleRate"])
    frames = int(rate * 0.1)
    print(f"[sys] loopback {rate}Hz {ch}ch")
    st = p.open(format=pyaudio.paInt16, channels=ch, rate=rate, input=True,
                frames_per_buffer=frames, input_device_index=spk["index"])
    end = time.monotonic() + seconds
    try:
        while time.monotonic() < end:
            raw = st.read(frames, exception_on_overflow=False)
            pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            if ch > 1:
                pcm = pcm.reshape(-1, ch).mean(axis=1)
            pcm = _resample(pcm, rate, SAMPLE_RATE)
            stream.feed_float32(pcm)
    finally:
        st.stop_stream()
        st.close()
        p.terminate()


if __name__ == "__main__":
    main()
