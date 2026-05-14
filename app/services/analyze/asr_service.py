"""
ASR 语音识别服务 - 基于 faster-whisper 本地离线识别
"""

import os
import threading
from typing import List, Dict, Optional, Callable
from dataclasses import dataclass, field
from pathlib import Path
from loguru import logger


@dataclass
class ASRSegment:
    """ASR 识别片段"""
    id: str
    text: str
    start: float
    end: float
    speaker: str = ""

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "text": self.text,
            "start": self.start,
            "end": self.end,
            "speaker": self.speaker,
        }


@dataclass
class ASRResult:
    """ASR 识别结果"""
    segments: List[ASRSegment] = field(default_factory=list)
    language: str = "zh"
    duration: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "segments": [s.to_dict() for s in self.segments],
            "language": self.language,
            "duration": self.duration,
        }


# ---------------------------------------------------------------------------
# Model manager – singleton, lazy-loaded
# ---------------------------------------------------------------------------

_model_instance = None
_model_lock = threading.Lock()
_model_device = "cpu"
_model_compute = "int8"


def _get_model(model_size: str = "large-v3", device: str = None,
               compute_type: str = None):
    """获取或创建 WhisperModel 单例"""
    global _model_instance, _model_device, _model_compute

    if _model_instance is not None:
        return _model_instance

    with _model_lock:
        if _model_instance is not None:
            return _model_instance

        from faster_whisper import WhisperModel

        # ---------- 设备探测 ----------
        use_cuda = False
        if device is None or device == "auto":
            try:
                import torch
                use_cuda = torch.cuda.is_available()
            except Exception:
                use_cuda = False
        else:
            use_cuda = device == "cuda"

        if use_cuda:
            _model_device = "cuda"
            _model_compute = compute_type or "float16"
            try:
                _model_instance = WhisperModel(
                    model_size_or_path=model_size,
                    device="cuda",
                    compute_type=_model_compute,
                    local_files_only=False,  # 允许自动下载
                )
                logger.info(f"ASR model loaded on CUDA: {model_size}")
            except Exception as e:
                logger.warning(f"CUDA load failed, fallback to CPU: {e}")
                use_cuda = False

        if not use_cuda:
            _model_device = "cpu"
            _model_compute = compute_type or "int8"
            _model_instance = WhisperModel(
                model_size_or_path=model_size,
                device="cpu",
                compute_type=_model_compute,
                local_files_only=False,
            )
            logger.info(f"ASR model loaded on CPU: {model_size}")

        return _model_instance


# ---------------------------------------------------------------------------
# ASR Service
# ---------------------------------------------------------------------------

class ASRService:
    """ASR 语音识别服务（本地 faster-whisper）"""

    def __init__(self):
        self._cancelled = False

    def cancel(self):
        """取消正在进行的识别"""
        self._cancelled = True

    def recognize(
        self,
        audio_path: str,
        language: str = "zh",
        model: str = "large-v3",
        video_id: Optional[str] = None,
        progress_callback: Optional[Callable] = None,
    ) -> ASRResult:
        """
        执行本地语音识别

        Args:
            audio_path: 音频文件路径 (16kHz mono WAV 推荐)
            language: 语言代码 ('zh', 'en', 'ja', 'auto')
            model: 模型大小 ('tiny', 'base', 'small', 'medium', 'large-v3')
            video_id: 视频标识（仅用于日志）
            progress_callback: 进度回调 fn(progress: int, message: str)

        Returns:
            ASRResult 包含识别片段列表
        """
        self._cancelled = False

        if not os.path.isfile(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        tag = video_id or Path(audio_path).stem
        logger.info(f"ASR start: {tag} (model={model}, lang={language})")

        if progress_callback:
            progress_callback(0, "加载语音识别模型...")

        whisper = _get_model(model_size=model)

        if self._cancelled:
            logger.warning(f"ASR cancelled before transcription: {tag}")
            return ASRResult(segments=[], language=language, duration=0.0)

        if progress_callback:
            progress_callback(10, "开始语音识别...")

        # ---------- 转写 ----------
        lang_param = None if language == "auto" else language
        seg_iter, info = whisper.transcribe(
            audio_path,
            language=lang_param,
            beam_size=5,
            word_timestamps=True,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
            initial_prompt="以下是普通话的句子",
        )

        detected_lang = info.language or language
        logger.info(f"ASR detected language: {detected_lang} "
                     f"(prob={info.language_probability:.2f})")

        if progress_callback:
            progress_callback(30, f"识别语言: {detected_lang}")

        # ---------- 遍历 segments ----------
        segments: List[ASRSegment] = []
        total_segments_approx = 50  # 用于进度估算
        seg_count = 0
        seg_start = 0.0
        seg_end = 0.0
        seg_text = ""

        for segment in seg_iter:
            if self._cancelled:
                logger.warning(f"ASR cancelled mid-transcription: {tag}")
                break

            # 按标点断句
            if segment.words:
                for word in segment.words:
                    if not seg_text:
                        seg_start = word.start
                    seg_text += word.word
                    seg_end = word.end

                    # 如果包含标点则输出一个片段
                    if _has_punctuation(word.word):
                        text = seg_text.rstrip(".,!?;:，。！？；：、")
                        if text:
                            segments.append(ASRSegment(
                                id=str(len(segments) + 1),
                                text=text,
                                start=seg_start,
                                end=seg_end,
                            ))
                        seg_text = ""
            else:
                # 没有词级时间戳时按 segment 级别输出
                text = segment.text.strip()
                if text:
                    segments.append(ASRSegment(
                        id=str(len(segments) + 1),
                        text=text,
                        start=segment.start,
                        end=segment.end,
                    ))

            seg_count += 1
            if progress_callback and seg_count % 5 == 0:
                pct = min(85, 30 + int(seg_count / total_segments_approx * 55))
                progress_callback(pct, f"识别中… 已处理 {seg_count} 段")

        # 处理最后一段无标点的文本
        if seg_text.strip():
            segments.append(ASRSegment(
                id=str(len(segments) + 1),
                text=seg_text.strip(),
                start=seg_start,
                end=seg_end,
            ))

        duration = max((s.end for s in segments), default=0.0)
        result = ASRResult(segments=segments, language=detected_lang, duration=duration)

        logger.info(f"ASR done: {tag} → {len(segments)} segments, {duration:.1f}s")

        if progress_callback:
            progress_callback(100, f"识别完成: {len(segments)} 段")

        return result

    def save_result(self, result: ASRResult, output_path: str):
        """将识别结果保存为 JSON 文件"""
        import json
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)
        logger.info(f"ASR result saved: {output_path}")


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _has_punctuation(word: str) -> bool:
    """判断单词/字是否包含标点符号"""
    punct = set(".,!?;:，。！？；：、")
    return any(c in punct for c in word)


# ---------------------------------------------------------------------------
# 独立入口 – 直接对音频文件执行 ASR
# ---------------------------------------------------------------------------

def whisper_asr(
    audio_path: str,
    model: str = "base",
    language: str = "zh",
    progress_callback=None,
) -> List[Dict]:
    """
    快捷函数：对单个音频文件执行语音识别

    Returns:
        [{"text": ..., "start": ..., "end": ..., "speaker": ...}]
    """
    service = ASRService()
    result = service.recognize(
        audio_path=audio_path,
        language=language,
        model=model,
        progress_callback=progress_callback,
    )
    return [s.to_dict() for s in result.segments]
