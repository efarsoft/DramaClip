"""
向后兼容 - 已迁移到 app.services.clip.style
"""
from app.services.clip.style import (  # noqa: F401
    RhythmStyle,
    TransitionStyle,
    NarrationStyle,
    FilterPreset,
    RhythmConfig,
    VisualConfig,
    NarrationConfig,
    ClipStyle,
    PresetStyles,
    StyleManager,
    get_style_manager,
)
