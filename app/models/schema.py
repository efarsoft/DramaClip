"""
DramaClip - 数据模型定义
基于 NarratoAI schema 扩展，增加短剧高光剪辑专用模型
"""

from enum import Enum
from typing import Optional, List, Any
from pydantic import BaseModel, Field


# ============================================
# 原有模型（从 NarratoAI 保留）
# ============================================

class VideoAspect(str, Enum):
    """视频宽高比"""
    landscape = "16:9"
    landscape_2 = "4:3"
    portrait = "9:16"
    portrait_2 = "3:4"
    square = "1:1"

    def to_resolution(self):
        resolutions = {
            "16:9": (1920, 1080),
            "4:3": (1440, 1080),
            "9:16": (1080, 1920),
            "3:4": (1080, 1440),
            "1:1": (1080, 1080),
        }
        return resolutions.get(self.value, (1080, 1920))


class VideoConcatMode(str, Enum):
    """视频拼接模式"""
    random = "random"
    sequential = "sequential"


class SubtitlePosition(str, Enum):
    """字幕位置"""
    bottom = "bottom"
    top = "top"
    center = "center"


# 音量范围与默认值常量 (UI 组件使用)
class AudioVolumeDefaults:
    """音频默认音量配置（常量 + 默认值）"""
    MIN_VOLUME: float = 0.0
    MAX_VOLUME: float = 2.0
    VOICE_VOLUME: float = 1.0
    BGM_VOLUME: float = 0.3
    ORIGINAL_VOLUME: float = 0.0
    ENABLE_SMART_VOLUME: bool = True


class AudioVolumeConfig(BaseModel):
    """音频音量运行时配置（实例字段）"""


class MaterialInfo(BaseModel):
    """视频素材信息"""
    provider: str = ""
    url: str = ""
    duration: int = 0
    video_file_path: str = ""


class VideoClipParams(BaseModel):
    """视频剪辑参数 — 完整字段定义（UI + task.py 双向对齐）"""
    # 脚本相关
    video_origin_path: str = Field(default="", description="原视频路径(兼容旧接口)")
    video_origin_paths: List[str] = Field(default_factory=list, description="原视频路径列表(多集短剧)")
    video_clip_json_path: str = Field(default="", description="脚本JSON路径")
    video_plot: str = Field(default="", description="剧情描述")
    voice_name: str = Field(default="zh-CN-XiaoyiNeural-Female", description="TTS音色")
    
    # 视频参数
    video_aspect: VideoAspect = Field(default=VideoAspect.portrait, description="视频宽高比")
    video_quality: str = Field(default="1080p", description="视频画质")
    video_concat_mode: VideoConcatMode = Field(default=VideoConcatMode.sequential, description="拼接模式")
    clip_mode: str = Field(default="direct_cut", description="剪辑模式(direct_cut/ai_narration)")
    
    # 音频参数
    bgm_volume: float = Field(default=0.3, description="BGM音量")
    voice_volume: float = Field(default=1.0, description="人声音量")
    original_audio_volume: float = Field(default=0.2, description="原声音量(作为背景)")
    original_volume: float = Field(default=0.0, description="原声音量(UI slider用)")
    tts_engine: str = Field(default="edge_tts", description="TTS引擎")
    voice_rate: float = Field(default=1.0, description="TTS语速")
    voice_pitch: float = Field(default=1.0, description="TTS音调")
    tts_volume: float = Field(default=1.0, description="TTS音量")
    bgm_type: str = Field(default="random", description="BGM类型(random/custom/none)")
    bgm_file: str = Field(default="", description="BGM自定义文件路径")
    
    # 字幕参数
    subtitle_enabled: bool = Field(default=True, description="是否启用字幕")
    subtitle_font_size: int = Field(default=40, description="字幕大小")
    subtitle_color: str = Field(default="#FFFFFF", description="字幕颜色")
    subtitle_position: SubtitlePosition = Field(default=SubtitlePosition.bottom, description="字幕位置")
    font_name: str = Field(default="SimHei", description="字体名称")
    font_size: int = Field(default=60, description="字体大小(字幕渲染)")
    text_fore_color: str = Field(default="#FFFFFF", description="文字颜色(字幕)")
    custom_position: Optional[float] = Field(default=None, description="自定义字幕位置(百分比)")
    
    # 脚本与模式参数
    script_type: str = Field(default="short", description="脚本类型(short/summary/auto)")
    target_duration: int = Field(default=30, description="目标时长(秒)")
    output_duration: int = Field(default=30, description="输出时长(秒)")
    video_language: str = Field(default="", description="视频语言")
    video_name: str = Field(default="", description="视频名称")
    n_threads: int = Field(default=2, description="线程数")


# ============================================
# DramaClip 新增模型
# ============================================

class ClipMode(str, Enum):
    """
    DramaClip 剪辑模式
    
    - direct_cut: 原片直剪模式 — 保留原声，快速提取高光
    - ai_narration: AI解说模式 — 生成旁白，替换原声
    """
    DIRECT_CUT = "direct_cut"
    AI_NARRATION = "ai_narration"


class SceneSegment(BaseModel):
    """
    镜头片段（场景分割后的基本单元）
    
    每个镜头片段代表视频中一个连续的场景片段，
    经过 PySceneDetect 分割后生成。
    """
    # 基本信息
    segment_id: str = Field(description="片段唯一ID")
    episode_index: int = Field(description="所属剧集序号(从1开始)")
    start_time: float = Field(description="起始时间(秒)")
    end_time: float = Field(description="结束时间(秒)")
    duration: float = Field(description="片段时长(秒)")
    
    # 文件路径
    video_path: Optional[str] = Field(default=None, description="片段视频文件路径")
    audio_path: Optional[str] = Field(default=None, description="提取的音频文件路径")
    
    # ASR转写结果
    subtitle_text: Optional[str] = Field(default=None, description="该片段的台词/字幕文本")
    subtitle_srt_path: Optional[str] = Field(default=None, description="SRT字幕文件路径")
    
    # 画面分析结果
    has_face: bool = Field(default=False, description="是否包含人脸")
    is_closeup: bool = Field(default=False, description="是否为特写镜头")
    face_center_x: Optional[float] = Field(default=None, description="人脸中心X坐标(归一化0-1)")
    face_center_y: Optional[float] = Field(default=None, description="人脸中心Y坐标(归一化0-1)")
    has_action: bool = Field(default=False, description="是否有肢体动作/冲突")
    emotion_tags: List[str] = Field(default_factory=list, description="检测到的情绪标签(anger/surprise/sadness等)")
    
    # 音频分析结果
    audio_peak_db: Optional[float] = Field(default=None, description="音量峰值(dB)")
    audio_rms: Optional[float] = Field(default=None, description="音频RMS均值")
    audio_energy: Optional[float] = Field(default=None, description="音频能量")
    has_sudden_change: bool = Field(default=False, description="是否存在音频突变")
    speech_rate: Optional[float] = Field(default=None, description="语速(字/秒)")
    
    # 打分结果
    audio_score: Optional[float] = Field(default=None, description="音频爆点得分(0-1)")
    emotion_score: Optional[float] = Field(default=None, description="台词情绪得分(0-1)")
    visual_score: Optional[float] = Field(default=None, description="画面特征得分(0-1)")
    rhythm_score: Optional[float] = Field(default=None, description="镜头节奏得分(0-1)")
    total_score: Optional[float] = Field(default=None, description="综合得分(0-1)")
    
    # 排序与筛选
    rank: Optional[int] = Field(default=None, description="排名")
    selected: bool = Field(default=False, description="是否被选中为高光片段")


class HighlightScoreWeights(BaseModel):
    """
    高光打分权重配置
    
    默认公式: score = 0.4*audio + 0.3*emotion + 0.2*visual + 0.1*rhythm
    """
    audio_weight: float = Field(default=0.4, ge=0, le=1, description="音频爆点权重")
    emotion_weight: float = Field(default=0.3, ge=0, le=1, description="台词情绪权重")
    visual_weight: float = Field(default=0.2, ge=0, le=1, description="画面特征权重")
    rhythm_weight: float = Field(default=0.1, ge=0, le=1, description="镜头节奏权重")
    
    def validate_weights(self) -> bool:
        """验证权重之和是否为1.0"""
        total = self.audio_weight + self.emotion_weight + self.visual_weight + self.rhythm_weight
        return abs(total - 1.0) < 0.01


class HighlightConfig(BaseModel):
    """高光识别配置"""
    weights: HighlightScoreWeights = Field(default_factory=HighlightScoreWeights)
    top_ratio: float = Field(default=0.3, ge=0.1, le=0.8, description="Top N比例")
    min_segment_duration: float = Field(default=2.0, ge=1.0, le=10.0, description="最小片段时长(秒)")
    max_segments_per_episode: int = Field(default=5, ge=1, le=20, description="每集最多片段数")
    min_episodes_covered: int = Field(default=1, ge=1, description="最少覆盖集数")


class DramaClipOutputConfig(BaseModel):
    """输出配置"""
    duration_seconds: int = Field(default=30, description="目标输出时长(秒)")
    resolution: str = Field(default="1080P", description="分辨率")
    aspect_ratio: str = Field(default="9:16", description="宽高比")
    fps: int = Field(default=25, description="帧率")
    format: str = Field(default="mp4", description="输出格式")


class NarrationScript(BaseModel):
    """AI解说文案"""
    title: str = Field(default="", description="解说标题")
    segments: List[dict] = Field(default_factory=list, description="分段解说内容")
    full_text: str = Field(default="", description="完整文案文本")
    style: str = Field(default="normal", description="文案风格(normal/satire/concise)")
    
    class NarrationSegment(BaseModel):
        timestamp: float = Field(description="对应时间点")
        text: str = Field(description="解说文本")
        emphasis: bool = Field(default=False, description="是否为重点强调")


class EpisodeInput(BaseModel):
    """单集输入信息"""
    episode_index: int = Field(description="剧集序号")
    file_path: str = Field(description="文件路径")
    file_name: str = Field(description="文件名")
    file_size_mb: float = Field(description="文件大小(MB)")
    duration_seconds: float = Field(description="视频时长(秒)")
    resolution: str = Field(description="分辨率")
    thumbnail_path: Optional[str] = Field(default=None, description="缩略图路径")
