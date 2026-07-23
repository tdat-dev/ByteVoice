# WakerVoice

**Push-to-Talk Speech-to-Text** chạy hoàn toàn trên cloud (Groq / OpenAI / custom).
Giữ một phím tắt toàn cục, nói, nhả phím — chữ tiếng Việt tự chèn vào nơi
con trỏ đang đứng.

> Phiên bản hiện tại: **v1.4.0** — lịch sử chép, snippets text-expansion,
> multi-provider (Groq/OpenAI/custom), Settings dialog tổng hợp.

> Tên *WakerVoice* lấy từ **sotto voce** (nói rất khẽ) — đúng tinh thần "nói thầm ra chữ".

Giao diện là một **pill** nổi, siêu nhẹ, vẽ bằng Qt (PySide6 / QPainter). Backend
STT qua **multi-provider cloud API** (không cần GPU/model cục bộ).

Mã nguồn: https://github.com/tdat-dev/ByteVoice
Tải bản mới nhất: https://github.com/tdat-dev/ByteVoice/releases/latest

## Tính năng

- **Cloud multi-provider** — Groq (mặc định, miễn phí nhanh), OpenAI
  (`gpt-4o-transcribe`), hoặc bất kỳ endpoint OpenAI-compatible nào (Together,
  Fireworks, self-hosted). Đổi trong menu khay hoặc **Cài đặt…**.
- **Gõ tại con trỏ** hoặc **Clipboard**.
- **Lịch sử chép** — mỗi lần chép được lưu JSONL; menu "Lịch sử" cho phép
  gõ lại / copy lại 20 bản gần nhất.
- **Snippets / text-expansion** — đặt trigger `@@date` → ngày hiện tại, `@@sign`
  → chữ ký mặc định. Editor trong menu "Snippets · text-expansion…".
- **Icon theo app đang focus** — pill tự nhận diện ứng dụng bạn đang gõ vào
  (Chrome, VS Code, Word…) và hiển thị icon của app đó thay cho mic. Khi đang
  dịch sẽ hiện spinner; không lấy được icon thì fallback về mic.
- **Tự cập nhật (delta)** — app kiểm tra GitHub lúc khởi động; có bản mới thì hỏi
  rồi chỉ tải **các file đã đổi** (đổi code ≈ vài chục MB thay vì cả gói), tự thay
  và khởi động lại. Cũng có menu tray "Kiểm tra cập nhật".

## Cài đặt

```bash
pip install -r requirements.txt
```

## Chạy

```bash
python app_qt.py
```

Trên Windows, để chèn chữ được vào mọi ứng dụng (kể cả app chạy quyền admin),
nên mở terminal **bằng quyền Administrator**.

## Dùng

1. Giữ **Right Alt** (đổi được trong **Cài đặt…** → tab Phím tắt) → pill chuyển
   vàng, sóng nở theo âm lượng thật khi bạn nói.
2. Nhả phím → spinner quay (đang dịch) → chữ tự chèn tại con trỏ.
3. Click trái lên pill (hoặc icon tray) để bật/tắt nói; kéo để di chuyển pill.
4. Menu tray → **Cài đặt…** để đổi provider, nhập API key, chỉnh snippets.

## Đóng gói (.exe)

```bash
pip install pyinstaller
pyinstaller WakerVoice.spec
```

Kết quả ở `dist/WakerVoice/WakerVoice.exe`. Icon lấy từ `icon.ico`.

## Cấu trúc

```
wakervoice/
├── app_qt.py          # pill Qt (PySide6) + tray + menu lịch sử + snippets editor
├── engine.py          # STT engine: hotkey, thu âm RAM, refine, snippets, history
├── config.py          # config.json (multi-provider) — KHÔNG lọc key
├── history.py         # JSONL append-only
├── snippets.py        # text-expansion với placeholder runtime
├── providers.py       # Groq / OpenAI / OpenAI-compatible
├── settings_ui.py     # QDialog cài đặt tổng hợp (5 tab)
├── icon.svg / icon.ico / icon.png
├── WakerVoice.spec        # cấu hình PyInstaller
├── requirements.txt
└── tests/                 # unit + e2e (không cần mạng)
```

## Tuỳ chỉnh nhanh

- **Provider & model**: Groq / OpenAI / Custom — menu "Nhà cung cấp STT" và
  "Chất lượng nhận dạng".
- **Phím tắt**: Right/Left Alt, Right Ctrl, F8, F9, Pause — **Cài đặt…** → Phím tắt.

## Bản quyền

Phát hành theo giấy phép [MIT](LICENSE) © 2026 tdat-dev.
