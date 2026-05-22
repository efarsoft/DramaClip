"""
Full Narration 流水线实现 - 全解说
"""

from typing import List, Dict, Optional

from app.services.clip.base import ClipPipeline
from app.services.narration.pipeline import NarrationPipeline as LegacyNarrationPipeline


class FullNarrationPipelineImpl(ClipPipeline):
    """
    全解说流水线
    
    完全使用 AI 解说替换原声，适合原声质量较差或需要全新配音的场景
    """
    
    @property
    def scheme(self) -> str:
        return "full_narration"
    
    @property
    def name(self) -> str:
        return "全解说"
    
    @property
    def description(self) -> str:
        return "完全使用 AI 解说替换原声，全新配音体验"
    
    def run(
        self,
        video_paths: List[str],
        output_path: str,
        target_duration: Optional[int] = None,
        segments: Optional[List[Dict]] = None,
        **kwargs
    ) -> Dict:
        """
        执行全解说
        
        1. 解析剧情
        2. 生成解说文案
        3. 语音合成
        4. 剪辑原片
        5. 音画替换（完全使用解说音）
        """
        self.validate_inputs(video_paths)
        
        pipeline = LegacyNarrationPipeline()
        
        if not output_path:
            output_path = pipeline.direct_cut_pipeline._generate_output_path(video_paths[0])
        
        final_path = pipeline.run(
            video_paths,
            output_path=output_path,
            target_duration=target_duration,
            mix_mode="replace",
        )
        
        return {
            "output_path": final_path,
            "mode": "full",
            "mix_mode": "replace",
        }
