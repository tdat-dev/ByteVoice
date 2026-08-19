"""
WakerVoice — bộ lọc ảo giác Whisper (dùng chung: push-to-talk + dịch realtime)
==============================================================================
Whisper được train trên rất nhiều audio + phụ đề YouTube. Khi gặp NHẠC/hát/khoảng
lặng (không có lời nói rõ) nó không có gì thật để chép -> rơi về "câu phụ đề hay
gặp nhất" đã học = mấy câu outro kênh Việt (Ghiền Mì Gõ, subscribe, đăng ký kênh...)
hoặc bản EN ("thanks for watching"). Đây là ẢO GIÁC, phải chặn trước khi hiện/dịch.
"""

# Câu outro/CTA mà Whisper hay "bịa" khi gặp nhạc hoặc tiếng video lọt mic.
HALLUCINATION_PHRASES = (
    "ghiền mì gõ", "ghien mi go",
    "đăng ký kênh", "dang ky kenh",
    "subscribe", "sub cho kênh", "subcribe",
    "ủng hộ kênh", "like và đăng ký", "nhấn chuông", "bấm chuông",
    "cảm ơn các bạn đã theo dõi", "cảm ơn các bạn đã lắng nghe",
    "cảm ơn đã xem", "cảm ơn các bạn đã xem",
    "hẹn gặp lại", "đừng quên",
    "để không bỏ lỡ những video", "những video hấp dẫn",
    "thanks for watching", "please subscribe", "see you in the next video",
    "like and subscribe",
)


def is_hallucination(text, max_len=120):
    """True nếu text chỉ là câu outro/CTA quen thuộc (ảo giác Whisper trên nhạc/lặng).

    Câu dài (> max_len) thì coi như nói thật -> cho qua (tránh nuốt lời thật có
    lỡ chứa từ 'subscribe'...). Text rỗng cũng coi là bỏ."""
    t = (text or "").lower().strip()
    if not t:
        return True
    if len(t) > max_len:
        return False
    return any(p in t for p in HALLUCINATION_PHRASES)
