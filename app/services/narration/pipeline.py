"""
DramaClip - AI解说模块

AI解说模式的核心处理逻辑：
1. 剧情解析（基于ASR台词 + LLM）
2. 解说文案生成（多风格）
3. TTS语音合成
4. 音画对齐与合成
"""

import os
import json
import re
import uuid
from typing import List, Optional, Dict, Callable, Any
from loguru import logger

from app.models.schema import SceneSegment, NarrationScript


class PlotParser:
    """
    剧情解析器
    
    基于ASR转写的全剧台词，结合镜头画面分析结果，
    通过LLM解析剧情脉络，提取核心冲突、反转、高潮节点。
    """
    
    def __init__(self, llm_config: Optional[dict] = None):
        self.llm_config = llm_config or {}
    
    def parse(self,
              segments: List[SceneSegment],
              drama_name: str = "",
              progress_callback=None) -> dict:
        """
        解析完整剧情
        
        Args:
            segments: 所有镜头片段（需包含 subtitle_text）
            drama_name: 剧名
            progress_callback: 进度回调
            
        Returns:
            dict: {
                "summary": "100~200字剧情摘要",
                "key_moments": [
                    {"type": "conflict", "description": "...", "segment_id": "..."},
                    {"type": "reversal", ...},
                    {"type": "climax", ...},
                ],
                "characters": ["角色A", "角色B"],
                "main_conflict": "主线冲突描述",
                "tags": ["复仇", "爱情", "悬疑"],
            }
        """
        if progress_callback:
            progress_callback(0.1, "正在收集台词内容...")
        
        # 收集所有台词文本
        all_text = []
        for seg in sorted(segments, key=lambda s: (s.episode_index, s.start_time)):
            if seg.subtitle_text:
                ep_marker = f"[E{seg.episode_index} {seg.start_time:.0f}s]"
                all_text.append(f"{ep_marker}: {seg.subtitle_text}")
        
        full_transcript = "\n".join(all_text)
        
        if not full_transcript.strip():
            return {
                "summary": "无法获取台词内容，请检查ASR转写结果。",
                "key_moments": [],
                "characters": [],
                "main_conflict": "",
                "tags": [],
                "error": "no_transcript",
            }
        
        if progress_callback:
            progress_callback(0.3, "正在调用AI解析剧情...")
        
        try:
            from app.services.llm.unified_service import UnifiedLLMService
            
            llm = UnifiedLLMService()
            
            prompt = self._build_plot_analysis_prompt(
                full_transcript, 
                drama_name,
                len(set(s.episode_index for s in segments))
            )
            
            response = llm.chat_completion(
                messages=[
                    {"role": "system", "content": "你是一个专业的短剧剧情分析师。请分析短剧的剧情结构、关键节点和情感走向。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.5,
            )
            
            result_text = response.get("content", "") if isinstance(response, dict) else str(response)
            
            # 解析结果为结构化数据
            parsed = self._parse_llm_result(result_text)
            
            if progress_callback:
                progress_callback(1.0, "剧情解析完成!")
            
            return parsed
            
        except Exception as e:
            logger.error(f"剧情解析失败: {e}")
            return {
                "summary": f"剧情解析失败: {str(e)}",
                "key_moments": [],
                "characters": [],
                "main_conflict": "",
                "tags": [],
                "error": str(e),
            }
    
    def _build_plot_analysis_prompt(self, 
                                     transcript: str, 
                                     drama_name: str,
                                     episode_count: int) -> str:
        """构建剧情分析的提示词"""
        max_chars = 8000
        truncated = transcript[:max_chars]
        if len(transcript) > max_chars:
            truncated += "\n...(内容已截断)"
        
        return f"""请分析以下{episode_count}集短剧的剧情内容。

剧名：{drama_name or "未知"}

完整的字幕/台词内容如下：
---
{truncated}
---

请以JSON格式返回分析结果，包含以下字段：{{
    "summary": "100-200字的剧情摘要，概括主要故事线",
    "characters": ["主要角色列表"],
    "main_conflict": "一句话描述核心冲突",
    "tags": ["类型标签如：复仇/爱情/悬疑/豪门等"],
    "key_moments": [
        {{
            "type": "conflict|reversal|climax|emotional|setup",
            "episode": 集数(int),
            "time_approx": 大约时间点(string),
            "description": "该节点描述",
            "intensity": 情绪强度1-10(int)
        }}
    ],
    "tone": "整体基调(紧张/温馨/虐心/爽文等)",
    "target_audience": "目标观众"
}}

只返回JSON，不要其他文字。"""

    def _parse_llm_result(self, result_text: str) -> dict:
        """
        解析 LLM 返回的 JSON 结果为结构化数据
        
        容错处理：LLM 可能返回非标准 JSON，需要多种策略解析
        """
        text = result_text.strip()
        
        # 策略 1: 直接尝试解析整个文本
        try:
            data = json.loads(text)
            return self._validate_plot_result(data)
        except json.JSONDecodeError:
            pass
        
        # 策略 2: 提取 ```json...``` 代码块
        json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(1).strip())
                return self._validate_plot_result(data)
            except json.JSONDecodeError:
                pass
        
        # 策略 3: 找到第一个 { 到最后一个 }
        start_idx = text.find('{')
        end_idx = text.rfind('}')
        if start_idx != -1 and end_idx > start_idx:
            try:
                data = json.loads(text[start_idx:end_idx + 1])
                return self._validate_plot_result(data)
            except json.JSONDecodeError:
                pass
        
        # 全部失败，返回降级结果
        logger.warning("无法解析LLM剧情分析结果为JSON，返回原始文本")
        return {
            "summary": text[:500] if text else "AI未能返回有效结果",
            "key_moments": [],
            "characters": [],
            "main_conflict": "",
            "tags": [],
            "raw_response": text[:2000],
            "error": "parse_failed",
        }

    @staticmethod
    def _validate_plot_result(data: dict) -> dict:
        """验证并补全剧情解析结果，确保所有必要字段存在"""
        return {
            "summary": str(data.get("summary", ""))[:500],
            "key_moments": data.get("key_moments", [])[:15],
            "characters": data.get("characters", [])[:20],
            "main_conflict": str(data.get("main_conflict", ""))[:200],
            "tags": data.get("tags", [])[:10],
            "tone": data.get("tone", ""),
            "target_audience": data.get("target_audience", ""),
        }


class NarrationGenerator:
    """
    解说文案生成器
    
    根据剧情解析结果和高光片段顺序，生成贴合画面的解说文案。
    支持多种风格。
    """
    
    STYLES = {
        "normal": "常规解说：客观叙述剧情，清晰易懂",
        "satire": "吐槽风：幽默吐槽，个性鲜明，有感染力",
        "concise": "简洁风：言简意赅，节奏快，信息密集",
        "emotional": "情感风：代入感强，情绪渲染到位",
    }
    
    def __init__(self, style: str = "normal"):
        self.style = style
    
    def generate(self,
                  plot_analysis: dict,
                  selected_segments: List[SceneSegment],
                  target_duration: int = 30,
                  progress_callback=None) -> NarrationScript:
        """
        生成解说文案
        
        Args:
            plot_analysis: 剧情解析结果
            selected_segments: 选中的高光片段
            target_duration: 目标时长(秒)
            
        Returns:
            NarrationScript: 解说文案对象
        """
        if progress_callback:
            progress_callback(0.1, "正在生成解说文案...")
        
        try:
            from app.services.llm.unified_service import UnifiedLLMService
            
            llm = UnifiedLLMService()
            
            prompt = self._build_script_prompt(
                plot_analysis, 
                selected_segments, 
                target_duration
            )
            
            response = llm.chat_completion(
                messages=[
                    {"role": "system", "content": self._get_system_prompt()},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.8,
            )
            
            result_text = response.get("content", "") if isinstance(response, dict) else str(response)
            
            # 解析为 NarrationScript
            script = self._parse_script(result_text, target_duration)
            
            if progress_callback:
                progress_callback(1.0, f"解说文案生成完成! 共 {len(script.segments)} 段")
            
            return script
            
        except Exception as e:
            logger.error(f"解说文案生成失败: {e}")
            return NarrationScript(
                title="解说文案生成失败",
                full_text=f"错误: {str(e)}",
                style=self.style,
                segments=[],
            )
    
    def _get_system_prompt(self) -> str:
        style_desc = self.STYLES.get(self.style, self.STYLES["normal"])
        
        return f"""你是一个专业的短视频解说文案写手。当前风格设定：{style_desc}

写作要求：
1. 语言口语化、自然流畅，像在跟朋友聊天
2. 开头前3句必须抓住注意力（悬念/冲突/反问）
3. 关键情节点要重点强调，适当使用"注意看""就在这时""没想到"
4. 文案时长要与目标视频长度匹配（约每秒2-3个中文字）
5. 避免AI味：不要用"首先...其次...最后"，不要过度排比
6. 每段文案对应一个画面片段，标注对应的时间位置

格式要求：
返回JSON格式，包含title（标题）、segments（分段文案列表）、full_text（完整文本）。"""
    
    def _build_script_prompt(self,
                               analysis: dict,
                               segments: List[SceneSegment],
                               duration: int) -> str:
        """构建文案生成提示词"""
        timeline = []
        current_time = 0.0
        for seg in segments:
            seg_info = {
                "index": len(timeline) + 1,
                "episode": seg.episode_index,
                "start_in_video": round(current_time, 1),
                "duration": round(seg.duration, 1),
                "original_time": f"E{seg.episode_index} {seg.start_time:.0f}s-{seg.end_time:.0f}s",
                "subtitle_preview": (seg.subtitle_text or "")[:80],
                "score": seg.total_score,
            }
            timeline.append(seg_info)
            current_time += seg.duration
        
        key_moments_str = json.dumps(
            analysis.get("key_moments", [])[:8], 
            ensure_ascii=False,
            indent=2
        )
        timeline_str = json.dumps(timeline, ensure_ascii=False, indent=2)
        
        return f"""请根据以下信息生成解说文案：

## 基本信息
- 目标输出时长: {duration}秒（约{int(duration*2.5)}字）
- 文案风格: {self.style}

## 剧情概览
- 摘要: {analysis.get('summary', 'N/A')[:300]}
- 核心冲突: {analysis.get('main_conflict', 'N/A')}
- 基调: {analysis.get('tone', 'N/A')}

## 关键剧情节点
```json
{key_moments_str}
```

## 高光片段时间线（按播放顺序）
```json
{timeline_str}
```

## 要求
请为每个高光片段生成对应的解说文案。每段文案应该：
1. 与该画面的内容匹配
2. 承接上段文案，保持叙事连贯
3. 在关键节点处加强语气
4. 控制总时长接近目标时长

返回JSON格式：{{"title":"标题","segments":[{{"timestamp":秒,"text":"文案","emphasis":bool}}],"full_text":"完整文案"}}"""

    def _parse_script(self, result_text: str, target_duration: int) -> NarrationScript:
        """
        解说 LLM 返回的解说文案 JSON 为 NarrationScript 对象
        
        Args:
            result_text: LLM 原始返回文本
            target_duration: 目标时长（用于校验）
            
        Returns:
            NarrationScript 对象
        """
        text = result_text.strip()
        data = None
        
        # 策略 1: 直接解析
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            pass
        
        # 策略 2: 提取代码块
        if data is None:
            json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
            if json_match:
                try:
                    data = json.loads(json_match.group(1).strip())
                except json.JSONDecodeError:
                    pass
        
        # 策略 3: 花括号提取
        if data is None:
            start_idx = text.find('{')
            end_idx = text.rfind('}')
            if start_idx != -1 and end_idx > start_idx:
                try:
                    data = json.loads(text[start_idx:end_idx + 1])
                except json.JSONDecodeError:
                    pass
        
        # 全部失败时降级
        if data is None:
            logger.warning("无法解析解说文案JSON，使用原始文本")
            return NarrationScript(
                title="AI解说文案",
                full_text=text[:2000],
                style=self.style,
                segments=[],
            )
        
        # 构建 segments 列表
        segments_raw = data.get("segments", [])
        segments = []
        for seg in segments_raw:
            if isinstance(seg, dict):
                segments.append({
                    "timestamp": float(seg.get("timestamp", 0)),
                    "text": str(seg.get("text", "")),
                    "emphasis": bool(seg.get("emphasis", False)),
                })
            elif isinstance(seg, str):
                # 兼容纯字符串格式
                segments.append({"timestamp": 0, "text": seg, "emphasis": False})
        
        title = data.get("title", "AI解说文案")
        full_text = data.get("full_text", "")
        
        # 如果没有 full_text，从 segments 拼接
        if not full_text and segments:
            full_text = " ".join(s["text"] for s in segments)
        elif not full_text:
            full_text = text[:2000]
        
        return NarrationScript(
            title=title,
            full_text=full_text,
            style=self.style,
            segments=segments,
        )


class TTSComposer:
    """
    TTS语音合成管理器
    
    将生成的解说文案合成为自然语音，
    支持多种TTS引擎和音色选择。
    """
    
    def __init__(self, tts_engine: str = "edge_tts", voice_config: Optional[dict] = None):
        self.tts_engine = tts_engine
        self.voice_config = voice_config or {}
    
    def compose(self,
                 script: NarrationScript,
                 output_dir: str,
                 task_id: str = "",
                 progress_callback=None) -> str:
        """
        合成TTS语音
        
        Args:
            script: 解说文案对象
            output_dir: 输出目录
            task_id: 任务ID
            
        Returns:
            str: 合成的音频文件路径
        """
        os.makedirs(output_dir, exist_ok=True)
        
        # 使用 voice.py 的 tts() 函数（NarratoAI 已有的 TTS 能力）
        from app.services.voice import tts
        
        output_path = os.path.join(output_dir, f"narration_audio_{task_id}.mp3")
        
        voice_name = self.voice_config.get("voice_name", "zh-CN-XiaoyiNeural")
        rate = self.voice_config.get("rate", 1.0)
        pitch = self.voice_config.get("pitch", 1.0)
        
        sub_maker = tts(
            text=script.full_text,
            voice_name=voice_name,
            voice_rate=rate,
            voice_pitch=pitch,
            voice_file=output_path,
            tts_engine=self.tts_engine,
        )
        
        if sub_maker is not None and os.path.exists(output_path):
            if progress_callback:
                progress_callback(1.0, "TTS合成完成!")
            return output_path
        else:
            raise RuntimeError(f"TTS合成未产出音频文件: {output_path}")


# ===== AI解说模式主流水线入口 =====#

class NarrationPipeline:
    """
    AI解说模式流水线
    
    完整流程：输入 → 预处理 → 高光打分筛选排序 
    → 剧情解析 → 文案生成 → TTS合成 → 音画合成 → 输出
    """
    
    def __init__(self):
        """初始化，预创建 DirectCutPipeline 避免重复初始化"""
        from app.services.direct_cut.pipeline import DirectCutPipeline
        self._direct_cut_pipeline = DirectCutPipeline()
    
    def run(self,
            video_paths: List[str],
            output_duration: int = 30,
            narration_style: str = "normal",
            output_dir: Optional[str] = None,
            progress_callback=None) -> Dict[str, Any]:
        """
        执行AI解说模式的完整流程
        
        复用 DirectCutPipeline 的预处理+打分+筛选排序部分，
        在此基础上增加：剧情解析 → 文案生成 → TTS → 音画合成
        """
        from app.services.highlight.scene_detect import detect_all_episodes
        
        task_id = str(uuid.uuid4())[:8]
        output_dir = output_dir or self._get_temp_dir()
        os.makedirs(output_dir, exist_ok=True)
        
        def progress(pct, msg):
            if progress_callback:
                progress_callback(pct, f"[解说-{task_id}] {msg}")
        
        logger.info(f"[{task_id}] 开始AI解说模式 | {len(video_paths)}集 | 风格:{narration_style}")
        
        try:
            # ===== Phase 1-5: 复用直剪流水线的预处理到排序部分 =====#
            pipeline = self._direct_cut_pipeline
            
            progress(0.05, "正在执行预处理和高光分析...")
            scene_infos = detect_all_episodes(video_paths, config={
                "threshold": pipeline.config.get("scene_threshold", 30),
                "min_scene_len": pipeline.config.get("min_segment_duration", 2.0),
                "max_scene_len": 8.0,
            }, progress_callback=lambda p, m: progress(0.05 + 0.20 * p, m))
            
            segments = [pipeline._info_to_segment(info) for info in scene_infos]
            segments = pipeline._extract_media(segments, lambda p, m: progress(0.25 + 0.08 * p, m))
            scored_results = pipeline.scorer.score_segments(segments, 
                                                           lambda p, m: progress(0.33 + 0.15 * p, m))
            selected_segments = pipeline.selector.select(scored_results, output_duration,
                                                         lambda p, m: progress(0.48 + 0.06 * p, m))
            sorted_segments = pipeline.sorter.sort(selected_segments)
            
            # ===== Phase 6: 剧情解析 =====#
            progress(0.56, "正在AI解析剧情...")
            plot_parser = PlotParser()
            plot_analysis = plot_parser.parse(sorted_segments, progress_callback=
                                              lambda p, m: progress(0.56 + 0.12 * p, m))
            
            # ===== Phase 7: 解说文案生成 =====#
            progress(0.70, "正在生成解说文案...")
            script_gen = NarrationGenerator(style=narration_style)
            narration_script = script_gen.generate(
                plot_analysis, sorted_segments, output_duration,
                lambda p, m: progress(0.70 + 0.10 * p, m)
            )
            
            # ===== Phase 8: TTS语音合成 =====#
            progress(0.82, "正在合成解说语音...")
            tts_composer = TTSComposer(tts_engine="edge_tts")
            narration_audio = tts_composer.compose(
                narration_script, output_dir, task_id,
                lambda p, m: progress(0.82 + 0.06 * p, m)
            )
            
            # ===== Phase 9: 音画合成（原片静音+解说叠加）=====#
            progress(0.90, "正在进行音画合成...")
            final_output = self._assemble_with_narration(
                sorted_segments=sorted_segments,
                narration_audio=narration_audio,
                narration_script=narration_script,
                output_dir=output_dir,
                output_path=os.path.join(output_dir, f"dramaclip_narration_{task_id}.mp4"),
                task_id=task_id,
                progress_callback=lambda p, m: progress(0.90 + 0.09 * p, m)
            )
            
            progress(1.0, f"完成! AI解说成片已生成")
            
            result = {
                "task_id": task_id,
                "mode": "ai_narration",
                "output_path": final_output.get("output_path"),
                "cover_path": final_output.get("cover_path"),
                "narration_style": narration_style,
                "script_title": narration_script.title,
                "script_text": narration_script.full_text[:200],
                "segments_count": len(sorted_segments),
                "plot_summary": plot_analysis.get("summary", ""),
            }
            
            logger.info(f"[{task_id}] AI解说完成: {result}")
            return result
            
        except Exception as e:
            logger.exception(f"[{task_id}] AI解说模式失败: {e}")
            raise
    
    def _assemble_with_narration(self,
                                  sorted_segments: List[SceneSegment],
                                  narration_audio: str,
                                  narration_script: NarrationScript,
                                  output_dir: str,
                                  output_path: str,
                                  task_id: str,
                                  progress_callback=None) -> dict:
        """AI解说的最终合成：竖屏裁剪 + 原片静音 + 解说音频 + 双字幕"""
        from app.services.generate_video import merge_materials
        from app.utils import ffmpeg_utils
        from app.utils.video_utils import generate_video_cover
        from app.utils.srt_utils import seconds_to_srt_time, create_simple_srt
        
        # 1. 裁剪所有选中片段为竖屏（复用直剪的逻辑）
        crop_dir = os.path.join(output_dir, "cropped_n")
        os.makedirs(crop_dir, exist_ok=True)
        
        cropped_paths = []
        for i, seg in enumerate(sorted_segments):
            if progress_callback:
                progress_callback((i + 1) / len(sorted_segments) * 0.4, 
                                  f"裁剪片段 {i + 1}/{len(sorted_segments)}")
            
            cropped_path = os.path.join(crop_dir, f"ncrop_{seg.segment_id}.mp4")
            try:
                # 优先使用 clip_path（裁剪片段），否则用原始 video_path
                input_video = getattr(seg, 'clip_path', None) or seg.video_path
                ffmpeg_utils.crop_to_portrait_face_centered(
                    input_video, cropped_path, 1080, 1920
                )
                if os.path.exists(cropped_path):
                    cropped_paths.append(cropped_path)
            except Exception as e:
                logger.warning(f"裁剪失败 ({seg.segment_id}): {e}, 使用原片段")
                cropped_paths.append(getattr(seg, 'clip_path', None) or seg.video_path)
        
        # 2. 合并视频片段
        concat_file = os.path.join(output_dir, f"concat_n_{task_id}.txt")
        with open(concat_file, 'w') as f:
            for p in cropped_paths:
                f.write(f"file '{p}'\n")
        
        merged_video = os.path.join(output_dir, f"merged_n_{task_id}.mp4")
        ffmpeg_utils.concat_videos(concat_file, merged_video)
        
        # 3. 最终合成：视频 + 解说音频(主) + 原声降低(背景) + 双字幕
        narration_srt = self._generate_narration_srt(narration_script, output_dir, task_id,
                                                      seconds_to_srt_time)
        
        try:
            merge_materials(
                video_path=merged_video,
                audio_path=narration_audio,
                output_path=output_path,
                subtitle_path=narration_srt,
                bgm_path=None,
                options={
                    "keep_original_audio": True,
                    "original_audio_volume": 0.15,
                    "voice_volume": 1.0,
                    "subtitle_enabled": True,
                    "subtitle_font_size": 38,
                    "subtitle_color": "#FFFFFF",
                    "stroke_color": "#000000",
                    "stroke_width": 2,
                    "fps": 25,
                }
            )
        except Exception as e:
            logger.warning(f"高级合成失败，尝试简单混合: {e}")
            # fallback: 使用 ffmpeg_utils 中的 mix_audio_video
            from app.utils import ffmpeg_utils
            ffmpeg_utils.mix_audio_video(merged_video, narration_audio, output_path,
                                          original_audio_volume=0.15)
        
        # 4. 生成封面（使用公共工具函数）
        cover = generate_video_cover(sorted_segments, output_dir, task_id)
        
        return {"output_path": output_path, "cover_path": cover}

    @staticmethod
    def _generate_narration_srt(script, output_dir, task_id, time_formatter) -> str:
        """从解说文案生成SRT字幕
        
        字幕时长根据文本长度动态计算（约2.5字/秒），
        而非固定5秒，确保字幕与语音同步。
        """
        CHARS_PER_SECOND = 2.5  # 中文语速参考值
        MIN_SUB_DURATION = 2.0  # 最短字幕时长
        MAX_SUB_DURATION = 10.0  # 最长字幕时长
        
        srt_path = os.path.join(output_dir, f"narration_subs_{task_id}.srt")
        with open(srt_path, 'w', encoding='utf-8') as f:
            for i, seg in enumerate(script.segments):
                ts = getattr(seg, 'timestamp', i * 5) if hasattr(seg, 'timestamp') else seg.get('timestamp', i * 5)
                text = getattr(seg, 'text', '') if hasattr(seg, 'text') else seg.get('text', '')
                
                # 动态计算字幕时长：文本长度 / 语速
                char_count = len(text.replace(' ', '').replace('\n', ''))
                estimated_duration = max(MIN_SUB_DURATION, 
                                        min(MAX_SUB_DURATION, char_count / CHARS_PER_SECOND))
                
                start_hms = time_formatter(float(ts))
                end_hms = time_formatter(float(ts) + estimated_duration)
                f.write(f"{i + 1}\n{start_hms} --> {end_hms}\n{text}\n\n")
        return srt_path

    @staticmethod
    def _mix_video_audio_fallback(video_path: str, audio_path: str, output_path: str,
                                   original_audio_volume: float = 0.15):
        """
        使用 FFmpeg 简单混合视频和音频（fallback 方式）
        
        当 merge_materials 不可用时，直接用 ffmpeg 滤镜混合
        """
        import subprocess
        
        # 构建音量滤镜：保留原声降低到指定比例，叠加解说音频全量
        volume_filter = f"[0:a]volume={original_audio_volume}[orig];[1:a]volume=1.0[narr];[orig][narr]amix=inputs=2:duration=first:dropout_transition=2[outa]"
        
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", audio_path,
            "-filter_complex", volume_filter,
            "-map", "0:v",
            "-map", "[outa]",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            output_path,
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode != 0:
                logger.error(f"ffmpeg fallback 混合失败: {result.stderr[-500:] if result.stderr else 'unknown'}")
            else:
                logger.info("ffmpeg fallback 混合成功")
        except Exception as e:
            logger.error(f"ffmpeg fallback 执行异常: {e}")

    @staticmethod
    def _get_temp_dir() -> str:
        """获取临时工作目录"""
        from app.utils import utils
        d = os.path.join(utils.temp_dir(), "dramaclip_work")
        os.makedirs(d, exist_ok=True)
        return d
