"""
剪辑配置模板管理模块
P2 差异化：用户配置模板化

功能：
1. 保存/加载剪辑配置模板
2. 分享模板
3. 模板分类管理
"""

import json
import uuid
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from loguru import logger

from app.services.clip.style import ClipStyle, PresetStyles, get_style_manager


class TemplateCategory(str, Enum):
    """模板分类"""
    ORIGINAL = "original"           # 原片直剪
    HYBRID = "hybrid"              # 混合解说
    FULL = "full"                 # 全解说
    CUSTOM = "custom"             # 自定义
    SHARED = "shared"             # 分享模板


@dataclass
class ClipConfig:
    """剪辑配置"""
    mode: str = "original"                    # 剪辑模式
    target_duration: int = 0                  # 目标时长（0=不限）
    target_ratio: str = "9:16"                # 输出比例
    quality: str = "1080p"                     # 输出质量
    auto_title: bool = True                   # 自动生成标题
    min_segment_duration: float = 3.0         # 最小片段时长
    max_segments: int = 0                     # 最大片段数（0=不限）
    enable_trim: bool = True                  # 启用裁剪


@dataclass
class ExportConfig:
    """导出配置"""
    format: str = "mp4"                       # 格式
    codec: str = "h264"                       # 编码
    bitrate: str = "8M"                       # 码率
    fps: int = 30                             # 帧率
    audio_codec: str = "aac"                  # 音频编码
    audio_bitrate: str = "128k"               # 音频码率


@dataclass
class ClipTemplate:
    """
    剪辑配置模板
    
    包含完整的剪辑配置和风格设置
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = "未命名模板"
    description: str = ""
    category: TemplateCategory = TemplateCategory.CUSTOM
    tags: List[str] = field(default_factory=list)
    author: str = "local"

    clip: ClipConfig = field(default_factory=ClipConfig)
    export: ExportConfig = field(default_factory=ExportConfig)
    style: Optional[ClipStyle] = None

    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    usage_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        result = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category.value,
            "tags": self.tags,
            "author": self.author,
            "clip": {
                "mode": self.clip.mode,
                "target_duration": self.clip.target_duration,
                "target_ratio": self.clip.target_ratio,
                "quality": self.clip.quality,
                "auto_title": self.clip.auto_title,
                "min_segment_duration": self.clip.min_segment_duration,
                "max_segments": self.clip.max_segments,
                "enable_trim": self.clip.enable_trim,
            },
            "export": {
                "format": self.export.format,
                "codec": self.export.codec,
                "bitrate": self.export.bitrate,
                "fps": self.export.fps,
                "audio_codec": self.export.audio_codec,
                "audio_bitrate": self.export.audio_bitrate,
            },
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "usage_count": self.usage_count,
        }

        if self.style:
            result["style"] = self.style.to_dict()

        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ClipTemplate":
        """从字典反序列化"""
        clip_data = data.get("clip", {})
        clip = ClipConfig(
            mode=clip_data.get("mode", "original"),
            target_duration=clip_data.get("target_duration", 0),
            target_ratio=clip_data.get("target_ratio", "9:16"),
            quality=clip_data.get("quality", "1080p"),
            auto_title=clip_data.get("auto_title", True),
            min_segment_duration=clip_data.get("min_segment_duration", 3.0),
            max_segments=clip_data.get("max_segments", 0),
            enable_trim=clip_data.get("enable_trim", True),
        )

        export_data = data.get("export", {})
        export = ExportConfig(
            format=export_data.get("format", "mp4"),
            codec=export_data.get("codec", "h264"),
            bitrate=export_data.get("bitrate", "8M"),
            fps=export_data.get("fps", 30),
            audio_codec=export_data.get("audio_codec", "aac"),
            audio_bitrate=export_data.get("audio_bitrate", "128k"),
        )

        template = cls(
            id=data.get("id", str(uuid.uuid4())[:8]),
            name=data.get("name", "未命名模板"),
            description=data.get("description", ""),
            category=TemplateCategory(data.get("category", "custom")),
            tags=data.get("tags", []),
            author=data.get("author", "local"),
            clip=clip,
            export=export,
            created_at=data.get("created_at", datetime.now().isoformat()),
            updated_at=data.get("updated_at", datetime.now().isoformat()),
            usage_count=data.get("usage_count", 0),
        )

        if "style" in data:
            template.style = ClipStyle.from_dict(data["style"])

        return template

    def update_timestamp(self):
        """更新修改时间"""
        self.updated_at = datetime.now().isoformat()


class TemplateManager:
    """
    模板管理器
    
    管理用户配置模板的保存、加载、分享
    """

    def __init__(self, storage_dir: Optional[Path] = None):
        if storage_dir is None:
            storage_dir = Path.home() / ".dramaclip" / "templates"
        self._storage_dir = storage_dir
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._templates: Dict[str, ClipTemplate] = {}
        self._load_all()

    def _load_all(self):
        """加载所有模板"""
        if not self._storage_dir.exists():
            return

        for file_path in self._storage_dir.glob("*.json"):
            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
                template = ClipTemplate.from_dict(data)
                self._templates[template.id] = template
            except Exception as e:
                logger.warning(f"[TemplateManager] 加载失败 {file_path}: {e}")

        logger.info(f"[TemplateManager] 加载了 {len(self._templates)} 个模板")

    def _save(self, template: ClipTemplate):
        """保存单个模板"""
        file_path = self._storage_dir / f"{template.id}.json"
        file_path.write_text(
            json.dumps(template.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    def create(
        self,
        name: str,
        description: str = "",
        category: TemplateCategory = TemplateCategory.CUSTOM,
        clip_config: Optional[ClipConfig] = None,
        style: Optional[ClipStyle] = None,
        tags: Optional[List[str]] = None,
    ) -> ClipTemplate:
        """
        创建新模板

        Args:
            name: 模板名称
            description: 模板描述
            category: 分类
            clip_config: 剪辑配置
            style: 风格配置
            tags: 标签

        Returns:
            创建的模板
        """
        template = ClipTemplate(
            id=str(uuid.uuid4())[:8],
            name=name,
            description=description,
            category=category,
            tags=tags or [],
            clip=clip_config or ClipConfig(),
            style=style,
        )

        self._templates[template.id] = template
        self._save(template)

        logger.info(f"[TemplateManager] 创建模板: {template.id} - {name}")
        return template

    def get(self, template_id: str) -> Optional[ClipTemplate]:
        """获取模板"""
        template = self._templates.get(template_id)
        if template:
            template.usage_count += 1
            self._save(template)
        return template

    def update(
        self,
        template_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[List[str]] = None,
        clip_config: Optional[ClipConfig] = None,
        style: Optional[ClipStyle] = None,
    ) -> Optional[ClipTemplate]:
        """更新模板"""
        template = self._templates.get(template_id)
        if not template:
            return None

        if name is not None:
            template.name = name
        if description is not None:
            template.description = description
        if tags is not None:
            template.tags = tags
        if clip_config is not None:
            template.clip = clip_config
        if style is not None:
            template.style = style

        template.update_timestamp()
        self._save(template)

        logger.info(f"[TemplateManager] 更新模板: {template_id}")
        return template

    def delete(self, template_id: str) -> bool:
        """删除模板"""
        if template_id not in self._templates:
            return False

        del self._templates[template_id]

        file_path = self._storage_dir / f"{template_id}.json"
        if file_path.exists():
            file_path.unlink()

        logger.info(f"[TemplateManager] 删除模板: {template_id}")
        return True

    def list(
        self,
        category: Optional[TemplateCategory] = None,
        tags: Optional[List[str]] = None,
        search: Optional[str] = None,
    ) -> List[ClipTemplate]:
        """列出模板"""
        templates = list(self._templates.values())

        if category:
            templates = [t for t in templates if t.category == category]

        if tags:
            templates = [
                t for t in templates
                if any(tag in t.tags for tag in tags)
            ]

        if search:
            search_lower = search.lower()
            templates = [
                t for t in templates
                if search_lower in t.name.lower()
                or search_lower in t.description.lower()
            ]

        templates.sort(key=lambda t: t.usage_count, reverse=True)
        return templates

    def export(self, template_id: str) -> Optional[str]:
        """
        导出模板为 JSON 字符串

        用于分享模板
        """
        template = self._templates.get(template_id)
        if not template:
            return None

        export_data = template.to_dict()
        export_data["author"] = "shared"
        return json.dumps(export_data, ensure_ascii=False, indent=2)

    def import_template(self, json_str: str) -> Optional[ClipTemplate]:
        """
        导入模板

        Args:
            json_str: 模板 JSON 字符串

        Returns:
            导入的模板
        """
        try:
            data = json.loads(json_str)
            data["id"] = str(uuid.uuid4())[:8]
            data["author"] = "imported"
            data["created_at"] = datetime.now().isoformat()
            data["updated_at"] = data["created_at"]
            data["usage_count"] = 0

            template = ClipTemplate.from_dict(data)
            self._templates[template.id] = template
            self._save(template)

            logger.info(f"[TemplateManager] 导入模板: {template.id} - {template.name}")
            return template
        except Exception as e:
            logger.error(f"[TemplateManager] 导入失败: {e}")
            return None

    def create_from_preset(self, preset_name: str) -> Optional[ClipTemplate]:
        """
        从预设创建模板

        Args:
            preset_name: 预设名称

        Returns:
            创建的模板
        """
        presets = {
            "original_fast": ("原片快剪", TemplateCategory.ORIGINAL, PresetStyles.original_fast),
            "original_cinematic": ("电影感", TemplateCategory.ORIGINAL, PresetStyles.original_cinematic),
            "hybrid_explainer": ("知识讲解", TemplateCategory.HYBRID, PresetStyles.hybrid_explainer),
            "hybrid_entertainment": ("娱乐解说", TemplateCategory.HYBRID, PresetStyles.hybrid_entertainment),
            "full_documentary": ("纪录片", TemplateCategory.FULL, PresetStyles.full_narration_documentary),
            "full_excited": ("激情解说", TemplateCategory.FULL, PresetStyles.full_narration_excited),
        }

        if preset_name not in presets:
            return None

        name, category, preset_fn = presets[preset_name]
        style = preset_fn()

        template = self.create(
            name=name,
            description=f"基于预设 {preset_name} 创建",
            category=category,
            style=style,
            tags=[preset_name],
        )

        return template

    def get_recent(self, limit: int = 5) -> List[ClipTemplate]:
        """获取最近使用的模板"""
        templates = list(self._templates.values())
        templates.sort(key=lambda t: t.updated_at, reverse=True)
        return templates[:limit]


_global_template_manager: Optional[TemplateManager] = None


def get_template_manager() -> TemplateManager:
    """获取全局模板管理器"""
    global _global_template_manager
    if _global_template_manager is None:
        _global_template_manager = TemplateManager()
    return _global_template_manager
