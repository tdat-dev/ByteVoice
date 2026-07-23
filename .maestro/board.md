# Board

## To do (0)

_(empty)_

## Doing (0)

_(empty)_

## Done (1)

- [x] Fix WakerVoice: prompt leak + hotkey chết sau idle
  3 bug: (1) hotkey/STT chết khi máy idle lâu hoặc overlay đè — pynput listener không restart; (2) Whisper prompt code-switch rò vào output (câu về VI chêm EN); (3) ảo giác từ. Sửa trong engine.py.
  - [ ] Rewrite Whisper prompt + strip prompt leak
  - [ ] Watchdog restart keyboard listener + audio retry
  - [ ] Mở rộng lọc ảo giác / vocab dump
  - [ ] Smoke-check logic bằng unit-style asserts

## Proposed (0)

_(empty)_
