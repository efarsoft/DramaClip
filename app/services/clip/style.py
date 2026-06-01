"""
剪辑风格配置模块
P2 差异化：三种剪辑模式各有独特风格

支持配置：
- 叙事节奏（快/中/慢）
- 画面处理（滤镜/变速/转场）
- 解说风格（激情/冷静/幽默）
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Callable
from loguru import logger


class RhythmStyle(str, Enum):
    """叙事节奏风格"""
    FAST = "fast"           # 快节奏 - 短平快，爆点密集
    MEDIUM = "medium"       # 中等节奏 - 张弛有度
    SLOW = "slow"           # 慢节奏 - 铺垫深入


class TransitionStyle(str, Enum):
    """转场风格"""
    NONE = "none"           # 无转场 - 直接切换
    SIMPLE = "simple"       # 简单 - 淡入淡出
    DYNAMIC = "dynamic"     # 动态 - 滑动缩放
    CREATIVE = "creative"  # 创意 - 遮挡变速


class NarrationStyle(str, Enum):
    """解说风格"""
    EXCITED = "excited"     # 激情型 - 情绪饱满
    CALM = "calm"           # 冷静型 - 客观叙述
    HUMOR = "humor"         # 幽默型 - 轻松搞笑
    DRAMATIC = "dramatic"   # 戏剧型 - 悬念感强


class FilterPreset(str, Enum):
    """画面滤镜预设"""
    NONE = "none"           # 无滤镜
    VIBRANT = "vibrant"     # 鲜艳
    CINEMATIC = "cinematic" # 电影感
    VINTAGE = "vintage"     # 复古
    BW = "bw"              # 黑白
    WARM = "warm"           # 暖色调
    COOL = "cool"           # 冷色调


@dataclass
class RhythmConfig:
    """节奏配置"""
    style: RhythmStyle = RhythmStyle.MEDIUM
    scene_duration_min: float = 3.0      # 最小场景时长
    scene_duration_max: float = 15.0      # 最大场景时长
    transition_duration: float = 0.5      # 转场时长
    pacing_factor: float = 1.0            # 节奏系数（>1加速，<1减速）

    @property
    def target_dialogue_ratio(self) -> float:
        """目标对话占比"""
        if self.style == RhythmStyle.FAST:
            return 0.4
        elif self.style == RhythmStyle.MEDIUM:
            return 0.5
        else:
            return 0.6


@dataclass
class VisualConfig:
    """画面配置"""
    filter: FilterPreset = FilterPreset.NONE
    brightness: float = 1.0          # 亮度调整 0.5-1.5
    contrast: float = 1.0             # 对比度调整 0.5-1.5
    saturation: float = 1.0           # 饱和度调整 0.5-1.5
    speed_change_enabled: bool = False  # 是否启用变速
    speed_min: float = 0.8            # 最小速度
    speed_max: float = 1.5            # 最大速度
    zoom_enabled: bool = False        # 是否启用缩放


@dataclass
class NarrationConfig:
    """解说配置"""
    style: NarrationStyle = NarrationStyle.CALM
    voice_type: str = "female"        # 音色: male/female
    speech_rate: float = 1.0          # 语速 0.5-2.0
    pitch_adjust: float = 0.0         # 音调调整 -10到10
    bgm_volume: float = 0.3           # 背景音乐音量 0-1
    sfx_enabled: bool = True          # 音效启用


@dataclass
class ClipStyle:
    """
    完整剪辑风格配置
    
    整合节奏、画面、解说配置
    """
    name: str = "默认风格"
    rhythm: RhythmConfig = field(default_factory=RhythmConfig)
    visual: VisualConfig = field(default_factory=VisualConfig)
    narration: NarrationConfig = field(default_factory=NarrationConfig)

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "name": self.name,
            "rhythm": {
                "style": self.rhythm.style.value,
                "scene_duration_min": self.rhythm.scene_duration_min,
                "scene_duration_max": self.rhythm.scene_duration_max,
                "transition_duration": self.rhythm.transition_duration,
                "pacing_factor": self.rhythm.pacing_factor,
            },
            "visual": {
                "filter": self.visual.filter.value,
                "brightness": self.visual.brightness,
                "contrast": self.visual.contrast,
                "saturation": self.visual.saturation,
                "speed_change_enabled": self.visual.speed_change_enabled,
                "zoom_enabled": self.visual.zoom_enabled,
            },
            "narration": {
                "style": self.narration.style.value,
                "voice_type": self.narration.voice_type,
                "speech_rate": self.narration.speech_rate,
                "pitch_adjust": self.narration.pitch_adjust,
                "bgm_volume": self.narration.bgm_volume,
                "sfx_enabled": self.narration.sfx_enabled,
            },
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ClipStyle":
        """从字典反序列化"""
        rhythm_data = data.get("rhythm", {})
        rhythm = RhythmConfig(
            style=RhythmStyle(rhythm_data.get("style", "medium")),
            scene_duration_min=rhythm_data.get("scene_duration_min", 3.0),
            scene_duration_max=rhythm_data.get("scene_duration_max", 15.0),
            transition_duration=rhythm_data.get("transition_duration", 0.5),
            pacing_factor=rhythm_data.get("pacing_factor", 1.0),
        )

        visual_data = data.get("visual", {})
        visual = VisualConfig(
            filter=FilterPreset(visual_data.get("filter", "none")),
            brightness=visual_data.get("brightness", 1.0),
            contrast=visual_data.get("contrast", 1.0),
            saturation=visual_data.get("saturation", 1.0),
            speed_change_enabled=visual_data.get("speed_change_enabled", False),
            zoom_enabled=visual_data.get("zoom_enabled", False),
        )

        narration_data = data.get("narration", {})
        narration = NarrationConfig(
            style=NarrationStyle(narration_data.get("style", "calm")),
            voice_type=narration_data.get("voice_type", "female"),
            speech_rate=narration_data.get("speech_rate", 1.0),
            pitch_adjust=narration_data.get("pitch_adjust", 0.0),
            bgm_volume=narration_data.get("bgm_volume", 0.3),
            sfx_enabled=narration_data.get("sfx_enabled", True),
        )

        return cls(
            name=data.get("name", "默认风格"),
            rhythm=rhythm,
            visual=visual,
            narration=narration,
        )


class PresetStyles:
    """预设风格"""

    @staticmethod
    def original_fast() -> ClipStyle:
        """
        原片直剪-快节奏风格
        适用：动作片、喜剧、悬疑开头
        """
        return ClipStyle(
            name="原片快剪",
            rhythm=RhythmConfig(
                style=RhythmStyle.FAST,
                scene_duration_min=2.0,
                scene_duration_max=8.0,
                pacing_factor=1.3,
            ),
            visual=VisualConfig(
                filter=FilterPreset.VIBRANT,
                speed_change_enabled=True,
            ),
            narration=NarrationConfig(
                style=NarrationStyle.EXCITED,
                speech_rate=1.2,
            ),
        )

    @staticmethod
    def original_cinematic() -> ClipStyle:
        """
        原片直剪-电影感风格
        适用：剧情片、爱情片、文艺片
        """
        return ClipStyle(
            name="电影感",
            rhythm=RhythmConfig(
                style=RhythmStyle.SLOW,
                scene_duration_min=5.0,
                scene_duration_max=20.0,
                pacing_factor=0.85,
            ),
            visual=VisualConfig(
                filter=FilterPreset.CINEMATIC,
                brightness=0.95,
                contrast=1.1,
            ),
            narration=NarrationConfig(
                style=NarrationStyle.DRAMATIC,
                speech_rate=0.9,
                bgm_volume=0.4,
            ),
        )

    @staticmethod
    def hybrid_explainer() -> ClipStyle:
        """
        混合解说-知识讲解风格
        适用：纪录片、教程、科普
        """
        return ClipStyle(
            name="知识讲解",
            rhythm=RhythmConfig(
                style=RhythmStyle.MEDIUM,
                scene_duration_min=3.0,
                scene_duration_max=12.0,
                pacing_factor=1.0,
            ),
            visual=VisualConfig(
                filter=FilterPreset.NONE,
                zoom_enabled=True,
            ),
            narration=NarrationConfig(
                style=NarrationStyle.CALM,
                speech_rate=1.0,
                bgm_volume=0.2,
                sfx_enabled=True,
            ),
        )

    @staticmethod
    def hybrid_entertainment() -> ClipStyle:
        """
        混合解说-娱乐解说风格
        适用：影视解说、娱乐评论
        """
        return ClipStyle(
            name="娱乐解说",
            rhythm=RhythmConfig(
                style=RhythmStyle.FAST,
                scene_duration_min=2.0,
                scene_duration_max=10.0,
                pacing_factor=1.2,
            ),
            visual=VisualConfig(
                filter=FilterPreset.WARM,
                brightness=1.05,
            ),
            narration=NarrationConfig(
                style=NarrationStyle.HUMOR,
                speech_rate=1.15,
                bgm_volume=0.25,
                sfx_enabled=True,
            ),
        )

    @staticmethod
    def full_narration_documentary() -> ClipStyle:
        """
        全解说-纪录片风格
        适用：纪录片、历史、人文
        """
        return ClipStyle(
            name="纪录片",
            rhythm=RhythmConfig(
                style=RhythmStyle.SLOW,
                scene_duration_min=4.0,
                scene_duration_max=15.0,
                pacing_factor=0.9,
            ),
            visual=VisualConfig(
                filter=FilterPreset.CINEMATIC,
                contrast=1.05,
                saturation=0.95,
            ),
            narration=NarrationConfig(
                style=NarrationStyle.CALM,
                voice_type="male",
                speech_rate=0.85,
                bgm_volume=0.35,
                sfx_enabled=True,
            ),
        )

    @staticmethod
    def full_narration_excited() -> ClipStyle:
        """
        全解说-激情解说风格
        适用：体育、综艺、热点
        """
        return ClipStyle(
            name="激情解说",
            rhythm=RhythmConfig(
                style=RhythmStyle.FAST,
                scene_duration_min=1.5,
                scene_duration_max=6.0,
                pacing_factor=1.4,
            ),
            visual=VisualConfig(
                filter=FilterPreset.VIBRANT,
                saturation=1.1,
            ),
            narration=NarrationConfig(
                style=NarrationStyle.EXCITED,
                speech_rate=1.3,
                pitch_adjust=2.0,
                bgm_volume=0.3,
                sfx_enabled=True,
            ),
        )

    @staticmethod
    def suspense_thriller() -> ClipStyle:
        """
        悬疑惊悚风格
        适用：悬疑剧、惊悚片
        """
        return ClipStyle(
            name="悬疑惊悚",
            rhythm=RhythmConfig(
                style=RhythmStyle.SLOW,
                scene_duration_min=4.0,
                scene_duration_max=18.0,
                pacing_factor=0.8,
            ),
            visual=VisualConfig(
                filter=FilterPreset.COOL,
                brightness=0.9,
                contrast=1.15,
                saturation=0.85,
            ),
            narration=NarrationConfig(
                style=NarrationStyle.DRAMATIC,
                speech_rate=0.85,
                bgm_volume=0.4,
                sfx_enabled=True,
            ),
        )

    @staticmethod
    def romantic_warm() -> ClipStyle:
        """
        浪漫温馨风格
        适用：爱情剧、治愈系
        """
        return ClipStyle(
            name="浪漫温馨",
            rhythm=RhythmConfig(
                style=RhythmStyle.SLOW,
                scene_duration_min=5.0,
                scene_duration_max=20.0,
                pacing_factor=0.85,
            ),
            visual=VisualConfig(
                filter=FilterPreset.WARM,
                brightness=1.05,
                saturation=1.1,
            ),
            narration=NarrationConfig(
                style=NarrationStyle.CALM,
                voice_type="female",
                speech_rate=0.9,
                bgm_volume=0.45,
                sfx_enabled=False,
            ),
        )

    @classmethod
    def get_presets(cls) -> Dict[str, ClipStyle]:
        """获取所有预设"""
        return {
            "original_fast": cls.original_fast(),
            "original_cinematic": cls.original_cinematic(),
            "hybrid_explainer": cls.hybrid_explainer(),
            "hybrid_entertainment": cls.hybrid_entertainment(),
            "full_documentary": cls.full_narration_documentary(),
            "full_excited": cls.full_narration_excited(),
            "suspense": cls.suspense_thriller(),
            "romantic": cls.romantic_warm(),
        }

    @classmethod
    def get_presets_for_mode(cls, mode: str) -> List[ClipStyle]:
        """根据剪辑模式获取推荐预设"""
        presets = {
            "original": [
                cls.original_fast(),
                cls.original_cinematic(),
                cls.suspense_thriller(),
                cls.romantic_warm(),
            ],
            "hybrid": [
                cls.hybrid_explainer(),
                cls.hybrid_entertainment(),
            ],
            "full": [
                cls.full_narration_documentary(),
                cls.full_narration_excited(),
            ],
        }
        return presets.get(mode, [cls.original_cinematic()])


class StyleManager:
    """
    风格管理器
    
    管理用户自定义风格和预设风格
    """

    def __init__(self):
        self._presets = PresetStyles.get_presets()
        self._custom_styles: Dict[str, ClipStyle] = {}

    def get_style(self, style_id: str) -> Optional[ClipStyle]:
        """获取风格"""
        if style_id in self._custom_styles:
            return self._custom_styles[style_id]
        if style_id in self._presets:
            return self._presets[style_id]
        return None

    def save_custom_style(self, style_id: str, style: ClipStyle) -> bool:
        """保存自定义风格"""
        try:
            self._custom_styles[style_id] = style
            self._save_to_storage(style_id, style)
            logger.info(f"[StyleManager] 保存风格: {style_id}")
            return True
        except Exception as e:
            logger.error(f"[StyleManager] 保存失败: {e}")
            return False

    def delete_custom_style(self, style_id: str) -> bool:
        """删除自定义风格"""
        if style_id in self._custom_styles:
            del self._custom_styles[style_id]
            self._delete_from_storage(style_id)
            return True
        return False

    def list_presets(self) -> List[str]:
        """列出所有预设"""
        return list(self._presets.keys())

    def list_custom_styles(self) -> List[str]:
        """列出所有自定义风格"""
        return list(self._custom_styles.keys())

    def _save_to_storage(self, style_id: str, style: ClipStyle):
        """保存到存储"""
        import json
        from pathlib import Path

        storage_dir = Path.home() / ".dramaclip" / "styles"
        storage_dir.mkdir(parents=True, exist_ok=True)

        file_path = storage_dir / f"{style_id}.json"
        file_path.write_text(
            json.dumps(style.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    def _delete_from_storage(self, style_id: str):
        """从存储删除"""
        from pathlib import Path

        storage_dir = Path.home() / ".dramaclip" / "styles"
        file_path = storage_dir / f"{style_id}.json"

        if file_path.exists():
            file_path.unlink()

    def load_from_storage(self):
        """从存储加载"""
        import json
        from pathlib import Path

        storage_dir = Path.home() / ".dramaclip" / "styles"

        if not storage_dir.exists():
            return

        for file_path in storage_dir.glob("*.json"):
            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
                style_id = file_path.stem
                self._custom_styles[style_id] = ClipStyle.from_dict(data)
            except Exception as e:
                logger.warning(f"[StyleManager] 加载失败 {file_path}: {e}")


_global_style_manager: Optional[StyleManager] = None


def get_style_manager() -> StyleManager:
    """获取全局风格管理器"""
    global _global_style_manager
    if _global_style_manager is None:
        _global_style_manager = StyleManager()
        _global_style_manager.load_from_storage()
    return _global_style_manager
