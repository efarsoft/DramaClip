"""
ASR 语音识别服务 - 基于 SenseVoice (阿里达摩院)
针对中文优化，支持方言识别、情感检测、音频事件检测

安装依赖:
    pip install funasr modelscope torch torchaudio
"""

import os
import re
import json
import threading
from typing import Any, List, Dict, Optional, Callable
from dataclasses import dataclass, field
from pathlib import Path
from loguru import logger


@dataclass
class SenseVoiceSegment:
    """SenseVoice 识别片段"""
    id: str
    text: str
    start: float
    end: float
    speaker: str = ""
    emotion: str = ""
    audio_events: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "text": self.text,
            "start": self.start,
            "end": self.end,
            "speaker": self.speaker,
            "emotion": self.emotion,
            "audio_events": self.audio_events,
        }


@dataclass
class SenseVoiceResult:
    """SenseVoice 识别结果"""
    segments: List[SenseVoiceSegment] = field(default_factory=list)
    language: str = "zh"
    duration: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "segments": [s.to_dict() for s in self.segments],
            "language": self.language,
            "duration": self.duration,
        }


# 线程本地存储
_sv_thread_local = threading.local()
_sv_model_lock = threading.Lock()

# 情感标签映射 — 使用标准 English 键以与前端 EmotionCurve.tsx 完美契合
_SV_EMOTION_LABELS = {
    "<|happy|>": "joy",
    "<|sad|>": "sadness",
    "<|angry|>": "anger",
    "<|fear|>": "fear",
    "<|surprise|>": "surprise",
    "<|neutral|>": "neutral",
    "<|disgust|>": "disgust",
    "<|contempt|>": "contempt",
}

# 音频事件标签映射
_SV_AUDIO_EVENT_LABELS = {
    "<|BGM|>": "背景音乐",
    "<|Speech|>": "语音",
    "<|Applause|>": "掌声",
    "<|Laughter|>": "笑声",
    "<|Cry|>": "哭声",
    "<|Sneeze|>": "喷嚏",
    "<|Breath|>": "呼吸",
    "<|Cough|>": "咳嗽",
}


def _parse_sv_output(text: str) -> Dict:
    """解析 SenseVoice 输出"""
    emotion = "neutral"
    audio_events: List[str] = []
    clean_text = text
    
    for tag, label in _SV_EMOTION_LABELS.items():
        if tag in text:
            emotion = label
            break
    
    for tag, label in _SV_AUDIO_EVENT_LABELS.items():
        if tag in text:
            audio_events.append(label)
    
    # 用最精简且完全无损的正则剥离所有 <|...|> 标签，留下干净纯粹的对白文字
    clean_text = re.sub(r'<\|.*?>', '', clean_text)
    
    return {"text": clean_text.strip(), "emotion": emotion, "audio_events": audio_events}


def _load_sv_model(model_size: str = "SenseVoice-large", device: Optional[str] = None) -> Any:
    """加载 SenseVoice 模型"""
    if hasattr(_sv_thread_local, 'model') and _sv_thread_local.model is not None:
        return _sv_thread_local.model

    with _sv_model_lock:
        if hasattr(_sv_thread_local, 'model') and _sv_thread_local.model is not None:
            return _sv_thread_local.model

        try:
            import importlib
            mod = importlib.import_module("funasr")
            AutoModel = mod.AutoModel
        except ImportError as e:
            raise RuntimeError("请安装: pip install funasr modelscope torch torchaudio") from e
        
        if device is None:
            try:
                import torch
                device = "cuda:0" if torch.cuda.is_available() else "cpu"
            except Exception:
                device = "cpu"
        
        # 优先从中央 catalog 获取标准 model repo（required_model_repo 风格）
        from app.services.model_manager import get_model_by_repo_id, load_model_catalog
        catalog_entry = get_model_by_repo_id("iic/SenseVoiceSmall")
        model_name = "iic/SenseVoiceSmall"
        if catalog_entry:
            # catalog 优先使用 HF repo 如果有，但 SenseVoice 主要 ModelScope
            model_name = catalog_entry.get("repo_id", "iic/SenseVoiceSmall")

        # 优先使用规整的本地物理直读路径
        try:
            from app.services.model_manager import _get_sensevoice_dir
            local_sv_dir = _get_sensevoice_dir()
            local_sv_dir_str = str(local_sv_dir.resolve())
        except Exception:
            local_sv_dir_str = os.path.normpath("resources/models/asr/iic/SenseVoiceSmall")
        
        if os.path.isdir(local_sv_dir_str) and (
            os.path.exists(os.path.join(local_sv_dir_str, "model.pt")) or
            os.path.exists(os.path.join(local_sv_dir_str, "model.onnx"))
        ):
            logger.info(f"[ASR] 检测到规整的本地内置 SenseVoiceSmall 模型，执行 100% 本地物理绝对路径直读: {local_sv_dir_str}")
            model_path = local_sv_dir_str
        else:
            model_path = model_name
            logger.warning(f"[ASR] 未在规整物理路径检测到模型 ({local_sv_dir_str})，降级使用 ModelScope 缓存加载: {model_path}")

        # VAD 模型的本地物理路径直读支持
        try:
            local_vad_dir = Path(local_sv_dir_str).parent / "speech_fsmn_vad_zh-cn-16k-common-pytorch"
            local_vad_dir_str = str(local_vad_dir.resolve())
        except Exception:
            local_vad_dir_str = os.path.normpath("resources/models/asr/iic/speech_fsmn_vad_zh-cn-16k-common-pytorch")
            
        if os.path.isdir(local_vad_dir_str) and (
            os.path.exists(os.path.join(local_vad_dir_str, "model.pt")) or
            os.path.exists(os.path.join(local_vad_dir_str, "model.yaml")) or
            os.path.exists(os.path.join(local_vad_dir_str, "config.yaml"))
        ):
            logger.info(f"[ASR] 检测到规整的本地内置 VAD 模型，执行 100% 本地物理绝对路径直读: {local_vad_dir_str}")
            vad_model_path = local_vad_dir_str
        else:
            vad_model_path = "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch"

        logger.info(f"Loading SenseVoice: {model_path} with VAD: {vad_model_path} on {device}")
        _sv_thread_local.model = AutoModel(
            model=model_path,
            vad_model=vad_model_path,
            device=device,
            trust_remote_code=True
        )
        logger.info(f"SenseVoice loaded on {device}")

        return _sv_thread_local.model


class SenseVoiceService:
    """SenseVoice ASR 服务"""

    def __init__(self, model: str = "SenseVoice-large"):
        self._cancelled = False
        self._model_size = model

    def cancel(self):
        self._cancelled = True

    def recognize(
        self,
        audio_path: str,
        language: str = "zh",
        video_id: Optional[str] = None,
        progress_callback: Optional[Callable] = None,
        enable_emotion: bool = True,
        enable_audio_events: bool = True,
    ) -> SenseVoiceResult:
        """执行语音识别"""
        self._cancelled = False

        if not os.path.isfile(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        tag = video_id or Path(audio_path).stem
        logger.info(f"SenseVoice start: {tag}")

        if progress_callback:
            progress_callback(0, "加载 SenseVoice 模型...")

        model = _load_sv_model(model_size=self._model_size)

        if progress_callback:
            progress_callback(10, "开始识别...")

        if self._cancelled:
            return SenseVoiceResult(segments=[], language=language, duration=0.0)

        try:
            results = model.generate(
                input=audio_path,
                cache={},
                language=language if language != "auto" else "zh",
                use_itn=True,
                batch_size_s=60,
            )

            if self._cancelled:
                return SenseVoiceResult(segments=[], language=language, duration=0.0)

            if progress_callback:
                progress_callback(50, "解析识别结果...")

            segments: List[SenseVoiceSegment] = []
            
            if results and len(results) > 0:
                result_data = results[0] if isinstance(results, list) else results
                
                if isinstance(result_data, dict):
                    raw_text = result_data.get("text", "")
                    
                    if raw_text:
                        # 先按标点和换行分割，保留原本的标签以精确匹配每句的情绪/事件
                        sentences = re.split(r'[。！？；\n]+', raw_text)
                        current_time = 0.0
                        
                        for i, sent in enumerate(sentences):
                            sent = sent.strip()
                            if not sent:
                                continue
                            
                            # 针对每个句子进行标签解析和提取，使情绪曲线和事件流高度精确和动态变化
                            parsed = _parse_sv_output(sent)
                            clean_text = parsed["text"]
                            
                            if not clean_text:
                                continue
                            
                            duration = max(1.0, len(clean_text) / 4.5)  # 至少 1.0 秒，确保有一定长度
                            segment = SenseVoiceSegment(
                                id=str(len(segments) + 1),
                                text=clean_text,
                                start=round(current_time, 2),
                                end=round(current_time + duration, 2),
                                emotion=parsed["emotion"] if enable_emotion else "",
                                audio_events=parsed["audio_events"] if enable_audio_events else [],
                            )
                            segments.append(segment)
                            current_time += duration

            duration = max((s.end for s in segments), default=0.0)
            result = SenseVoiceResult(segments=segments, language=language, duration=duration)

            logger.info(f"SenseVoice done: {tag} → {len(segments)} segments")

            if progress_callback:
                progress_callback(100, f"识别完成: {len(segments)} 段")

            return result

        except Exception as e:
            logger.error(f"SenseVoice failed: {e}")
            raise

    def save_result(self, result: SenseVoiceResult, output_path: str):
        """保存结果到 JSON 文件"""
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)
        logger.info(f"Result saved: {output_path}")


def sensevoice_asr(audio_path: str, model: str = "SenseVoice-large", language: str = "zh", progress_callback=None) -> List[Dict]:
    """快捷函数：执行语音识别"""
    service = SenseVoiceService(model=model)
    result = service.recognize(audio_path=audio_path, language=language, progress_callback=progress_callback)
    return [s.to_dict() for s in result.segments]
