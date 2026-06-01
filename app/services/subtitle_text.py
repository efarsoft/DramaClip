"""向后兼容 - 已迁移到 app.services.clip.subtitle_text"""
from app.services.clip.subtitle_text import *  # noqa: F401,F403
from app.services.clip.subtitle_text import (  # noqa: F401
    read_subtitle_text, has_timecodes, normalize_subtitle_text,
)
