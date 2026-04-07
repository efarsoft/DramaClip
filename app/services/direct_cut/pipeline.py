"""
DramaClip - 原片直剪模式流水线

原片直剪模式的完整处理链路：
输入(多集视频) → 预处理 → 镜头分割 → ASR转写 → 高光打分筛选 → 排序
→ 竖屏裁剪(人脸居中) → 字幕叠加 → 原声保留拼接 → 输出MP4

特点：保留原片全部音频（人物原声、背景音、BGM），不添加任何额外音频。
"""

import os
import json
import re
import uuid
from typing import List, Optional, Dict, Callable, Any
from loguru import logger

from app.models.schema import (
    SceneSegment, ClipMode, DramaClipOutputConfig,
    HighlightConfig, HighlightScoreWeights
)
from app.services.highlight.scene_detect import SceneDetector, detect_all_episodes
from app.services.highlight.scorer import HighlightScorer
from app.services.highlight.selector import HighlightSelector
from app.services.sorter.scene_sorter import SceneSorter
from app.utils.srt_utils import seconds_to_srt_time, parse_srt_time, create_simple_srt, concat_srt_files
from app.utils.video_utils import generate_video_cover


class DirectCutPipeline:
    """
    原片直剪流水线
    
    使用方式：
        pipeline = DirectCutPipeline()
        result = pipeline.run(
            video_paths=["ep1.mp4", "ep2.mp4"],
            output_duration=30,
            progress_callback=my_callback
        )
        # result.output_path -> 最终成片路径
    """
    
    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        
        # 初始化各模块
        highlight_cfg = HighlightConfig(
            weights=HighlightScoreWeights(**{
                "audio_weight": self.config.get("audio_weight", 0.4),
                "emotion_weight": self.config.get("emotion_weight", 0.3),
                "visual_weight": self.config.get("visual_weight", 0.2),
                "rhythm_weight": self.config.get("rhythm_weight", 0.1),
            }),
            top_ratio=self.config.get("top_ratio", 0.3),
            min_segment_duration=self.config.get("min_segment_duration", 2.0),
            max_segments_per_episode=self.config.get("max_segments_per_episode", 5),
            min_episodes_covered=self.config.get("min_episodes_covered", 1),
        )
        
        self.detector = SceneDetector(
            threshold=self.config.get("scene_threshold", 30),
            min_scene_len=highlight_cfg.min_segment_duration,
            max_scene_len=8.0,
        )
        self.scorer = HighlightScorer(highlight_cfg)
        self.selector = HighlightSelector(highlight_cfg)
        self.sorter = SceneSorter()
        
        # 输出目录
        self.temp_dir = self._get_temp_dir()
    
    def run(self,
            video_paths: List[str],
            output_duration: int = 30,
            output_dir: Optional[str] = None,
            progress_callback: Optional[Callable[[float, str], None]] = None
            ) -> Dict[str, Any]:
        """
        执行完整的原片直剪流程
        
        Args:
            video_paths: 输入视频文件路径列表
            output_duration: 目标输出时长(秒)
            output_dir: 输出目录
            progress_callback: 进度回调 (progress_01, message)
            
        Returns:
            dict: {
                "output_path": 成品路径,
                "segments_count": 片段数,
                "total_duration": 总时长,
                "cover_path": 封面路径,
                ...
            }
        """
        task_id = str(uuid.uuid4())[:8]
        output_dir = output_dir or self.temp_dir
        
        def progress(pct, msg):
            if progress_callback:
                progress_callback(pct, f"[直剪-{task_id}] {msg}")
        
        logger.info(f"[{task_id}] 开始原片直剪模式 | {len(video_paths)}集 | 目标时长:{output_duration}s")
        
        try:
            # ===== Phase 1: 预处理 + 镜头分割 =====#
            progress(0.05, "正在预处理和镜头分割...")
            scene_infos = detect_all_episodes(
                video_paths,
                config={
                    "threshold": self.config.get("scene_threshold", 30),
                    "min_scene_len": self.config.get("min_segment_duration", 2.0),
                    "max_scene_len": 8.0,
                },
                progress_callback=lambda p, m: progress(0.05 + 0.15 * p, m)
            )
            
            # 转换为 SceneSegment 对象
            segments = [self._info_to_segment(info) for info in scene_infos]
            
            # ===== Phase 2: 提取片段音频/字幕 =====#
            progress(0.20, "正在提取音频和字幕...")
            segments = self._extract_media(segments, 
                                           lambda p, m: progress(0.20 + 0.10 * p, m))
            
            # ===== Phase 3: 高光打分 =====#
            progress(0.32, "正在进行高光打分分析...")
            scored_results = self.scorer.score_segments(
                segments,
                progress_callback=lambda p, m: progress(0.32 + 0.18 * p, m)
            )
            
            # 更新 segments（scorer 已修改 in-place）
            
            # ===== Phase 4: 筛选高光片段 =====#
            progress(0.52, "正在筛选最优高光片段...")
            selected_segments = self.selector.select(
                scored_results,
                target_duration=output_duration,
                progress_callback=lambda p, m: progress(0.52 + 0.08 * p, m)
            )
            
            # ===== Phase 5: 智能排序 =====#
            progress(0.62, "正在智能排序...")
            sorted_segments = self.sorter.sort(selected_segments)
            
            # 排序质量分析
            quality = self.sorter.analyze_sorting_quality(sorted_segments)
            logger.info(f"排序质量: {quality}")
            
            # ===== Phase 6: 裁剪+拼接+输出 =====#
            progress(0.68, "正在裁剪拼接生成成片...")
            output_info = self._assemble_video(
                sorted_segments,
                output_dir=output_dir,
                output_duration=output_duration,
                task_id=task_id,
                progress_callback=lambda p, m: progress(0.68 + 0.27 * p, m)
            )
            
            progress(1.0, f"完成! 成片已生成: {os.path.basename(output_info['output_path'])}")
            
            # 返回结果
            result = {
                "task_id": task_id,
                "mode": "direct_cut",
                "output_path": output_info["output_path"],
                "cover_path": output_info.get("cover_path"),
                "segments_count": len(sorted_segments),
                "segments_total_duration": round(sum(s.duration for s in sorted_segments), 1),
                "target_duration": output_duration,
                "episodes_covered": len(set(s.episode_index for s in sorted_segments)),
                "avg_score": round(
                    sum(s.total_score or 0 for s in sorted_segments) / max(1, len(sorted_segments)), 3
                ),
                "sorting_quality": quality,
            }
            
            logger.info(f"[{task_id}] 原片直剪完成: {result}")
            return result
            
        except Exception as e:
            logger.exception(f"[{task_id}] 原片直剪失败: {e}")
            raise
    
    def _info_to_segment(self, info) -> SceneSegment:
        """将 SceneInfo 转换为 SceneSegment"""
        return SceneSegment(
            segment_id=info.to_segment_id(),
            episode_index=info.episode_index,
            start_time=info.start_time,
            end_time=info.end_time,
            duration=info.duration,
            video_path=info.video_path,
        )
    
    def _extract_media(self, 
                        segments: List[SceneSegment],
                        progress_callback=None) -> List[SceneSegment]:
        """为每个片段提取音频文件"""
        from app.utils import ffmpeg_utils
        
        extract_dir = os.path.join(self.temp_dir, "extracts")
        os.makedirs(extract_dir, exist_ok=True)
        
        for i, seg in enumerate(segments):
            if progress_callback:
                progress_callback((i + 1) / len(segments), f"提取 E{seg.episode_index} 片段音频...")
            
            try:
                base_name = seg.segment_id.replace(".", "_")
                
                # 提取音频
                audio_out = os.path.join(extract_dir, f"{base_name}.wav")
                if not os.path.exists(audio_out):
                    success = ffmpeg_utils.extract_audio(
                        seg.video_path,
                        audio_out,
                        start_time=seg.start_time,
                        duration=seg.duration,
                    )
                    if success and os.path.exists(audio_out):
                        seg.audio_path = audio_out
                
                # 裁剪视频片段
                clip_out = os.path.join(extract_dir, f"{base_name}.mp4")
                if not os.path.exists(clip_out):
                    success = ffmpeg_utils.clip_video(
                        seg.video_path,
                        clip_out,
                        start_time=seg.start_time,
                        duration=seg.duration,
                    )
                    if success and os.path.exists(clip_out):
                        seg.video_path = clip_out  # 更新为裁剪后的片段
                        
            except Exception as e:
                logger.warning(f"媒体提取失败 ({seg.segment_id}): {e}")
        
        return segments
    
    def _assemble_video(self,
                         segments: List[SceneSegment],
                         output_dir: str,
                         output_duration: int,
                         task_id: str,
                         progress_callback=None) -> dict:
        """
        组装最终成片：
        1. 竖屏9:16裁剪 + 人脸居中
        2. 字幕叠加（ASR结果）
        3. 原声保留拼接
        4. 封面生成
        """
        from app.services.generate_video import merge_materials
        from app.utils import ffmpeg_utils
        
        output_filename = f"dramaclip_directcut_{task_id}.mp4"
        output_path = os.path.join(output_dir, output_filename)
        
        if not segments:
            return {"output_path": output_path, "error": "no_segments"}
        
        # ===== 1. 逐片段竖屏裁剪 =====#
        crop_dir = os.path.join(output_dir, "cropped")
        os.makedirs(crop_dir, exist_ok=True)
        
        cropped_paths = []
        for i, seg in enumerate(segments):
            if progress_callback:
                progress_callback((i + 1) / len(segments), f"竖屏裁剪 {i+1}/{len(segments)}...")
            
            cropped_path = os.path.join(crop_dir, f"crop_{seg.segment_id}.mp4")
            
            try:
                # 人脸居中裁剪为 1080x1920 (9:16)
                success = ffmpeg_utils.crop_to_portrait_face_centered(
                    input_path=seg.video_path,
                    output_path=cropped_path,
                    target_width=1080,
                    target_height=1920,
                )
                if success and os.path.exists(cropped_path):
                    cropped_paths.append({
                        "path": cropped_path,
                        "segment": seg,
                    })
                else:
                    # fallback：简单居中裁剪
                    fallback_path = cropped_path.replace(".mp4", "_fallback.mp4")
                    ffmpeg_utils.crop_to_portrait_centered(
                        seg.video_path,
                        fallback_path,
                        width=1080,
                        height=1920,
                    )
                    if os.path.exists(fallback_path):
                        cropped_paths.append({"path": fallback_path, "segment": seg})
                        
            except Exception as e:
                logger.warning(f"裁剪失败 ({seg.segment_id}): {e}, 使用原始片段")
                cropped_paths.append({"path": seg.video_path, "segment": seg})
        
        if not cropped_paths:
            return {"output_path": output_path, "error": "no_cropped_segments"}
        
        # ===== 2. 合并所有片段 =====#
        concat_list_path = os.path.join(output_dir, f"concat_list_{task_id}.txt")
        with open(concat_list_path, 'w', encoding='utf-8') as f:
            for item in cropped_paths:
                f.write(f"file '{item['path']}'\n")
        
        merged_path = os.path.join(output_dir, f"merged_{task_id}.mp4")
        if not ffmpeg_utils.concat_videos(concat_list_path, merged_path):
            return {"output_path": output_path, "error": "concat_failed"}
        
        # ===== 3. 音量均衡处理 =====#
        normalized_path = os.path.join(output_dir, f"normalized_{task_id}.mp4")
        from app.services.audio_normalizer import AudioNormalizer
        normalizer = AudioNormalizer()
        normalizer.normalize_audio_lufs(merged_path, normalized_path)
        
        # 如果归一化成功则使用，否则用合并版本
        final_video = normalized_path if os.path.exists(normalized_path) else merged_path
        
        # ===== 4. 字幕叠加（如果有ASR字幕）=====#
        # 收集所有片段的字幕并合并
        srt_merged = self._merge_subtitles(segments, output_dir, task_id)
        
        if srt_merged and os.path.exists(srt_merged):
            subtitled_path = os.path.join(output_dir, f"subtitled_{task_id}.mp4")
            try:
                merge_materials(
                    video_path=final_video,
                    audio_path="",  # 视频自带音频
                    output_path=subtitled_path,
                    subtitle_path=srt_merged,
                    options={
                        "keep_original_audio": True,
                        "original_audio_volume": 1.0,
                        "subtitle_enabled": True,
                        "subtitle_font_size": 40,
                        "subtitle_color": "#FFFFFF",
                        "stroke_color": "#000000",
                        "stroke_width": 2,
                        "subtitle_position": "bottom",
                        "fps": 25,
                    }
                )
                if os.path.exists(subtitled_path):
                    final_video = subtitled_path
            except Exception as e:
                logger.warning(f"字幕叠加失败: {e}，使用无字幕版本")
        
        # ===== 5. 复制到最终输出路径 =====#
        import shutil
        shutil.copy2(final_video, output_path)
        
        # ===== 6. 生成封面 =====#
        cover_path = self._generate_cover(segments, output_dir, task_id)
        
        return {
            "output_path": output_path,
            "cover_path": cover_path,
            "segments_processed": len(segments),
        }
    
    def _merge_subtitles(self, 
                          segments: List[SceneSegment],
                          output_dir: str,
                          task_id: str) -> Optional[str]:
        """合并所有选中片段的字幕为统一SRT文件"""
        # 直接用简单的 SRT 拼接方式，避免依赖 subtitle_merger 的复杂接口
        srt_files = []
        time_offset = 0.0
        
        for seg in segments:
            if seg.subtitle_srt_path and os.path.exists(seg.subtitle_srt_path):
                srt_files.append(seg.subtitle_srt_path)
            elif seg.subtitle_text:
                # 从文本创建临时SRT
                temp_srt = os.path.join(output_dir, f"temp_sub_{seg.segment_id}.srt")
                self._create_simple_srt(seg.subtitle_text, time_offset, seg.duration, temp_srt)
                srt_files.append(temp_srt)
            
            time_offset += seg.duration
        
        if not srt_files:
            return None
        
        merged_path = os.path.join(output_dir, f"merged_subs_{task_id}.srt")
        
        try:
            # 手动合并 SRT 文件（按时间偏移拼接）
            self._concat_srt_files(srt_files, merged_path)
            return merged_path if os.path.exists(merged_path) else None
        except Exception as e:
            logger.warning(f"字幕合并失败: {e}")
            return None
    
    def _concat_srt_files(self, srt_files: List[str], output_path: str):
        """手动拼接多个 SRT 文件，处理时间偏移"""
        # 使用公共 SRT 工具函数
        concat_srt_files(srt_files, output_path)
    
    def _parse_srt_time(self, srt_time_str: str) -> float:
        """将 SRT 时间字符串转换为秒数（委托给公共模块）"""
        return parse_srt_time(srt_time_str)
    
    def _create_simple_srt(self, text: str, start: float, duration: float, output_path: str):
        """创建简单的SRT字幕文件（委托给公共模块）"""
        create_simple_srt(text, start, duration, output_path)
    
    @staticmethod
    def _seconds_to_srt_time(seconds: float) -> str:
        """将秒数转换为 SRT 时间字符串（委托给公共模块）"""
        return seconds_to_srt_time(seconds)
    
    def _generate_cover(self, 
                         segments: List[SceneSegment],
                         output_dir: str,
                         task_id: str) -> Optional[str]:
        """从得分最高的片段帧生成封面（使用公共工具函数）"""
        return generate_video_cover(segments, output_dir, task_id)
    
    def _get_temp_dir(self) -> str:
        """获取临时工作目录"""
        from app.utils import utils
        base = utils.temp_dir()
        work_dir = os.path.join(base, "dramaclip_work")
        os.makedirs(work_dir, exist_ok=True)
        return work_dir
