"""
AI解说管道 - 完整的AI解说模式流水线
结合大模型剧情解说生成、TTS语音合成、声音避让混音与智能画面裁剪

M1 优化（2026-05）：
- 添加 Narration 结果缓存（segments + mix_mode 维度）
- 尝试使用 response_format=json 提升结构化输出成功率
- 显著降低重复生成相同高光片段时的 LLM 调用成本和延迟
"""

import os
import json
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Callable, Any

from loguru import logger

from app.services.clip.modular_direct_cut import ModularDirectCutPipeline
from app.services.project.manager_sqlite import get_manager
from app.services.llm.unified_service import UnifiedLLMService
from app.services.llm.migration_adapter import _run_async_safely
from app.utils.json_utils import parse_and_fix_json
from .cache import get_narration_cache  # M1 优化：Narration 结果缓存
from app.services.prompts.manager import PromptManager  # M1 优化：统一 prompt 管理
from app.services.clip.clip_video import clip_video_unified_multi
from app.utils.ffmpeg import smart_crop, to_portrait, concat_videos
from app.utils.path_manager import get_path_manager
from app.utils import utils
import app.services.voice as voice


def format_seconds_to_hmsm(seconds: float) -> str:
    """将秒数格式化为 HH:MM:SS,ms"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    if ms >= 1000:
        ms = 999
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


class NarrationPipeline:
    """AI解说流水线"""

    def __init__(self, config: dict = None):
        self.config = config or {}
        # 使用模块化原片直剪作为高光片段选取的基础组件
        self.direct_cut_pipeline = ModularDirectCutPipeline(config)
        self.narration_mode = "hybrid"  # 默认值
        logger.info("NarrationPipeline initialized (与智能画面裁剪及去重引擎深度结合)")

    def run(
        self,
        video_paths: List[str],
        output_path: str,
        target_duration: Optional[int] = None,
        segments: Optional[List[Dict[str, Any]]] = None,
        mix_mode: str = "overlay",
        task_id: Optional[str] = None,
        progress_callback: Optional[Callable[[str, int, str], None]] = None,
        crop_mode: str = "smart",
        target_ratio: str = "9:16",
        project_name: Optional[str] = None,
        narration_mode: str = "hybrid",  # Phase 1 新增：支持模式传递
        **kwargs
    ) -> str:
        """
        执行完整的AI解说流水线
        """
        if progress_callback is None:
            progress_callback = lambda stage, progress, message: None

        # 1. 初始化与片段选取 (0% - 20%)
        progress_callback("narration_init", 5, "正在初始化解说流水线...")
        logger.info(f"[Narration] Starting narration pipeline for project {project_name or 'default'}")

        if not segments:
            logger.info("[Narration] No pre-selected segments, running highlight selector...")
            segments = self.direct_cut_pipeline.run_segments_only(
                video_paths, target_duration=target_duration
            )

        if not segments:
            raise RuntimeError("未检测到任何高光候选片段，无法生成解说视频")

        # 确保 task_id 有效
        if not task_id:
            task_id = hashlib.md5(output_path.encode()).hexdigest()

        # Phase 1 新增：记录当前模式
        self.narration_mode = narration_mode or "hybrid"

        # 创建任务目录
        task_dir_path = utils.task_dir(task_id)
        os.makedirs(task_dir_path, exist_ok=True)

        # 2. 比对语音识别(ASR)文本并聚合成片段上下文 (20% - 30%)
        progress_callback("asr_alignment", 15, "正在匹配语音转写(ASR)对白上下文...")
        
        # 获取项目ID（即 project_name）
        project_id = project_name
        videos = []
        if project_id:
            try:
                manager = get_manager()
                videos = manager.get_videos(project_id)
                logger.info(f"[Narration] Loaded {len(videos)} videos from project database")
            except Exception as e:
                logger.warning(f"[Narration] Failed to load videos from project DB: {e}")

        # 比对 ASR
        for idx, seg in enumerate(segments):
            seg_video_path = seg.get("video_path") or (video_paths[0] if video_paths else "")
            
            # 匹配对应视频的ID以加载 ASR.json
            video_id = None
            if videos:
                for v in videos:
                    if os.path.basename(v.path) == os.path.basename(seg_video_path):
                        video_id = v.id
                        break
            
            # 加载 ASR 文本
            joined_text = ""
            if video_id:
                asr_file = Path.home() / ".dramaclip" / "analysis" / project_id / video_id / "asr.json"
                if asr_file.exists():
                    try:
                        asr_data = json.loads(asr_file.read_text(encoding="utf-8"))
                        asr_segs = asr_data.get("segments", [])
                        seg_start = seg.get("start_time") or seg.get("start") or 0.0
                        seg_end = seg.get("end_time") or seg.get("end") or 0.0
                        
                        overlapping_texts = []
                        for asr_s in asr_segs:
                            as_start = asr_s.get("start", 0.0)
                            as_end = asr_s.get("end", 0.0)
                            # 判断时间交叉
                            if max(seg_start, as_start) < min(seg_end, as_end):
                                overlapping_texts.append(asr_s.get("text", "").strip())
                        
                        joined_text = " ".join([t for t in overlapping_texts if t])
                    except Exception as e:
                        logger.warning(f"[Narration] Failed to read ASR segments: {e}")

            # 写入段落对白
            seg["transcript"] = joined_text or seg.get("subtitle_text") or "无对白动作画面"

        # ==================== 聚合全量 ASR 为剧情梗概 ====================
        all_asr_texts = []
        if project_id and videos:
            for v in videos:
                asr_file = Path.home() / ".dramaclip" / "analysis" / project_id / v.id / "asr.json"
                if asr_file.exists():
                    try:
                        asr_data = json.loads(asr_file.read_text(encoding="utf-8"))
                        for seg_asr in asr_data.get("segments", []):
                            t = seg_asr.get("text", "").strip()
                            if t:
                                all_asr_texts.append(t)
                    except Exception as e:
                        logger.warning(f"[Narration] Failed to read full ASR for video {v.id}: {e}")

        plot_synopsis = " ".join(all_asr_texts) if all_asr_texts else ""

        # 超长文本压缩（>20000字符时调用 LLM 摘要，中短剧通常 8000-15000 字直接传原文）
        if len(plot_synopsis) > 20000:
            try:
                progress_callback("asr_synopsis", 20, "正在生成全剧剧情梗概...")
                summary_prompt = (
                    "请将以下短剧的全部对白文本压缩为一段 1500 字以内的剧情梗概，"
                    "保留核心人物关系、关键冲突转折和剧情走向：\n\n"
                    f"{plot_synopsis[:40000]}"
                )
                plot_synopsis = _run_async_safely(
                    UnifiedLLMService.generate_text,
                    prompt=summary_prompt,
                    system_prompt="你是一位短剧剧情分析师，擅长用精炼的语言概括剧情。",
                    max_tokens=800,
                    temperature=0.3,
                )
                logger.info(f"[Narration] ASR synopsis compressed: {len(plot_synopsis)} chars")
            except Exception as e:
                logger.warning(f"[Narration] Synopsis compression failed, using truncated: {e}")
                plot_synopsis = plot_synopsis[:20000]

        if plot_synopsis:
            logger.info(f"[Narration] Plot synopsis ready: {len(plot_synopsis)} chars")
        else:
            logger.warning("[Narration] No ASR data available, plot_synopsis is empty")
        # ==================== 剧情梗概聚合结束 ====================

        # 3. 大模型解说词脚本生成 (30% - 50%)
        progress_callback("llm_generation", 30, "正在调用大语言模型策划专属解说词...")
        
        drama_name = "精彩短剧"
        if project_id:
            try:
                project = get_manager().get_project(project_id)
                if project:
                    drama_name = project.name
            except Exception as e:
                logger.warning(f"[Narration] Failed to load project metadata: {e}")

        # M1 优化：使用统一 PromptManager 生成提示词
        prompt_segments = []
        for idx, seg in enumerate(segments):
            start = seg.get("start_time") or seg.get("start") or 0.0
            end = seg.get("end_time") or seg.get("end") or 0.0
            prompt_segments.append({
                "_id": idx,
                "duration": round(end - start, 2),
                "original_dialogue": seg.get("transcript"),
                "scene_description": seg.get("reason") or "高光爆点画面"
            })

        mix_mode_description = (
            "混合解说 (overlay)：AI 解说与原声混合，保留关键对话，当有重要原声台词时，可以保留原声(OST=1)"
            if mix_mode == "overlay"
            else "全片解说 (replace)：完全使用 AI 解说替换原声，建议主要使用解说(OST=2)"
        )

        try:
            user_prompt = PromptManager.get_prompt(
                category="short_drama_narration",
                name="highlight_narration",
                parameters={
                    "drama_name": drama_name,
                    "plot_synopsis": plot_synopsis or "无可用剧情文本",
                    "mix_mode_description": mix_mode_description,
                    "segments": json.dumps(prompt_segments, ensure_ascii=False, indent=2)
                }
            )
        except Exception as e:
            logger.warning(f"[Narration] Failed to load managed prompt, falling back to inline prompt: {e}")
            # 简单兜底（生产环境建议保留完整旧 prompt）
            user_prompt = f"请为短剧《{drama_name}》生成高光解说脚本，segments: {json.dumps(prompt_segments, ensure_ascii=False)}"

        # ==================== M1 优化：Narration LLM 调用优化 ====================
        # 1. 先尝试缓存命中（最高优先级）
        cache = get_narration_cache()
        script_data = cache.get(segments, mix_mode, drama_name)

        if script_data:
            logger.info(f"[Narration] 使用缓存的解说脚本 (segments={len(segments)}, mix_mode={mix_mode})")
        else:
            # 2. 缓存未命中 → 调用 LLM（已做到单次合并请求）
            logger.info(f"[Narration] Requesting LLM narration script for {len(segments)} segments (no cache)...")
            try:
                # 优先尝试结构化输出（如果模型支持）
                response = _run_async_safely(
                    UnifiedLLMService.generate_text,
                    prompt=user_prompt,
                    system_prompt="你是一名精通短剧解说与文案配音的资深自媒体人。你的输出必须是裸 JSON 字符串，绝对不要包含任何代码块符号或Markdown标记。",
                    max_tokens=1500,
                    temperature=0.8,
                    response_format="json"   # 尝试让模型直接返回 JSON
                )

                # 清理 Markdown 代码块
                cleaned_response = response.strip()
                if cleaned_response.startswith("```json"):
                    cleaned_response = cleaned_response[7:]
                if cleaned_response.endswith("```"):
                    cleaned_response = cleaned_response[:-3]
                cleaned_response = cleaned_response.strip()

                script_data = parse_and_fix_json(cleaned_response)
                logger.info(f"[Narration] Successfully parsed LLM script items: {script_data}")

                # 3. 成功后写入缓存
                if script_data and "items" in script_data:
                    cache.set(segments, mix_mode, drama_name, script_data)

                # ==================== 成片级文案打磨阶段（新） ====================
                # 在初稿生成成功后，自动进行全局打磨，提升故事性和语言质感
                if script_data and "items" in script_data:
                    try:
                        progress_callback("narration_refinement", 42, "正在进行成片级文案打磨...")
                        refined_data = self._refine_script_globally(
                            drama_name=drama_name,
                            mix_mode=mix_mode,
                            plot_synopsis=plot_synopsis,
                            original_segments=prompt_segments,
                            initial_script=script_data
                        )
                        if refined_data and "items" in refined_data:
                            script_data = refined_data
                            logger.info("[Narration] 成片级打磨完成，质量已提升")
                    except Exception as refine_err:
                        logger.warning(f"[Narration] 成片级打磨失败，保留初稿: {refine_err}")
                # ==================== 打磨阶段结束 ====================

            except Exception as e:
                logger.error(f"[Narration] LLM narration generation failed: {e}. Falling back to default script.")
                script_data = None
        # ==================== M1 优化结束 ====================

        # 备用方案：生成默认的旁白
        if not script_data or "items" not in script_data:
            logger.warning("[Narration] Using placeholder narration generation due to parse or call failures.")
            script_data = {
                "items": [
                    {
                        "_id": idx,
                        "OST": 2 if mix_mode == "overlay" else 0,
                        "narration": seg.get("reason") or f"接下来进入精彩的高潮桥段！"
                    }
                    for idx, seg in enumerate(segments)
                ]
            }

        # 4. 构建统一的剪辑描述清单并做时间戳格式化 (50% - 60%)
        progress_callback("formatting_script", 50, "正在整理剪辑时间轴与解说字幕文本...")
        
        script_list = []
        tts_segments = []
        
        # 建立 LLM 结果到原 segment 的映射
        llm_items = {item["_id"]: item for item in script_data.get("items", []) if "_id" in item}

        for idx, seg in enumerate(segments):
            start = seg.get("start_time") or seg.get("start") or 0.0
            end = seg.get("end_time") or seg.get("end") or 0.0
            dur = max(0.5, end - start)
            
            # 获取 LLM 生成结果
            llm_item = llm_items.get(idx)
            ost_type = llm_item.get("OST", 2) if llm_item else (2 if mix_mode == "overlay" else 0)
            narration_text = llm_item.get("narration", "精彩画面不容错过") if llm_item else "精彩画面不容错过"
            
            # 若 narration_text 为“播放原片”且为 1，则确实使用原片
            if ost_type == 1 or "播放原片" in narration_text:
                ost_type = 1
                narration_text = "播放原片"

            # 对应视频索引
            video_idx = 0
            if seg.get("video_path") in video_paths:
                video_idx = video_paths.index(seg.get("video_path"))

            # 格式化时间戳字符串，供 clip_video_unified_multi 内部解析
            timestamp_str = f"{format_seconds_to_hmsm(start)}-{format_seconds_to_hmsm(end)}"

            script_item = {
                "_id": idx,
                "episode": video_idx,
                "timestamp": timestamp_str,
                "narration": narration_text,
                "OST": ost_type,
                "picture": seg.get("reason") or "高光镜头",
            }
            script_list.append(script_item)
            
            # 如果不是纯原声，需要加入 TTS 配音生成队列
            if ost_type != 1:
                tts_segments.append(script_item)

        # 5. 执行 TTS 配音语音合成 (60% - 70%)
        progress_callback("tts_synthesis", 60, "正在调用高音质TTS语音合成引擎...")
        
        # 加载项目级 TTS 设置，若缺失则回退到 config.toml [tts] 全局配置
        tts_section = {}
        if project_id:
            try:
                project = get_manager().get_project(project_id)
                if project and project.settings:
                    settings = project.settings
                    # 现代结构
                    tts_section = settings.get("tts") or {}
                    # 兼容旧扁平结构
                    if not tts_section:
                        tts_section = {
                            "engine": settings.get("tts_engine"),
                            "voice": settings.get("voice_name"),
                            "speed": settings.get("voice_rate"),
                            "pitch": settings.get("voice_pitch"),
                        }
                    logger.info(f"[Narration] Loaded TTS settings: engine={tts_section.get('engine')}")
            except Exception as e:
                logger.warning(f"[Narration] Failed to read project settings for TTS: {e}")

        # 若项目设置为空，再回退到 config.toml 全局 [tts] 配置
        if not tts_section:
            try:
                from app.config.unified_config import get_config
                global_cfg = get_config()
                global_tts = global_cfg.get("tts", {}) if hasattr(global_cfg, 'get') else {}
                if global_tts:
                    tts_section = {
                        "engine": global_tts.get("engine"),
                        "voice": global_tts.get("voice"),
                    }
                    logger.info(f"[Narration] Fallback to global TTS config: engine={tts_section.get('engine')}")
            except Exception:
                pass

        # 默认引擎：本地 Kokoro（轻量快速），用户可在设置中切换为其他方案
        raw_engine = tts_section.get("engine") or "kokoro"

        # 前端有时传 "edge"，后端 voice.py 用 "edge_tts"
        tts_engine = "edge_tts" if raw_engine in ("edge", "edge_tts") else raw_engine
        voice_name = tts_section.get("voice") or "zf_001"
        voice_rate = float(tts_section.get("speed") or tts_section.get("voice_rate") or 1.0)
        voice_pitch = float(tts_section.get("pitch") or tts_section.get("voice_pitch") or 1.0)

        logger.info(f"[Narration] Final TTS: engine={tts_engine}, voice={voice_name}")

        # 调用统一的 tts_multiple
        tts_results = []
        if tts_segments:
            logger.info(f"[Narration] Synthesizing voiceover for {len(tts_segments)} segments...")
            tts_results = voice.tts_multiple(
                task_id=task_id,
                list_script=tts_segments,
                voice_name=voice_name,
                voice_rate=voice_rate,
                voice_pitch=voice_pitch,
                tts_engine=tts_engine
            )
            logger.info(f"[Narration] TTS synthesis completed with {len(tts_results)} audio files")

        # 6. 音画混合与裁剪 (70% - 90%)
        progress_callback("video_clipping", 72, "正在精准对齐音轨并处理高光镜头...")
        
        # 利用后台最核心、最成熟的音轨混合、时间戳对齐与声音避让模块进行处理
        raw_cut_results = clip_video_unified_multi(
            episode_paths=video_paths,
            script_list=script_list,
            tts_results=tts_results,
            task_id=task_id
        )

        # 7. 应用智能裁剪(9:16)、视觉微调变速去重并最终拼接 (90% - 100%)
        progress_callback("smart_crop", 90, "正在进行画面智能裁剪与全局视频无缝合并...")
        
        path_mgr = get_path_manager()
        temp_dir = path_mgr.create_temp_dir(prefix="narration_portrait_", delete_on_exit=True)

        portrait_paths = []
        for idx in range(len(script_list)):
            slice_path = raw_cut_results.get(idx)
            if not slice_path or not os.path.exists(slice_path):
                logger.warning(f"[Narration] Sliced video for segment {idx} failed or missing")
                continue

            portrait_path = os.path.join(temp_dir, f"portrait_{idx:03d}.mp4")
            
            # 为每个独立切片生成唯一的微变速与视觉微调去重参数
            from app.utils.ffmpeg import generate_dedup_params
            dedup_p = generate_dedup_params()
            logger.info(f"[Narration] Segment {idx} dedup parameters: {dedup_p}")

            # 根据裁剪模式选择不同的裁剪方法
            if crop_mode == "smart":
                smart_crop(
                    slice_path,
                    portrait_path,
                    target_ratio=target_ratio,
                    crop_position="smart",
                    dedup_params=dedup_p
                )
            else:
                to_portrait(slice_path, portrait_path, dedup_params=dedup_p)

            portrait_paths.append(portrait_path)

        if not portrait_paths:
            raise RuntimeError("没有成功生成任何带有解说人声的竖屏片段")

        # 最终合并！
        logger.info(f"[Narration] Merging {len(portrait_paths)} portrait slices into final output: {output_path}")
        concat_videos(portrait_paths, output_path)

        # 8. 完成清理
        try:
            for p in portrait_paths:
                if os.path.exists(p):
                    os.remove(p)
        except Exception:
            pass

    # ==================== 成片级文案打磨方法（新增） ====================
    def _refine_script_globally(
        self,
        drama_name: str,
        mix_mode: str,
        plot_synopsis: str,
        original_segments: list,
        initial_script: dict
    ) -> dict:
        """
        对初稿解说脚本进行成片级打磨。
        目标：提升故事连贯性、情绪节奏，降低油腻感和AI味。
        失败时返回 None，由调用方保留初稿。
        """
        try:
            from app.services.prompts.manager import PromptManager
            from app.services.llm.migration_adapter import _run_async_safely
            from app.services.llm.unified_service import UnifiedLLMService

            mix_desc = (
                "混合解说（AI解说与原声混合）" if mix_mode == "overlay"
                else "全片解说（主要使用AI旁白）"
            )

            refinement_prompt = PromptManager.get_prompt(
                category="short_drama_narration",
                name="narration_refinement",
                parameters={
                    "drama_name": drama_name,
                    "plot_synopsis": plot_synopsis or "无可用剧情文本",
                    "mix_mode": mix_desc,
                    "original_segments": json.dumps(original_segments, ensure_ascii=False, indent=2),
                    "initial_script": json.dumps(initial_script, ensure_ascii=False, indent=2)
                }
            )

            response = _run_async_safely(
                UnifiedLLMService.generate_text,
                prompt=refinement_prompt,
                system_prompt="你是一位专业的短剧解说总监，擅长把初稿打磨成自然高级的成片文案。输出必须是严格合法的 JSON。",
                max_tokens=1600,
                temperature=0.6,
                response_format="json"
            )

            cleaned = response.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()

            refined = parse_and_fix_json(cleaned)
            if refined and "items" in refined:
                return refined
            return None

        except Exception as e:
            logger.warning(f"[Narration] 成片级打磨调用异常: {e}")
            return None
    # ==================== 打磨方法结束 ====================

        progress_callback("completed", 100, "AI智能解说与配音生成剪辑已全部完成！")
        logger.info(f"[Narration] Narration Pipeline run successfully completed! Output: {output_path}")
        return output_path
