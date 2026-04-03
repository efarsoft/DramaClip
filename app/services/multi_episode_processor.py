#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""
DramaClip 多集短剧统一处理流程

核心设计思路（方案一：逐集处理）:
  1. 逐集 ASR + 关键帧提取，各自独立分析
  2. 合并全剧分析结果，一次性 LLM 决策高光（感知集数，高光均匀分配）
  3. 逐集裁剪视频片段（每个片段标注来自哪一集）
  4. 合并所有精华片段 → 最终合成

与单集模式的区别:
  - script_list 每个 item 多了 episode 字段（从 0 开始）
  - clip_video_unified_multi 支持 episode 路由（哪个 episode 就裁哪个视频）
  - 最终 concat 时按 script_list 顺序拼接
"""

import os
import json
import asyncio
import re
from typing import List, Dict, Any, Optional, Callable
from loguru import logger

from app.models.schema import VideoClipParams
from app.models import const
from app.services import state as sm
from app.services import voice
from app.services import audio_merger
from app.services import subtitle_merger
from app.services import merger_video
from app.services import generate_video
from app.services import update_script
from app.services.clip_video import clip_video_unified_multi
from app.config.audio_config import AudioConfig, get_recommended_volumes_for_content
from app.utils import utils, video_processor
from app.config import config


def _natural_sort_key(s: str):
    """自然排序 key"""
    parts = re.split(r'(\d+)', s)
    return [int(p) if p.isdigit() else p.lower() for p in parts]


async def _extract_keyframes_multi(
    episode_paths: List[str],
    skip_seconds: int = 0,
    threshold: int = 30,
    progress_callback: Optional[Callable[[float, str], None]] = None,
) -> Dict[int, List[str]]:
    """
    批量提取多集关键帧

    Returns:
        { episode_index: [keyframe_path, ...] }
    """
    if progress_callback is None:
        progress_callback = lambda p, m: None

    result = {}
    total = len(episode_paths)

    for i, ep_path in enumerate(episode_paths):
        ep_idx = i  # 0-based
        ep_name = os.path.basename(ep_path)
        progress_callback(
            5 + 15 * i / total,
            f"提取第 {i+1}/{total} 集关键帧: {ep_name}"
        )

        video_hash = utils.md5(ep_path + str(os.path.getmtime(ep_path)))
        ep_keyframes_dir = os.path.join(
            utils.temp_dir(), "keyframes_multi", video_hash
        )

        # 检查缓存
        cached = []
        if os.path.exists(ep_keyframes_dir):
            for fname in sorted(os.listdir(ep_keyframes_dir)):
                if fname.endswith('.jpg'):
                    cached.append(os.path.join(ep_keyframes_dir, fname))
        if cached:
            logger.info(f"[多集] E{i+1} 使用缓存关键帧: {len(cached)} 张")
            result[ep_idx] = cached
            continue

        os.makedirs(ep_keyframes_dir, exist_ok=True)
        try:
            processor = video_processor.VideoProcessor(ep_path)
            processor.process_video_pipeline(
                output_dir=ep_keyframes_dir,
                skip_seconds=skip_seconds,
                threshold=threshold
            )
            frames = sorted([
                os.path.join(ep_keyframes_dir, f)
                for f in os.listdir(ep_keyframes_dir)
                if f.endswith('.jpg')
            ])
            result[ep_idx] = frames
            logger.info(f"[多集] E{i+1} 提取关键帧: {len(frames)} 张")
        except Exception as e:
            logger.error(f"[多集] E{i+1} 关键帧提取失败: {e}")
            result[ep_idx] = []

    return result


async def _analyze_all_frames_multi(
    episode_keyframes: Dict[int, List[str]],
    video_theme: str,
    custom_prompt: str,
    vision_llm_provider: str,
    progress_callback: Optional[Callable[[float, str], None]] = None,
) -> str:
    """
    使用 LLM 分析所有集的关键帧，返回完整的帧描述文本
    包含 episode 上下文信息
    """
    if progress_callback is None:
        progress_callback = lambda p, m: None

    from app.services.llm.migration_adapter import create_vision_analyzer

    vision_api_key = config.app.get(f'vision_{vision_llm_provider}_api_key')
    vision_model = config.app.get(f'vision_{vision_llm_provider}_model_name')
    vision_base_url = config.app.get(f'vision_{vision_llm_provider}_base_url')

    if not vision_api_key or not vision_model:
        raise ValueError(f"未配置 {vision_llm_provider} API Key 或模型")

    analyzer = create_vision_analyzer(
        provider=vision_llm_provider,
        api_key=vision_api_key,
        model=vision_model,
        base_url=vision_base_url
    )

    total_eps = len(episode_keyframes)
    total_frames = sum(len(v) for v in episode_keyframes.values())
    frame_analysis = ""

    flat_frames = []  # [(episode_idx, frame_path), ...]
    for ep_idx, frames in sorted(episode_keyframes.items()):
        flat_frames.extend([(ep_idx, f) for f in frames])

    # 逐帧分析（带 episode 标注）
    analyzed = 0
    batch_size = 5

    while analyzed < len(flat_frames):
        batch = flat_frames[analyzed:analyzed + batch_size]
        ep_idx = batch[0][0]
        ep_name = f"E{ep_idx + 1}"

        progress_callback(
            25 + 30 * analyzed / max(len(flat_frames), 1),
            f"分析 {ep_name} 帧 {analyzed + 1}~{analyzed + len(batch)}/{total_frames} ..."
        )

        frame_paths = [f[1] for f in batch]

        # 每个 episode 单独分析，避免跨集混淆
        prompt = config.app.get(
            'vision_analysis_prompt',
            f"描述这个短剧片段的画面内容、人物、动作、情绪。"
        )
        # 补充集数上下文
        prompt = (
            f"[{ep_name} / 共 {total_eps} 集]\n"
            f"视频主题: {video_theme}\n"
            f"{prompt}"
        )

        try:
            results = await analyzer.analyze_images(
                images=frame_paths,
                prompt=prompt,
                batch_size=len(frame_paths)
            )
            for r in results:
                if 'error' in r:
                    continue
                # 从文件名提取时间戳
                fname = os.path.basename(r.get('images', [''])[0])
                ts_match = re.search(r'(\d{2}:\d{2}:\d{2})', fname)
                ts = ts_match.group(1) if ts_match else "??:??"

                frame_analysis += (
                    f"\n=== [{ep_name}] {ts} ===\n"
                    f"{r['response']}\n"
                )
        except Exception as e:
            logger.warning(f"[多集] {ep_name} 帧分析异常: {e}")

        analyzed += len(batch)

    return frame_analysis


async def _generate_narration_script_multi(
    frame_analysis: str,
    episode_paths: List[str],
    video_theme: str,
    custom_prompt: str,
    target_duration: int = 30,
    progress_callback: Optional[Callable[[float, str], None]] = None,
) -> List[Dict[str, Any]]:
    """
    基于全剧帧分析，生成统一的高光解说脚本
    脚本中每个 clip 标注来自哪个 episode
    """
    if progress_callback is None:
        progress_callback = lambda p, m: None
    progress_callback(58, "生成高光解说脚本...")

    total_eps = len(episode_paths)

    # 构建 prompt：告知 LLM 有多少集，要求均匀分配高光
    system_prompt = (
        f"你是一名专业的短视频解说文案撰写专家。"
        f"当前短剧共 {total_eps} 集，需要从中挑选高光片段，"
        f"总输出时长控制在 {target_duration} 秒以内，"
        f"高光尽量均匀分布在各集，每集选取最精彩的 {max(1, target_duration // total_eps // 5)}~3 个片段。"
    )

    user_prompt = (
        f"视频主题: {video_theme}\n"
        f"{custom_prompt}\n\n"
        f"以下是各集关键帧分析结果：\n"
        f"{frame_analysis}\n\n"
        f"请从以上内容中挑选最精彩的高光片段（总时长 ≤ {target_duration} 秒），"
        f"均匀分配到 {total_eps} 集中，生成 JSON 格式的解说脚本。"
        f"每个片段需要包含: _id, episode(从0开始), timestamp(格式 HH:MM:SS-HH:MM:SS，本集内时间), "
        f"narration(解说文案), OST(0=纯解说,1=原声,2=混合，推荐用2保留现场感)。"
        f"请以JSON数组格式返回。"
    )

    # 使用文本 LLM 生成
    text_provider = config.app.get('text_llm_provider', 'openai').lower()
    text_api_key = config.app.get(f'text_{text_provider}_api_key')
    text_model = config.app.get(f'text_{text_provider}_model_name')
    text_base_url = config.app.get(f'text_{text_provider}_base_url')

    from openai import OpenAI
    client = OpenAI(api_key=text_api_key, base_url=text_base_url)

    try:
        response = client.chat.completions.create(
            model=text_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=1.2,
            response_format={"type": "json_object"}
        )
        content = response.choices[0].message.content
        # 清理 markdown 代码块
        content = re.sub(r'^```json\s*', '', content.strip())
        content = re.sub(r'\s*```$', '', content)
        result = json.loads(content)

        # 支持 {"clips": [...]} 或直接数组
        if isinstance(result, dict):
            if 'clips' in result:
                script_list = result['clips']
            else:
                # 取第一个 list 字段
                for v in result.values():
                    if isinstance(v, list):
                        script_list = v
                        break
                else:
                    raise ValueError(f"无法从 LLM 返回中解析脚本: {result}")
        elif isinstance(result, list):
            script_list = result
        else:
            raise ValueError(f"LLM 返回格式异常: {type(result)}")

        # 确保每个 item 有 episode 字段
        for item in script_list:
            if 'episode' not in item:
                item['episode'] = 0

        logger.info(f"[多集] 解说脚本生成完成，共 {len(script_list)} 个高光片段")
        return script_list

    except Exception as e:
        logger.error(f"[多集] 解说脚本生成失败: {e}")
        raise


def _split_script_by_episode(
    script_list: List[Dict],
    episode_paths: List[str]
) -> Dict[int, List[Dict]]:
    """按 episode 分组脚本片段，返回 {episode_idx: [script_items]}"""
    grouped = {i: [] for i in range(len(episode_paths))}
    for item in script_list:
        ep_idx = item.get('episode', 0)
        if ep_idx not in grouped:
            grouped[ep_idx] = []
        grouped[ep_idx].append(item)
    return grouped


# -------------------------------------------------------------------
#  主入口：start_multi_episode
# -------------------------------------------------------------------

def start_multi_episode(
    task_id: str,
    params: VideoClipParams,
    episode_paths: List[str],
    progress_callback: Optional[Callable[[float, str], None]] = None,
) -> Dict[str, Any]:
    """
    多集短剧高光剪辑主流程

    完整流程：
      1. 逐集提取关键帧
      2. 全局 LLM 分析 → 生成含 episode 标记的统一脚本
      3. 逐集 TTS 合成
      4. 逐集裁剪视频（感知 episode 来源）
      5. 合并全剧音频字幕
      6. 拼接高光视频片段
      7. 最终合成（字幕+BGM+配音）

    Args:
        task_id: 任务 ID
        params:  VideoClipParams（含 TTS 参数等）
        episode_paths: 视频路径列表（按剧集顺序）
        progress_callback: 进度回调 (progress: float 0-100, message: str)

    Returns:
        {"videos": [final_video_path], "combined_videos": [...], "script": [...]}
    """
    if progress_callback is None:
        progress_callback = lambda p, m: logger.info(f"[进度] {m} ({p:.0f}%)")

    logger.info(f"\n\n## 开始多集处理任务: {task_id}")
    logger.info(f"[多集] 共 {len(episode_paths)} 集")
    for i, p in enumerate(episode_paths):
        logger.info(f"  E{i+1}: {os.path.basename(p)}")

    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=0)

    try:
        # ── 1. 逐集提取关键帧 ──────────────────────────
        progress_callback(5, "提取多集关键帧...")
        episode_keyframes = asyncio.run(_extract_keyframes_multi(
            episode_paths=episode_paths,
            skip_seconds=0,
            threshold=30,
        ))

        # ── 2. 全局 LLM 分析 ──────────────────────────
        progress_callback(20, "分析全剧画面内容...")
        frame_analysis = asyncio.run(_analyze_all_frames_multi(
            episode_keyframes=episode_keyframes,
            video_theme=params.video_plot or "",
            custom_prompt="",
            vision_llm_provider=params.vision_llm_provider or "gemini",
        ))

        # ── 3. 生成高光解说脚本 ───────────────────────
        target_duration = getattr(params, 'target_duration', 30)
        script_list = asyncio.run(_generate_narration_script_multi(
            frame_analysis=frame_analysis,
            episode_paths=episode_paths,
            video_theme=params.video_plot or "",
            custom_prompt="",
            target_duration=target_duration,
        ))

        # 保存脚本
        script_dir = utils.task_dir(task_id)
        os.makedirs(script_dir, exist_ok=True)
        script_path = os.path.join(script_dir, "video_clip.json")
        with open(script_path, 'w', encoding='utf-8') as f:
            json.dump(script_list, f, ensure_ascii=False, indent=2)
        logger.info(f"[多集] 脚本已保存: {script_path}")

        progress_callback(40, "生成 TTS 音频...")
        sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=40)

        # ── 4. TTS 合成 ──────────────────────────────
        tts_segments = [s for s in script_list if s.get('OST', 0) in [0, 2]]
        tts_results = voice.tts_multiple(
            task_id=task_id,
            list_script=tts_segments,
            tts_engine=params.tts_engine,
            voice_name=params.voice_name,
            voice_rate=params.voice_rate,
            voice_pitch=params.voice_pitch,
        )

        progress_callback(55, "逐集裁剪高光视频...")
        sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=55)

        # ── 5. 逐集裁剪视频 ──────────────────────────
        # clip_video_unified_multi 根据 script_item['episode'] 路由到对应视频
        video_clip_result = clip_video_unified_multi(
            episode_paths=episode_paths,
            script_list=script_list,
            tts_results=tts_results,
            task_id=task_id,
        )

        # 更新 script_list 中的路径和时间戳
        tts_map = {r['_id']: r['audio_file'] for r in tts_results}
        subclip_map = {r['_id']: r['subtitle_file'] for r in tts_results}
        new_script_list = update_script.update_script_timestamps(
            script_list, video_clip_result, tts_map, subclip_map
        )

        progress_callback(65, "合并音频字幕...")
        sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=65)

        # ── 6. 合并音频和字幕 ─────────────────────────
        total_duration = sum(s.get("duration", 0) for s in new_script_list)
        merged_audio_path = ""
        merged_subtitle_path = ""

        if tts_segments:
            try:
                merged_audio_path = audio_merger.merge_audio_files(
                    task_id=task_id,
                    total_duration=total_duration,
                    list_script=new_script_list
                )
                merged_subtitle_path = subtitle_merger.merge_subtitle_files(new_script_list) or ""
                logger.info(f"[多集] 音频: {merged_audio_path}, 字幕: {merged_subtitle_path}")
            except Exception as e:
                logger.warning(f"[多集] 音频/字幕合并失败: {e}")

        progress_callback(75, "拼接高光视频片段...")
        sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=75)

        # ── 7. 拼接高光视频 ───────────────────────────
        combined_video_path = os.path.join(script_dir, "merger.mp4")

        video_clips = []
        video_ost_list = []
        for s in new_script_list:
            vpath = s.get('video')
            if vpath and os.path.exists(vpath):
                video_clips.append(vpath)
                video_ost_list.append(s.get('OST', 2))
            else:
                logger.warning(f"[多集] 片段 {s.get('_id')} 视频文件缺失，跳过")

        logger.info(f"[多集] 拼接 {len(video_clips)} 个高光片段")

        merger_video.combine_clip_videos(
            output_video_path=combined_video_path,
            video_paths=video_clips,
            video_ost_list=video_ost_list,
            video_aspect=params.video_aspect,
            threads=params.n_threads,
        )

        progress_callback(88, "最终合成...")
        sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=88)

        # ── 8. 最终合成（字幕+BGM+配音）───────────────
        output_video_path = os.path.join(script_dir, "combined.mp4")
        bgm_path = utils.get_bgm_file()

        optimized_volumes = get_recommended_volumes_for_content('mixed')
        has_original = any(s.get('OST') == 1 for s in script_list)
        final_tts_vol = (
            params.tts_volume if hasattr(params, 'tts_volume') and params.tts_volume != 1.0
            else optimized_volumes['tts_volume']
        )
        final_orig_vol = 1.0 if has_original else (
            params.original_volume if hasattr(params, 'original_volume') and params.original_volume != 0.7
            else optimized_volumes['original_volume']
        )
        final_bgm_vol = (
            params.bgm_volume if hasattr(params, 'bgm_volume') and params.bgm_volume != 0.3
            else optimized_volumes['bgm_volume']
        )

        options = {
            'voice_volume': final_tts_vol,
            'bgm_volume': final_bgm_vol,
            'original_audio_volume': final_orig_vol,
            'keep_original_audio': True,
            'subtitle_enabled': params.subtitle_enabled,
            'subtitle_font': params.font_name,
            'subtitle_font_size': params.font_size,
            'subtitle_color': params.text_fore_color,
            'subtitle_bg_color': None,
            'subtitle_position': params.subtitle_position,
            'custom_position': params.custom_position,
            'threads': params.n_threads
        }

        generate_video.merge_materials(
            video_path=combined_video_path,
            audio_path=merged_audio_path,
            subtitle_path=merged_subtitle_path,
            bgm_path=bgm_path,
            output_path=output_video_path,
            options=options
        )

        progress_callback(100, "处理完成！")
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_COMPLETE,
            progress=100,
            videos=[output_video_path],
            combined_videos=[combined_video_path]
        )

        logger.success(f"[多集] 任务 {task_id} 完成！成片: {output_video_path}")

        return {
            "videos": [output_video_path],
            "combined_videos": [combined_video_path],
            "script": new_script_list,
            "episode_count": len(episode_paths),
        }

    except Exception as e:
        logger.exception(f"[多集] 任务 {task_id} 失败")
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_FAILED,
            message=str(e)
        )
        raise


# -------------------------------------------------------------------
#  便捷入口：start_multi_episode_async（供 webui 后台调用）
# -------------------------------------------------------------------

def start_multi_episode_async(
    task_id: str,
    params: VideoClipParams,
    episode_paths: List[str],
):
    """异步入口，包装为线程运行（Streamlit 后台任务用）"""
    import threading

    def _run():
        try:
            start_multi_episode(task_id, params, episode_paths)
        except Exception as e:
            logger.exception(f"[多集-线程] {task_id} 执行异常: {e}")

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return task_id
