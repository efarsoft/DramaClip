"""
小工具 Handler
处理台词提取、文案AI改写等快捷功能
"""

import os
import uuid
import asyncio
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger
from app.ipc.protocol import RPCError

# 全局任务状态库
_tools_tasks: Dict[str, Dict[str, Any]] = {}


def _do_transcribe(task_id: str, video_path: str, mode: str):
    """后台执行转写"""
    _tools_tasks[task_id] = {
        "task_id": task_id,
        "status": "running",
        "progress": 5,
        "message": "正在提取音频...",
        "results": None,
        "error": None
    }

    temp_dir = Path.home() / ".dramaclip" / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    audio_path = str(temp_dir / f"{task_id}.wav")

    # 1. 提取音频
    from app.utils.ffmpeg_utils import extract_audio
    logger.info(f"[Tools] Extracting audio for task {task_id}: {video_path} -> {audio_path}")
    
    success = extract_audio(video_path, audio_path)
    if not success:
        logger.error(f"[Tools] Audio extraction failed for task {task_id}")
        _tools_tasks[task_id].update({
            "status": "failed",
            "progress": -1,
            "error": "音频提取失败，请检查 FFmpeg 安装或视频文件格式",
            "message": "音频提取失败"
        })
        return

    _tools_tasks[task_id].update({
        "progress": 20,
        "message": "音频提取成功，正在加载语音识别模型..."
    })

    # 进度回调
    def make_progress(pct, msg):
        # 将内部 ASR 进度 0-100% 映射到 25% - 95%
        scaled_pct = int(25 + (pct / 100) * 70)
        _tools_tasks[task_id].update({
            "progress": scaled_pct,
            "message": f"识别中: {msg} ({pct}%)"
        })

    # 2. 运行语音识别
    try:
        if mode == "precise":
            # Whisper 精准引擎
            from app.services.analyze.asr_service import ASRService
            from app.config.unified_config import config as unified_config
            
            whisper_model = unified_config.get("asr.model", "large-v3")
            logger.info(f"[Tools] Starting Whisper ASR on task {task_id} using model: {whisper_model}")
            
            service = ASRService()
            result = service.recognize(
                audio_path=audio_path,
                language="zh",
                model=whisper_model,
                progress_callback=make_progress
            )
            segments_list = [s.to_dict() for s in result.segments]
        else:
            # SenseVoice 极速引擎
            from app.services.analyze.sensevoice_asr import SenseVoiceService
            logger.info(f"[Tools] Starting SenseVoice ASR on task {task_id}")
            
            service = SenseVoiceService(model="SenseVoice-large")
            result = service.recognize(
                audio_path=audio_path,
                language="zh",
                progress_callback=make_progress
            )
            segments_list = [s.to_dict() for s in result.segments]

        # 3. 聚合为高可读性的纯净段落
        prose_parts = []
        last_end = 0.0
        for seg in segments_list:
            # 停顿超过 2 秒，自动划分段落
            if seg["start"] - last_end > 2.0:
                prose_parts.append("\n\n")
            elif prose_parts and prose_parts[-1] != "\n\n":
                prose_parts.append(" ")
            prose_parts.append(seg["text"])
            last_end = seg["end"]
            
        prose = "".join(prose_parts).strip()

        _tools_tasks[task_id].update({
            "status": "completed",
            "progress": 100,
            "message": "台词提取成功！",
            "results": {
                "segments": segments_list,
                "prose": prose
            }
        })
        logger.info(f"[Tools] Task {task_id} completed successfully")

    except Exception as e:
        logger.exception(f"[Tools] ASR failed for task {task_id}: {e}")
        _tools_tasks[task_id].update({
            "status": "failed",
            "progress": -1,
            "error": f"语音识别失败: {str(e)}",
            "message": "识别错误"
        })

    finally:
        # 清理临时 wav 文件
        if os.path.exists(audio_path):
            try:
                os.remove(audio_path)
                logger.debug(f"[Tools] Temp file cleaned up: {audio_path}")
            except Exception as clean_err:
                logger.warning(f"[Tools] Failed to clean temp file {audio_path}: {clean_err}")


def tools_transcribe(video_path: str, mode: str = "fast") -> Dict[str, Any]:
    """开始台词/文案提取任务

    Args:
        video_path: 本地视频绝对路径
        mode: 引擎类型，'fast' (SenseVoice极速) | 'precise' (Whisper精准)

    Returns:
        任务ID和初始状态
    """
    logger.info(f"[Tools] Starting transcription: path={video_path}, mode={mode}")
    if not video_path or not os.path.exists(video_path):
        raise RPCError(-32602, f"视频文件不存在: {video_path}")

    task_id = str(uuid.uuid4())
    
    # 启动后台工作线程
    thread = threading.Thread(
        target=_do_transcribe,
        args=(task_id, video_path, mode),
        name=f"ToolsTranscribe-{task_id[:8]}",
        daemon=True
    )
    thread.start()

    return {
        "task_id": task_id,
        "status": "running"
    }


def tools_get_progress(task_id: str) -> Dict[str, Any]:
    """查询台词提取任务进度

    Args:
        task_id: 任务ID

    Returns:
        包含进度和结果的状态字典
    """
    task = _tools_tasks.get(task_id)
    if not task:
        raise RPCError(-32002, f"任务不存在: {task_id}")
    return task


def tools_rewrite(script: str, prompt_style: str = "rewriter") -> Dict[str, Any]:
    """使用AI改写提取出的文案

    Args:
        script: 原剧台词或文案内容
        prompt_style: 改写风格选项 ('shocking' | 'suspense' | 'emotional' | 'rewriter')

    Returns:
        改写后的文案内容
    """
    logger.info(f"[Tools] Request AI rewrite style: {prompt_style}")
    if not script or not script.strip():
        raise RPCError(-32602, "文案内容不能为空")

    style_prompts = {
        "shocking": (
            "请将以下原剧台词或视频文案，二次改写成富有极强剧烈冲突感、极度抓人眼球的短剧解说词。\n"
            "特别加强‘黄金前3秒’的文案悬念，突出主要矛盾和痛点，以吸引观众持续观看，用词要凌厉直接：\n\n"
        ),
        "suspense": (
            "请将以下原剧台词或视频文案，二次改写成充满悬念、层层铺垫、吊足胃口并在结尾具有神级戏剧化反转的解说词。\n"
            "极力挑逗观众的猎奇心，在结尾给出一记出人意料的终极解答：\n\n"
        ),
        "emotional": (
            "请将以下原剧台词或视频文案，二次改写成富有深厚情感张力、文艺共鸣和高级情绪感染力的经典解说词。\n"
            "词藻优美真挚，触动观众内心深处的同理心与代入感：\n\n"
        ),
        "rewriter": (
            "请将以下原剧台词或视频文案进行高水平的二次创作和洗稿。\n"
            "保持核心故事情节与主题不变，但使用全新的现代流行网络解说风格进行重写和修饰，确保能轻松通过各大视频平台的原创版权检测：\n\n"
        )
    }

    prefix = style_prompts.get(prompt_style, style_prompts["rewriter"])
    prompt = f"{prefix}{script}"

    try:
        from app.services.llm.manager import LLMServiceManager
        provider = LLMServiceManager.get_text_provider()
        system_prompt = "你是一位全网累计百万播放量的资深短剧解说词与二创爆款文案改写大师。极其擅长用最精准、震撼、带感的话术重塑文案。"

        # 异步调用同步化包装
        async def run_llm():
            return await provider.generate_text(
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=0.8
            )

        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(lambda: asyncio.run(run_llm()))
                rewritten = future.result()
        else:
            rewritten = loop.run_until_complete(run_llm())

        return {"rewritten": rewritten}

    except Exception as e:
        logger.exception(f"[Tools] AI rewrite failed: {e}")
        raise RPCError(-32005, f"AI 改写服务异常: {str(e)}")
