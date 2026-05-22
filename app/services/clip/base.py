"""
视频剪辑流水线基类和注册器
使用命令模式实现可扩展的剪辑流水线架构
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Type
from pathlib import Path
import tempfile


class ClipPipeline(ABC):
    """
    剪辑流水线抽象基类
    
    所有具体的剪辑流水线必须继承此类并实现 run 方法
    """
    
    @property
    @abstractmethod
    def scheme(self) -> str:
        """剪辑方案标识"""
        pass
    
    @property
    @abstractmethod
    def name(self) -> str:
        """用户友好的名称"""
        pass
    
    @property
    def description(self) -> str:
        """方案描述"""
        return ""
    
    @abstractmethod
    def run(
        self,
        video_paths: List[str],
        output_path: str,
        target_duration: Optional[int] = None,
        segments: Optional[List[Dict]] = None,
        **kwargs
    ) -> Dict:
        """
        执行剪辑流水线
        
        Args:
            video_paths: 视频文件路径列表
            output_path: 输出文件路径
            target_duration: 目标时长（秒）
            segments: 预选片段列表
            **kwargs: 其他参数
            
        Returns:
            包含 output_path 等信息的字典
        """
        pass
    
    def _generate_output_path(self, video_path: str, suffix: str = "") -> str:
        """生成输出文件路径"""
        input_path = Path(video_path)
        output_dir = input_path.parent / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = Path(tempfile.mktemp(suffix=""))
        suffix_part = f"_{suffix}" if suffix else ""
        output_file = output_dir / f"{input_path.stem}{suffix_part}{input_path.suffix}"
        
        return str(output_file)
    
    def validate_inputs(self, video_paths: List[str]) -> None:
        """验证输入参数"""
        if not video_paths:
            raise ValueError("video_paths cannot be empty")
        
        for path in video_paths:
            p = Path(path)
            if not p.exists():
                raise FileNotFoundError(f"Video file not found: {path}")


class PipelineRegistry:
    """
    流水线注册器
    
    管理所有可用的剪辑流水线，支持动态注册和获取
    """
    
    _pipelines: Dict[str, ClipPipeline] = {}
    _initialized: bool = False
    
    @classmethod
    def register(cls, pipeline: ClipPipeline) -> None:
        """
        注册一个剪辑流水线
        
        Args:
            pipeline: ClipPipeline 实例
        """
        if pipeline.scheme in cls._pipelines:
            import warnings
            warnings.warn(
                f"Pipeline scheme '{pipeline.scheme}' already registered. "
                f"Overwriting with {pipeline.__class__.__name__}"
            )
        
        cls._pipelines[pipeline.scheme] = pipeline
        cls._initialized = True
    
    @classmethod
    def get(cls, scheme: str) -> ClipPipeline:
        """
        获取指定方案的流水线
        
        Args:
            scheme: 剪辑方案标识
            
        Returns:
            对应的 ClipPipeline 实例
            
        Raises:
            KeyError: 如果指定的方案不存在
        """
        if scheme not in cls._pipelines:
            available = ", ".join(cls._pipelines.keys())
            raise KeyError(
                f"Unknown pipeline scheme: '{scheme}'. "
                f"Available schemes: {available}"
            )
        return cls._pipelines[scheme]
    
    @classmethod
    def list_schemes(cls) -> List[str]:
        """列出所有已注册的方案"""
        return list(cls._pipelines.keys())
    
    @classmethod
    def list_pipelines(cls) -> List[Dict]:
        """获取所有流水线的信息"""
        return [
            {
                "scheme": p.scheme,
                "name": p.name,
                "description": p.description,
            }
            for p in cls._pipelines.values()
        ]
    
    @classmethod
    def unregister(cls, scheme: str) -> bool:
        """
        取消注册指定方案
        
        Args:
            scheme: 剪辑方案标识
            
        Returns:
            是否成功取消注册
        """
        if scheme in cls._pipelines:
            del cls._pipelines[scheme]
            return True
        return False
    
    @classmethod
    def clear(cls) -> None:
        """清除所有注册的流水线"""
        cls._pipelines.clear()
        cls._initialized = False
    
    @classmethod
    def is_initialized(cls) -> bool:
        """检查是否已初始化"""
        return cls._initialized


def register_all_pipelines():
    """
    注册所有内置流水线
    
    此函数应该在应用启动时调用
    """
    from app.services.clip.pipelines.direct_cut import DirectCutPipelineImpl
    from app.services.clip.pipelines.hybrid_narration import HybridNarrationPipelineImpl
    from app.services.clip.pipelines.full_narration import FullNarrationPipelineImpl
    
    PipelineRegistry.register(DirectCutPipelineImpl())
    PipelineRegistry.register(HybridNarrationPipelineImpl())
    PipelineRegistry.register(FullNarrationPipelineImpl())
