"""
平台适配与投稿检查模块
P2 差异化：确保视频符合目标平台要求

支持平台：
- 抖音 / TikTok
- 快手
- B站
- 微信视频号
- 小红书
"""

from enum import Enum
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple
from loguru import logger


class Platform(str, Enum):
    """目标平台"""
    DOUYIN = "douyin"
    KUAISHOU = "kuaishou"
    BILIBILI = "bilibili"
    WECHAT = "wechat"
    XIAOHONGSHU = "xiaohongshu"
    YOUTUBE = "youtube"
    INSTAGRAM = "instagram"


class ViolationLevel(str, Enum):
    """违规级别"""
    ERROR = "error"      # 致命错误，不符合发布要求
    WARNING = "warning" # 警告，可能影响推荐
    INFO = "info"       # 提示信息


@dataclass
class FormatRequirement:
    """格式要求"""
    min_duration: float = 3.0           # 最小时长（秒）
    max_duration: float = 600.0         # 最大时长
    min_resolution: Tuple[int, int] = (720, 1280)  # 最小分辨率
    aspect_ratios: List[str] = ["9:16"] # 支持的比例
    min_bitrate: int = 1000            # 最小码率 (kbps)
    max_file_size: int = 4 * 1024 * 1024 * 1024  # 最大文件 4GB
    recommended_duration: Tuple[float, float] = (15.0, 60.0)  # 推荐时长范围


@dataclass
class ContentRule:
    """内容规则"""
    min_title_length: int = 5
    max_title_length: int = 30
    min_description_length: int = 10
    max_description_length: int = 2000
    required_tags_count: Tuple[int, int] = (3, 10)  # 标签数量范围
    max_hashtag_length: int = 10


@dataclass
class CheckResult:
    """检查结果"""
    level: ViolationLevel
    message: str
    field: str
    suggestion: Optional[str] = None


@dataclass
class PlatformAdapter:
    """平台适配器"""
    platform: Platform
    format_req: FormatRequirement
    content_rules: ContentRule
    cover_size: Tuple[int, int]
    recommended_tags: List[str]

    def check_video(
        self,
        duration: float,
        resolution: Tuple[int, int],
        aspect_ratio: str,
        bitrate: int,
        file_size: int,
    ) -> List[CheckResult]:
        """检查视频格式"""
        results = []

        if duration < self.format_req.min_duration:
            results.append(CheckResult(
                level=ViolationLevel.ERROR,
                message=f"视频时长过短，最少需要 {self.format_req.min_duration} 秒",
                field="duration",
                suggestion=f"当前: {duration:.1f}s，建议: >= {self.format_req.min_duration}s",
            ))
        elif duration > self.format_req.max_duration:
            results.append(CheckResult(
                level=ViolationLevel.WARNING,
                message=f"视频时长过长，可能影响完播率",
                field="duration",
                suggestion=f"当前: {duration:.1f}s，建议: <= {self.format_req.max_duration}s",
            ))

        min_w, min_h = self.format_req.min_resolution
        if resolution[0] < min_w or resolution[1] < min_h:
            results.append(CheckResult(
                level=ViolationLevel.ERROR,
                message=f"分辨率过低，需要至少 {min_w}x{min_h}",
                field="resolution",
                suggestion=f"当前: {resolution[0]}x{resolution[1]}",
            ))

        if aspect_ratio not in self.format_req.aspect_ratios:
            results.append(CheckResult(
                level=ViolationLevel.WARNING,
                message=f"比例 {aspect_ratio} 不是该平台最佳比例",
                field="aspect_ratio",
                suggestion=f"推荐比例: {', '.join(self.format_req.aspect_ratios)}",
            ))

        if bitrate < self.format_req.min_bitrate:
            results.append(CheckResult(
                level=ViolationLevel.WARNING,
                message=f"码率过低，可能影响画质",
                field="bitrate",
                suggestion=f"当前: {bitrate}kbps，建议: >= {self.format_req.min_bitrate}kbps",
            ))

        if file_size > self.format_req.max_file_size:
            results.append(CheckResult(
                level=ViolationLevel.ERROR,
                message=f"文件过大，超过平台限制",
                field="file_size",
                suggestion=f"当前: {file_size / 1024 / 1024:.1f}MB，建议: <= {self.format_req.max_file_size / 1024 / 1024 / 1024:.1f}GB",
            ))

        return results

    def check_title(self, title: str) -> List[CheckResult]:
        """检查标题"""
        results = []

        if len(title) < self.content_rules.min_title_length:
            results.append(CheckResult(
                level=ViolationLevel.WARNING,
                message="标题过短，可能影响曝光",
                field="title",
                suggestion=f"建议: >= {self.content_rules.min_title_length} 字",
            ))
        elif len(title) > self.content_rules.max_title_length:
            results.append(CheckResult(
                level=ViolationLevel.ERROR,
                message="标题过长，可能被截断",
                field="title",
                suggestion=f"建议: <= {self.content_rules.max_title_length} 字，当前: {len(title)} 字",
            ))

        return results

    def check_description(self, description: str) -> List[CheckResult]:
        """检查简介"""
        results = []

        if len(description) < self.content_rules.min_description_length:
            results.append(CheckResult(
                level=ViolationLevel.INFO,
                message="简介较短，可能影响推荐",
                field="description",
                suggestion=f"建议: >= {self.content_rules.min_description_length} 字",
            ))
        elif len(description) > self.content_rules.max_description_length:
            results.append(CheckResult(
                level=ViolationLevel.WARNING,
                message="简介过长，可能被截断",
                field="description",
                suggestion=f"建议: <= {self.content_rules.max_description_length} 字",
            ))

        return results

    def check_tags(self, tags: List[str]) -> List[CheckResult]:
        """检查标签"""
        results = []
        min_tags, max_tags = self.content_rules.required_tags_count

        if len(tags) < min_tags:
            results.append(CheckResult(
                level=ViolationLevel.INFO,
                message="标签数量较少",
                field="tags",
                suggestion=f"建议: {min_tags}-{max_tags} 个标签",
            ))
        elif len(tags) > max_tags:
            results.append(CheckResult(
                level=ViolationLevel.WARNING,
                message="标签数量过多",
                field="tags",
                suggestion=f"建议: {min_tags}-{max_tags} 个标签，当前: {len(tags)} 个",
            ))

        for tag in tags:
            if len(tag) > self.content_rules.max_hashtag_length:
                results.append(CheckResult(
                    level=ViolationLevel.INFO,
                    message=f"标签过长: #{tag}",
                    field="tags",
                    suggestion=f"建议: <= {self.content_rules.max_hashtag_length} 字",
                ))

        return results


class PlatformRegistry:
    """平台注册表"""

    _adapters: Dict[Platform, PlatformAdapter] = {}

    @classmethod
    def register(cls, adapter: PlatformAdapter):
        """注册平台"""
        cls._adapters[adapter.platform] = adapter

    @classmethod
    def get(cls, platform: Platform) -> Optional[PlatformAdapter]:
        """获取平台适配器"""
        return cls._adapters.get(platform)

    @classmethod
    def list_platforms(cls) -> List[Platform]:
        """列出所有平台"""
        return list(cls._adapters.keys())

    @classmethod
    def initialize(cls):
        """初始化所有平台"""
        cls.register(PlatformAdapter(
            platform=Platform.DOUYIN,
            format_req=FormatRequirement(
                min_duration=3.0,
                max_duration=600.0,
                min_resolution=(720, 1280),
                aspect_ratios=["9:16", "1:1"],
                min_bitrate=1500,
                recommended_duration=(15.0, 60.0),
            ),
            content_rules=ContentRule(
                min_title_length=5,
                max_title_length=30,
                min_description_length=10,
                max_description_length=2000,
                required_tags_count=(3, 10),
            ),
            cover_size=(1080, 1920),
            recommended_tags=["影视剪辑", "精彩片段", "推荐", "必看"],
        ))

        cls.register(PlatformAdapter(
            platform=Platform.KUAISHOU,
            format_req=FormatRequirement(
                min_duration=3.0,
                max_duration=300.0,
                min_resolution=(540, 960),
                aspect_ratios=["9:16", "16:9"],
                min_bitrate=1000,
                recommended_duration=(15.0, 57.0),
            ),
            content_rules=ContentRule(
                min_title_length=5,
                max_title_length=40,
                min_description_length=5,
                max_description_length=1500,
                required_tags_count=(2, 8),
            ),
            cover_size=(1080, 1920),
            recommended_tags=["影视", "片段", "推荐"],
        ))

        cls.register(PlatformAdapter(
            platform=Platform.BILIBILI,
            format_req=FormatRequirement(
                min_duration=5.0,
                max_duration=1800.0,
                min_resolution=(1280, 720),
                aspect_ratios=["16:9", "9:16", "1:1"],
                min_bitrate=2000,
                recommended_duration=(60.0, 300.0),
            ),
            content_rules=ContentRule(
                min_title_length=5,
                max_title_length=80,
                min_description_length=20,
                max_description_length=5000,
                required_tags_count=(3, 10),
            ),
            cover_size=(1920, 1080),
            recommended_tags=["影视剪辑", "预告", "解说"],
        ))

        cls.register(PlatformAdapter(
            platform=Platform.WECHAT,
            format_req=FormatRequirement(
                min_duration=1.0,
                max_duration=600.0,
                min_resolution=(720, 1280),
                aspect_ratios=["9:16", "16:9", "1:1"],
                min_bitrate=1000,
                recommended_duration=(15.0, 60.0),
            ),
            content_rules=ContentRule(
                min_title_length=5,
                max_title_length=64,
                min_description_length=0,
                max_description_length=2000,
                required_tags_count=(1, 10),
            ),
            cover_size=(1080, 1920),
            recommended_tags=["影视", "精彩"],
        ))

        cls.register(PlatformAdapter(
            platform=Platform.XIAOHONGSHU,
            format_req=FormatRequirement(
                min_duration=5.0,
                max_duration=300.0,
                min_resolution=(1080, 1350),
                aspect_ratios=["9:16", "1:1"],
                min_bitrate=2000,
                recommended_duration=(30.0, 90.0),
            ),
            content_rules=ContentRule(
                min_title_length=10,
                max_title_length=20,
                min_description_length=20,
                max_description_length=1000,
                required_tags_count=(3, 6),
            ),
            cover_size=(1080, 1920),
            recommended_tags=["影视推荐", "追剧", "好剧"],
        ))

        cls.register(PlatformAdapter(
            platform=Platform.YOUTUBE,
            format_req=FormatRequirement(
                min_duration=12.0,
                max_duration=43200.0,
                min_resolution=(1280, 720),
                aspect_ratios=["16:9", "9:16", "1:1"],
                min_bitrate=2500,
                recommended_duration=(480.0, 600.0),
            ),
            content_rules=ContentRule(
                min_title_length=5,
                max_title_length=100,
                min_description_length=100,
                max_description_length=5000,
                required_tags_count=(3, 15),
            ),
            cover_size=(1280, 720),
            recommended_tags=["movie", "clip", "trailer"],
        ))

        cls.register(PlatformAdapter(
            platform=Platform.INSTAGRAM,
            format_req=FormatRequirement(
                min_duration=3.0,
                max_duration=60.0,
                min_resolution=(1080, 1080),
                aspect_ratios=["1:1", "4:5", "9:16"],
                min_bitrate=2000,
                recommended_duration=(15.0, 30.0),
            ),
            content_rules=ContentRule(
                min_title_length=0,
                max_title_length=2200,
                min_description_length=0,
                max_description_length=2200,
                required_tags_count=(1, 30),
            ),
            cover_size=(1080, 1080),
            recommended_tags=["movie", "film", "edit"],
        ))


PlatformRegistry.initialize()


class PlatformChecker:
    """
    平台检查器
    
    统一检查视频是否符合目标平台要求
    """

    def __init__(self):
        self._registry = PlatformRegistry

    def check(
        self,
        platform: Platform,
        duration: float,
        resolution: Tuple[int, int],
        aspect_ratio: str,
        bitrate: int,
        file_size: int,
        title: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        全面检查视频是否符合平台要求

        Returns:
            {
                "passed": bool,
                "errors": [...],
                "warnings": [...],
                "info": [...],
                "suggestions": [...],
            }
        """
        adapter = self._registry.get(platform)
        if not adapter:
            return {
                "passed": False,
                "errors": [{"message": f"不支持的平台: {platform}"}],
                "warnings": [],
                "info": [],
                "suggestions": [],
            }

        all_results = []

        all_results.extend(adapter.check_video(
            duration, resolution, aspect_ratio, bitrate, file_size
        ))

        if title:
            all_results.extend(adapter.check_title(title))

        if description:
            all_results.extend(adapter.check_description(description))

        if tags:
            all_results.extend(adapter.check_tags(tags))

        errors = [r for r in all_results if r.level == ViolationLevel.ERROR]
        warnings = [r for r in all_results if r.level == ViolationLevel.WARNING]
        info = [r for r in all_results if r.level == ViolationLevel.INFO]
        suggestions = [r.suggestion for r in all_results if r.suggestion]

        return {
            "passed": len(errors) == 0,
            "errors": [
                {"message": r.message, "field": r.field, "suggestion": r.suggestion}
                for r in errors
            ],
            "warnings": [
                {"message": r.message, "field": r.field, "suggestion": r.suggestion}
                for r in warnings
            ],
            "info": [
                {"message": r.message, "field": r.field, "suggestion": r.suggestion}
                for r in info
            ],
            "suggestions": suggestions,
            "recommendation": self._get_recommendation(platform, len(errors), len(warnings)),
        }

    def _get_recommendation(
        self,
        platform: Platform,
        error_count: int,
        warning_count: int,
    ) -> str:
        """获取建议"""
        if error_count > 0:
            return "存在致命错误，请修复后再发布"
        elif warning_count > 2:
            return "存在多个警告，建议优化后发布"
        elif warning_count > 0:
            return "存在少量警告，可以发布但推荐优化"
        else:
            return "符合平台要求，可以发布"

    def get_platform_info(self, platform: Platform) -> Optional[Dict[str, Any]]:
        """获取平台信息"""
        adapter = self._registry.get(platform)
        if not adapter:
            return None

        return {
            "name": platform.value,
            "format": {
                "duration_range": f"{adapter.format_req.min_duration}s - {adapter.format_req.max_duration}s",
                "recommended_duration": f"{adapter.format_req.recommended_duration[0]}s - {adapter.format_req.recommended_duration[1]}s",
                "min_resolution": f"{adapter.format_req.min_resolution[0]}x{adapter.format_req.min_resolution[1]}",
                "aspect_ratios": adapter.format_req.aspect_ratios,
                "min_bitrate": f"{adapter.format_req.min_bitrate}kbps",
            },
            "content": {
                "title_range": f"{adapter.content_rules.min_title_length}-{adapter.content_rules.max_title_length}字",
                "description_range": f"{adapter.content_rules.min_description_length}-{adapter.content_rules.max_description_length}字",
                "tags_range": f"{adapter.content_rules.required_tags_count[0]}-{adapter.content_rules.required_tags_count[1]}个",
            },
            "cover_size": f"{adapter.cover_size[0]}x{adapter.cover_size[1]}",
            "recommended_tags": adapter.recommended_tags,
        }

    def list_platforms(self) -> List[Dict[str, Any]]:
        """列出所有平台信息"""
        return [
            {"id": p.value, "name": p.value}
            for p in self._registry.list_platforms()
        ]


_global_checker: Optional[PlatformChecker] = None


def get_platform_checker() -> PlatformChecker:
    """获取全局平台检查器"""
    global _global_checker
    if _global_checker is None:
        _global_checker = PlatformChecker()
    return _global_checker
