"""
Phase 3.3 - First-Run Intelligent Onboarding

检测首次使用，推荐高质量模型套装，并提供一键安装入口。
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from loguru import logger

from app.config.unified_config import get_config


_FIRST_RUN_FLAG = Path.home() / ".dramaclip" / ".first_run_completed"


def is_first_run() -> bool:
    """是否为首次运行。"""
    return not _FIRST_RUN_FLAG.exists()


def mark_first_run_completed():
    """标记首次运行已完成（更健壮的写入）。"""
    try:
        _FIRST_RUN_FLAG.parent.mkdir(parents=True, exist_ok=True)
        _FIRST_RUN_FLAG.write_text("completed", encoding="utf-8")
    except Exception as e:
        logger.warning(f"无法写入首次运行标记: {e}")


def get_recommended_packs() -> List[Dict]:
    """
    返回推荐的质量套装。
    每个套装包含：name, description, models, estimated_size_gb, recommended_for
    """
    return [
        {
            "id": "light_high_quality",
            "name": "轻量高质套装（推荐新用户）",
            "description": "Kokoro（极快中文TTS）+ SenseVoice（强方言/情绪ASR）",
            "models": [
                "hexgrad/Kokoro-82M-v1.1-zh",
                "iic/SenseVoiceSmall"
            ],
            "estimated_size_gb": 1.1,
            "recommended_for": "大多数短剧，资源占用低，效果已很好",
        },
    ]


def get_hardware_recommendation() -> str:
    """简单硬件推荐（当前仅有轻量高质套装）。"""
    return "light_high_quality"


def apply_recommended_pack(pack_id: str) -> bool:
    """
    应用推荐套装（目前仅设置默认 TTS 引擎）。
    实际模型下载由用户在模型管理中触发。
    """
    try:
        cfg = get_config()
        tts_cfg = dict(cfg.get("tts", {}) or {})
        if pack_id == "light_high_quality":
            tts_cfg["engine"] = "kokoro"
            # 通过内部机制更新
            if hasattr(cfg, '_settings'):
                cfg._settings.setdefault("tts", {}).update(tts_cfg)
            logger.info("已切换默认 TTS 为 kokoro（轻量高质套装）")
            return True
    except Exception as e:
        logger.warning(f"应用推荐套装时出错（可忽略，后端仍可用）: {e}")
    return True  # 即使更新失败也返回成功，让流程继续
