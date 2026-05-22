"""
Hybrid Narration 流水线实现 - 混合解说
"""

from typing import List, Dict, Optional

from app.services.clip.base import ClipPipeline
from app.services.narration.pipeline import NarrationPipeline as LegacyNarrationPipeline


class HybridNarrationPipelineImpl(ClipPipeline):
    """
    混合解说流水线
    
    AI 解说与原片声音混合播放，适合保留部分对话的场景
    """
    
    @property
    def scheme(self) -> str:
        return "hybrid_narration"
    
    @property
    def name(self) -> str:
        return "混合解说"
    
    @property
    def description(self) -> str:
        return "AI 解说与原声混合，保留关键对话"
    
    def run(
        self,
        video_paths: List[str],
        output_path: str,
        target_duration: Optional[int] = None,
        segments: Optional[List[Dict]] = None,
        **kwargs
    ) -> Dict:
        """
        执行混合解说
        
        1. 解析剧情
        2. 生成解说文案
        3. 语音合成
        4. 剪辑原片
        5. 音画混合（保留原声）
        """
        self.validate_inputs(video_paths)
        
        pipeline = LegacyNarrationPipeline()
        
        if not output_path:
            output_path = pipeline.direct_cut_pipeline._generate_output_path(video_paths[0])
        
        final_path = pipeline.run(
            video_paths,
            output_path=output_path,
            target_duration=target_duration,
            mix_mode="overlay",
        )
        
        return {
            "output_path": final_path,
            "mode": "hybrid",
            "mix_mode": "overlay",
        }
