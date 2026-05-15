"""
AI解说管道 - 完整的AI解说模式流水线

流程：
1. 剧情解析（LLM）
2. 解说文案生成（LLM）
3. TTS语音合成
4. 音画合成输出
"""

import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

import openai

from app.services.direct_cut.pipeline import DirectCutPipeline
from app.utils.ffmpeg_utils import get_ffmpeg_path

logger = logging.getLogger(__name__)


class PlotParser:
    """剧情解析器 - 使用LLM理解剧情"""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str = "deepseek-ai/DeepSeek-V3",
        timeout: int = 180,
    ):
        """
        初始化剧情解析器

        Args:
            api_key: API密钥
            base_url: API基础URL
            model: 模型名称
            timeout: 超时时间（秒）
        """
        self.client = openai.OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
        )
        self.model = model
        logger.info(f"PlotParser initialized with model: {model}")

    def parse(
        self,
        video_paths: List[str],
        subtitle_texts: Optional[List[str]] = None,
    ) -> Dict:
        """
        解析剧情

        Args:
            video_paths: 视频路径列表
            subtitle_texts: 字幕文本列表（可选）

        Returns:
            剧情解析结果，包含：
            - plot_summary: 剧情摘要
            - key_points: 关键情节点
            - emotional_arc: 情绪曲线
            - characters: 角色列表
        """
        logger.info(f"Parsing plot from {len(video_paths)} videos")

        # 构建prompt
        prompt = self._build_prompt(video_paths, subtitle_texts)

        try:
            # 调用LLM
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "你是一个专业的短剧剧情分析师，擅长理解剧情、提取关键情节点、分析情绪曲线。",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.7,
            )

            # 解析结果
            result_text = response.choices[0].message.content
            result = self._parse_result(result_text)

            logger.info("Plot parsing completed")
            return result

        except Exception as e:
            logger.error(f"Error parsing plot: {e}")
            raise

    def _build_prompt(
        self,
        video_paths: List[str],
        subtitle_texts: Optional[List[str]],
    ) -> str:
        """构建LLM prompt"""
        prompt = """请分析以下短剧的剧情：

视频文件：
"""
        for i, path in enumerate(video_paths):
            prompt += f"{i+1}. {os.path.basename(path)}\n"

        if subtitle_texts:
            prompt += "\n字幕文本：\n"
            for i, text in enumerate(subtitle_texts):
                if text:
                    prompt += f"\n第{i+1}集：\n{text[:500]}...\n"  # 只取前500字符

        prompt += """

请输出以下JSON格式的结果：
{
  "plot_summary": "剧情摘要（100字以内）",
  "key_points": ["关键点1", "关键点2", ...],
  "emotional_arc": ["起始情绪", "发展情绪", "高潮情绪", "结尾情绪"],
  "characters": ["角色1", "角色2", ...]
}

注意：
1. 只输出JSON，不要有任何其他文字
2. key_points应该包含3-5个关键情节点
3. emotional_arc应该反映情绪的起伏
"""

        return prompt

    def _parse_result(self, result_text: str) -> Dict:
        """解析LLM返回的结果"""
        import json

        # 尝试提取JSON
        try:
            # 查找JSON字符串
            start = result_text.find("{")
            end = result_text.rfind("}") + 1
            if start != -1 and end != 0:
                json_str = result_text[start:end]
                return json.loads(json_str)
        except Exception as e:
            logger.error(f"Error parsing result: {e}")

        # 降级：返回默认值
        return {
            "plot_summary": "",
            "key_points": [],
            "emotional_arc": [],
            "characters": [],
        }


class NarrationGenerator:
    """解说文案生成器 - 使用LLM生成解说词"""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str = "deepseek-ai/DeepSeek-V3",
        timeout: int = 180,
    ):
        """
        初始化解说文案生成器

        Args:
            api_key: API密钥
            base_url: API基础URL
            model: 模型名称
            timeout: 超时时间（秒）
        """
        self.client = openai.OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
        )
        self.model = model
        logger.info(f"NarrationGenerator initialized with model: {model}")

    def generate(
        self,
        plot_info: Dict,
        target_duration: Optional[int] = None,
    ) -> List[Dict]:
        """
        生成解说文案

        Args:
            plot_info: 剧情解析结果（来自PlotParser）
            target_duration: 目标时长（秒），None 表示不限制时长

        Returns:
            解说文案列表，每个元素包含：
            - text: 解说文本
            - start_time: 开始时间（秒）
            - end_time: 结束时间（秒）
            - emotion: 情绪标签
        """
        logger.info("Generating narration")

        # 构建prompt
        prompt = self._build_prompt(plot_info, target_duration)

        try:
            # 调用LLM
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "你是一个专业的短剧解说文案创作者，擅长创作生动、有趣、引人入胜的解说词。",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.8,
            )

            # 解析结果
            result_text = response.choices[0].message.content
            narration = self._parse_result(result_text)

            logger.info(f"Generated {len(narration)} narration segments")
            return narration

        except Exception as e:
            logger.error(f"Error generating narration: {e}")
            raise

    def _build_prompt(self, plot_info: Dict, target_duration: Optional[int] = None) -> str:
        """构建LLM prompt"""
        duration_instruction = ""
        if target_duration is not None:
            duration_instruction = f"""目标时长：{target_duration}秒

注意：
3. 时间应该连续，总时长约为{target_duration}秒
"""

        prompt = f"""请为以下短剧生成解说文案：

剧情摘要：
{plot_info.get('plot_summary', '')}

关键情节点：
"""
        for i, kp in enumerate(plot_info.get("key_points", [])):
            prompt += f"{i+1}. {kp}\n"

        prompt += f"\n情绪曲线：{', '.join(plot_info.get('emotional_arc', []))}"

        prompt += f"""

{duration_instruction}请生成解说文案，输出以下JSON格式：
[
  {{
    "text": "解说文本1",
    "start_time": 0,
    "end_time": 5,
    "emotion": "兴奋"
  }},
  {{
    "text": "解说文本2",
    "start_time": 5,
    "end_time": 10,
    "emotion": "紧张"
  }},
  ...
]

注意：
1. 只输出JSON，不要有任何其他文字
2. 解说词应该生动、有趣、引人入胜
4. emotion可以是：兴奋、紧张、悲伤、愤怒、温馨、搞笑等
"""

        return prompt

    def generate_with_segments(
        self,
        plot_info: Dict,
        segments: List['HighlightSegment'],
        target_duration: Optional[int] = None,
    ) -> List[Dict]:
        """
        基于实际选中的高光片段生成解说文案

        Args:
            plot_info: 剧情解析结果
            segments: 排序后的高光片段列表（按时间顺序排列）
            target_duration: 目标时长（秒），None 表示不限制时长

        Returns:
            解说文案列表，每个元素包含：
            - text: 解说文本
            - start_time: 开始时间（秒）
            - end_time: 结束时间（秒）
            - emotion: 情绪标签
        """
        if not segments:
            logger.warning("No segments provided, falling back to regular generation")
            return self.generate(plot_info, target_duration)

        logger.info(f"Generating narration for {len(segments)} segments")

        # 构建基于片段的 prompt
        prompt = self._build_prompt_with_segments(plot_info, segments, target_duration)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "你是一个专业的短剧解说文案创作者，擅长根据实际视频片段创作生动、有趣、引人入胜的解说词。你能够根据每个片段的具体内容、情绪和剧情重要性，生成精准匹配的解说文本。",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.8,
            )

            result_text = response.choices[0].message.content
            narration = self._parse_result(result_text)

            # 校验并修正时间戳：确保连续性
            narration = self._fix_timestamps(narration)

            logger.info(f"Generated {len(narration)} narration segments for {len(segments)} video segments")
            return narration

        except Exception as e:
            logger.error(f"Error generating narration for segments: {e}")
            # 降级：使用常规方法
            return self.generate(plot_info, target_duration)

    def _fix_timestamps(self, narration: List[Dict]) -> List[Dict]:
        """
        修复时间戳：确保连续、递增、无重叠
        """
        if not narration:
            return narration

        cumulative = 0.0
        for item in narration:
            item["start_time"] = round(cumulative, 2)
            # 如果 end_time 缺失或错误，估算时长
            if item.get("end_time", 0) <= item.get("start_time", 0):
                # 根据文本长度估算：中文平均每秒 4-5 字
                text_len = len(item.get("text", ""))
                estimated_dur = max(1.5, text_len / 4.5)
                item["end_time"] = round(item["start_time"] + estimated_dur, 2)
            cumulative = item["end_time"]

        return narration

    def _build_prompt_with_segments(
        self,
        plot_info: Dict,
        segments: List['HighlightSegment'],
        target_duration: Optional[int] = None,
    ) -> str:
        """构建基于实际片段的 prompt"""
        total_dur = sum(s.duration for s in segments)
        duration_note = f"\n实际总时长：{total_dur:.1f}秒\n" if target_duration is None else f"\n目标时长：{target_duration}秒，实际片段总时长：{total_dur:.1f}秒\n"

        # 构建每个片段的描述
        segment_descriptions = []
        for i, seg in enumerate(segments):
            desc = f"\n  [{i + 1}] 片段时间: [{seg.start_time:.1f}s - {seg.end_time:.1f}s] 时长: {seg.duration:.1f}s | 情绪: {seg.emotion_score:.1f} | 音频: {seg.audio_score:.1f} | 画面: {seg.visual_score:.1f} | 节奏: {seg.rhythm_score:.1f} | 总分: {seg.score:.1f}"
            if seg.subtitle_text:
                desc += f"\n     字幕内容: {seg.subtitle_text[:100]}"
            if seg.reason:
                desc += f"\n     入选理由: {seg.reason}"
            segment_descriptions.append(desc)

        prompt = f"""请为以下短剧的高光片段生成解说文案：

剧情摘要：
{plot_info.get('plot_summary', '')}

关键情节点：
"""
        for i, kp in enumerate(plot_info.get("key_points", [])):
            prompt += f"{i + 1}. {kp}\n"

        prompt += f"\n情绪曲线：{', '.join(plot_info.get('emotional_arc', []))}\n"

        prompt += f"\n选中的高光片段：{duration_note}{''.join(segment_descriptions)}\n"

        prompt += f"""请为上述每个片段生成对应的解说文本。

输出 JSON 格式：
[
  {{
    "text": "解说文本1",
    "start_time": 0,
    "end_time": 5,
    "emotion": "紧张"
  }},
  ...
]

要求：
1. 只输出 JSON，不要有任何其他文字
2. 解说词必须与对应片段内容紧密关联，生动、有趣、引人入胜
3. start_time/end_time 必须连续递增，从 0 开始，总时长等于各片段实际时长之和
4. 每个片段对应一段解说，解说词长度应与片段时长匹配（中文每秒约 4-5 字）
5. emotion 可以是：兴奋、紧张、悲伤、愤怒、温馨、搞笑、悬疑等
6. 解说要制造悬念、推动剧情、解释人物动机，让观众欲罢不能
"""

        return prompt

    def _parse_result(self, result_text: str) -> List[Dict]:
        """解析LLM返回的结果"""
        import json

        # 尝试提取JSON
        try:
            # 查找JSON字符串
            start = result_text.find("[")
            end = result_text.rfind("]") + 1
            if start != -1 and end != 0:
                json_str = result_text[start:end]
                return json.loads(json_str)
        except Exception as e:
            logger.error(f"Error parsing result: {e}")

        # 降级：返回默认值
        return []


class TTSComposer:
    """TTS语音合成器"""

    def __init__(
        self,
        engine: str = "styletts2",
        voice: Optional[str] = None,
        rate: float = 1.0,
        volume: int = 80,
    ):
        """
        初始化TTS合成器

        Args:
            engine: TTS引擎（edge_tts, azure_speech, tencent_tts, cosyvoice）
            voice: 音色名称
            rate: 语速（1.0 = 正常）
            volume: 音量（0-100）
        """
        self.engine = engine
        self.voice = voice
        self.rate = rate
        self.volume = volume

        logger.info(f"TTSComposer initialized with engine: {engine}")

    def synthesize(
        self,
        narration: List[Dict],
        output_dir: Optional[str] = None,
    ) -> List[str]:
        """
        语音合成

        Args:
            narration: 解说文案列表
            output_dir: 输出目录（可选）

        Returns:
            音频文件路径列表
        """
        if output_dir is None:
            output_dir = os.path.join(tempfile.gettempdir(), "narration_audio")
        os.makedirs(output_dir, exist_ok=True)

        audio_paths = []

        for i, seg in enumerate(narration):
            text = seg.get("text", "")
            if not text:
                continue

            output_path = os.path.join(output_dir, f"narration_{i:03d}.mp3")

            try:
                if self.engine == "edge_tts":
                    self._synthesize_edge_tts(text, output_path)
                elif self.engine == "azure_speech":
                    self._synthesize_azure(text, output_path)
                elif self.engine == "tencent_tts":
                    self._synthesize_tencent(text, output_path)
                elif self.engine == "cosyvoice":
                    self._synthesize_cosyvoice(text, output_path)
                elif self.engine == "styletts2":
                    self._synthesize_styletts2(text, output_path)
                else:
                    logger.warning(f"Unknown TTS engine: {self.engine}")
                    continue

                audio_paths.append(output_path)
                logger.info(f"Synthesized: {output_path}")

            except Exception as e:
                logger.error(f"Error synthesizing audio: {e}")
                continue

        logger.info(f"Total synthesized: {len(audio_paths)} audio files")
        return audio_paths

    def _synthesize_edge_tts(self, text: str, output_path: str):
        """使用edge-tts合成语音"""
        import asyncio
        import edge_tts

        async def _synthesize():
            communicate = edge_tts.Communicate(
                text, self.voice or "zh-CN-XiaoyiNeural"
            )
            await communicate.save(output_path)

        asyncio.run(_synthesize())

    def _synthesize_azure(self, text: str, output_path: str):
        """使用Azure Speech合成语音"""
        import azure.cognitiveservices.speech as speechsdk

        speech_config = speechsdk.SpeechConfig(
            subscription=os.getenv("AZURE_SPEECH_KEY"),
            region=os.getenv("AZURE_SPEECH_REGION"),
        )
        speech_config.speech_synthesis_voice_name = (
            self.voice or "zh-CN-XiaoyiNeural"
        )

        audio_config = speechsdk.audio.AudioOutputConfig(filename=output_path)
        synthesizer = speechsdk.SpeechSynthesizer(
            speech_config=speech_config, audio_config=audio_config
        )

        result = synthesizer.speak_text_async(text).get()
        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            logger.info(f"Azure TTS synthesis completed: {output_path}")
        else:
            raise Exception(f"Azure TTS synthesis failed: {result.reason}")

    def _synthesize_tencent(self, text: str, output_path: str):
        """使用腾讯云TTS合成语音"""
        from tencentcloud.common import credential
        from tencentcloud.tts.v20190823 import tts_client, models

        cred = credential.Credential(
            os.getenv("TENCENT_SECRET_ID"),
            os.getenv("TENCENT_SECRET_KEY"),
        )
        client = tts_client.TtsClient(cred, os.getenv("TENCENT_REGION", "ap-beijing"))

        req = models.TextToSpeechRequest()
        req.Text = text
        req.VoiceType = 1001  # 默认音色

        resp = client.TextToSpeech(req)
        with open(output_path, "wb") as f:
            f.write(resp.Audio)

        logger.info(f"Tencent TTS synthesis completed: {output_path}")

    def _synthesize_cosyvoice(self, text: str, output_path: str):
        """使用CosyVoice合成语音（DashScope API）"""
        import dashscope
        from dashscope.audio.tts_v2 import SpeechSynthesizer

        dashscope.api_key = os.getenv("COSYVOICE_API_KEY")

        synthesizer = SpeechSynthesizer(
            model="cosyvoice-v3-flash",
            voice="longanyang",
            text=text,
        )

        audio = synthesizer.call()
        with open(output_path, "wb") as f:
            f.write(audio)

        logger.info(f"CosyVoice TTS synthesis completed: {output_path}")

    def _synthesize_styletts2(self, text: str, output_path: str):
        """使用StyleTTS 2自动情感匹配合成语音（纯本地，无需API）"""
        try:
            from styletts2 import tts

            # Read config for model settings
            styletts2_cfg = {}
            try:
                from app.config import config as cfg
                styletts2_cfg = getattr(cfg, "styletts2", {}) or {}
            except ImportError:
                pass

            model_checkpoint = styletts2_cfg.get("model_checkpoint", "")
            config_path = styletts2_cfg.get("config_path", "")
            embedding_scale = styletts2_cfg.get("embedding_scale", 1.0)
            alpha = styletts2_cfg.get("alpha", 0.3)
            beta = styletts2_cfg.get("beta", 0.7)

            # Cache model as module-level singleton
            if not hasattr(self, "_styletts2_model"):
                kwargs = {}
                if model_checkpoint:
                    kwargs["model_checkpoint_path"] = model_checkpoint
                if config_path:
                    kwargs["config_path"] = config_path
                logger.info("Loading StyleTTS 2 model (first load downloads ~2GB)...")
                if kwargs:
                    self._styletts2_model = tts.StyleTTS2(**kwargs)
                else:
                    self._styletts2_model = tts.StyleTTS2()
                logger.info("StyleTTS 2 model loaded successfully")

            model = self._styletts2_model

            # Parse target voice if specified
            target_voice_path = None
            if self.voice and self.voice.startswith("styletts2:"):
                target_voice_path = self.voice[10:].strip()

            kwargs = {
                "text": text.strip(),
                "output_wav_file": output_path,
                "alpha": alpha,
                "beta": beta,
                "embedding_scale": embedding_scale,
            }
            if target_voice_path:
                kwargs["target_voice_path"] = target_voice_path
            if abs(self.rate - 1.0) > 0.05:
                kwargs["output_sample_rate"] = int(24000 * self.rate)

            model.inference(**kwargs)
            logger.info(f"StyleTTS 2 synthesis completed: {output_path}")

        except ImportError:
            logger.error("styletts2 not installed, run: pip install styletts2")
            raise
        except Exception as e:
            logger.error(f"StyleTTS 2 synthesis failed: {e}")
            raise


class NarrationPipeline:
    """AI解说管道 - 完整流水线"""

    def __init__(
        self,
        config: Optional[Dict] = None,
    ):
        """
        初始化管道

        Args:
            config: 配置字典（从config.toml加载）
        """
        self.config = config or {}

        # 初始化子模块
        llm_config = self.config.get("app", {})
        self.plot_parser = PlotParser(
            api_key=llm_config.get("text_openai_api_key", ""),
            base_url=llm_config.get("text_openai_base_url", ""),
            model=llm_config.get("text_openai_model_name", "deepseek-ai/DeepSeek-V3"),
        )

        self.narration_generator = NarrationGenerator(
            api_key=llm_config.get("text_openai_api_key", ""),
            base_url=llm_config.get("text_openai_base_url", ""),
            model=llm_config.get("text_openai_model_name", "deepseek-ai/DeepSeek-V3"),
        )

        ui_config = self.config.get("ui", {})
        self.tts_composer = TTSComposer(
            engine=ui_config.get("tts_engine", "styletts2"),
            voice=ui_config.get("styletts2_voice", ""),
            rate=ui_config.get("edge_rate", 1.0),
            volume=ui_config.get("edge_volume", 80),
        )

        # 复用DirectCutPipeline进行视频剪辑
        self.direct_cut_pipeline = DirectCutPipeline(config)

        logger.info("NarrationPipeline initialized")

    def run(
        self,
        video_paths: List[str],
        output_path: Optional[str] = None,
        target_duration: Optional[int] = None,
        mix_mode: str = "replace",
    ) -> str:
        """
        执行完整的AI解说流水线（已修复：先选片段 → 基于片段生成解说 → 精确对齐）

        Args:
            video_paths: 输入视频路径列表（多集）
            output_path: 输出文件路径（可选，默认自动生成）
            target_duration: 目标时长（秒，可选）。为 None 时不限制时长
            mix_mode: 音画合成模式
                - "replace": 替换原声为解说（full_narration）
                - "overlay": 保留原声 + 叠加解说（hybrid_narration）

        Returns:
            输出文件路径
        """
        if not video_paths:
            raise ValueError("No video paths provided")

        logger.info(f"Starting NarrationPipeline with {len(video_paths)} videos, mix_mode={mix_mode}")
        if target_duration:
            logger.info(f"Target duration: {target_duration}s")

        # 1. 剧情解析
        logger.info("Step 1: Plot parsing")
        plot_info = self.plot_parser.parse(video_paths)

        # 2. 先选取高光片段（复用 DirectCutPipeline，不输出视频）
        logger.info("Step 2: Selecting highlight segments")
        sorted_segments = self.direct_cut_pipeline.run_segments_only(
            video_paths, target_duration
        )
        if not sorted_segments:
            raise ValueError("No highlight segments selected")
        total_dur = sum(s.duration for s in sorted_segments)
        logger.info(f"Selected {len(sorted_segments)} segments, total {total_dur:.1f}s")

        # 3. 基于实际片段生成解说文案
        logger.info("Step 3: Generating narration based on selected segments")
        narration = self.narration_generator.generate_with_segments(
            plot_info, sorted_segments, target_duration
        )

        # 4. TTS语音合成
        logger.info("Step 4: TTS synthesis")
        audio_paths = self.tts_composer.synthesize(narration)

        # 5. 精确剪辑 + 转场 + 音画合成
        logger.info("Step 5: Video cutting, transitions, and audio mixing")
        if output_path is None:
            output_path = self._generate_output_path(video_paths[0])

        final_path = self._cut_and_mix(
            video_paths, sorted_segments, audio_paths,
            output_path, mix_mode=mix_mode
        )

        logger.info(f"Pipeline completed: {final_path}")
        return final_path

    def _cut_segment(self, seg: 'HighlightSegment', output_path: str):
        """切割视频片段"""
        cmd = [
            get_ffmpeg_path(),
            "-y",
            "-ss", str(seg.start_time),
            "-i", seg.video_path,
            "-t", str(seg.duration),
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            output_path,
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"Error cutting segment: {e}")
            raise

    def _to_portrait(self, input_path: str, output_path: str):
        """横屏转竖屏（9:16）"""
        import cv2
        cap = cv2.VideoCapture(input_path)
        if not cap.isOpened():
            logger.warning(f"Cannot open video for aspect check: {input_path}")
            import shutil
            shutil.copy2(input_path, output_path)
            return

        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()

        aspect = width / height if height > 0 else 1.0
        target_aspect = 9.0 / 16.0

        if abs(aspect - target_aspect) < 0.06:
            import shutil
            shutil.copy2(input_path, output_path)
            return

        cmd = [
            get_ffmpeg_path(),
            "-y",
            "-i", input_path,
            "-vf", "crop=in_h*9/16:in_h:(in_w-in_h*9/16)/2:0",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "copy",
            output_path,
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"Error converting to portrait: {e}")
            raise

    def _calculate_xfade_offset(self, portrait_paths: List[str], index: int, overlap: float) -> float:
        """计算第 index 个 xfade 的 offset（累积时长减去前面所有转场重叠）"""
        import cv2
        offset = 0.0
        for i in range(index + 1):
            cap = cv2.VideoCapture(portrait_paths[i])
            fps = cap.get(cv2.CAP_PROP_FPS)
            frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            dur = frames / fps if fps > 0 else 0
            cap.release()
            offset += dur
        # 减去前面已经用掉的转场重叠
        offset -= index * overlap
        return max(offset, 0.1)

    def _build_xfade_filter(self, portrait_paths: List[str], overlap: float) -> str:
        """构建 xfade 滤镜字符串（暂未使用，保留接口）"""
        return ""

    def _cut_and_mix(
        self,
        video_paths: List[str],
        segments: List['HighlightSegment'],
        audio_paths: List[str],
        output_path: str,
        mix_mode: str = "replace",
    ) -> str:
        """
        基于片段精确剪辑、添加转场、混合音频

        Args:
            video_paths: 原始视频路径列表
            segments: 排序后的高光片段列表
            audio_paths: TTS 音频文件路径列表
            output_path: 输出文件路径
            mix_mode: "replace" 或 "overlay"

        Returns:
            输出文件路径
        """
        logger.info(f"Cutting & mixing {len(segments)} segments (mode={mix_mode})")

        try:
            temp_dir = tempfile.gettempdir()

            # 1. 精确剪辑每个片段
            cut_paths = []
            for i, seg in enumerate(segments):
                cut_path = os.path.join(temp_dir, f"narr_cut_{i:03d}.mp4")
                self._cut_segment(seg, cut_path)
                cut_paths.append(cut_path)

            # 2. 转换为竖屏（9:16）
            portrait_paths = []
            for i, cut_path in enumerate(cut_paths):
                portrait_path = os.path.join(temp_dir, f"narr_portrait_{i:03d}.mp4")
                self._to_portrait(cut_path, portrait_path)
                portrait_paths.append(portrait_path)

            # 3. 拼接所有片段（带 crossfade 转场）
            if len(portrait_paths) > 1:
                overlap = 0.5  # 0.5 秒交叉淡入淡出
                trans_output = os.path.join(temp_dir, f"narr_transited.mp4")

                # 构建输入参数
                cmd = [get_ffmpeg_path(), "-y"]
                for p in portrait_paths:
                    cmd.extend(["-i", p])

                num_inputs = len(portrait_paths)

                # 构建 xfade 链
                filter_parts = []
                prev_tags = "[0:v][1:v]"
                for i in range(num_inputs - 1):
                    out_tag = f"[xfade_{i}]"
                    offset = self._calculate_xfade_offset(portrait_paths, i, overlap)
                    filter_parts.append(
                        f"{prev_tags}xfade=transition=fade:duration={overlap}:offset={offset}{out_tag}"
                    )
                    prev_tags = out_tag

                # 最后一个输出
                final_out = "[out]"
                filter_parts.append(f"{prev_tags}copy{final_out}")

                filter_complex = ";".join(filter_parts)

                cmd.extend([
                    "-filter_complex", filter_complex,
                    "-map", "[out]",
                    "-c:v", "libx264",
                    "-preset", "fast",
                    "-crf", "23",
                    "-movflags", "+faststart",
                    trans_output,
                ])

                subprocess.run(cmd, check=True, capture_output=True)
                concat_video = trans_output
            else:
                # 单片段，直接复制
                import shutil
                shutil.copy2(portrait_paths[0], os.path.join(temp_dir, "narr_single.mp4"))
                concat_video = os.path.join(temp_dir, "narr_single.mp4")

            # 4. 合并所有 TTS 音频
            merged_audio = os.path.join(temp_dir, "merged_narration.mp3")
            concat_list = os.path.join(temp_dir, "narr_audio_list.txt")

            with open(concat_list, "w") as f:
                for ap in audio_paths:
                    escaped = ap.replace("\\", "/").replace("'", "'\\''")
                    f.write(f"file '{escaped}'\n")

            cmd_merge = [
                get_ffmpeg_path(), "-y",
                "-f", "concat", "-safe", "0",
                "-i", concat_list,
                "-c:a", "libmp3lame",
                "-q:a", "4",
                merged_audio,
            ]
            subprocess.run(cmd_merge, check=True, capture_output=True)

            # 5. 混合视频和解说音频
            if mix_mode == "overlay":
                cmd_mix = [
                    get_ffmpeg_path(), "-y",
                    "-i", concat_video,
                    "-i", merged_audio,
                    "-filter_complex",
                    "[0:a][1:a]amix=inputs=2:duration=longest:dropout_transition=2[aout]",
                    "-map", "0:v",
                    "-map", "[aout]",
                    "-c:v", "libx264",
                    "-c:a", "aac",
                    "-b:a", "192k",
                    output_path,
                ]
            else:
                cmd_mix = [
                    get_ffmpeg_path(), "-y",
                    "-i", concat_video,
                    "-i", merged_audio,
                    "-map", "0:v",
                    "-map", "1:a",
                    "-c:v", "libx264",
                    "-c:a", "aac",
                    "-b:a", "192k",
                    "-shortest",
                    output_path,
                ]

            subprocess.run(cmd_mix, check=True, capture_output=True)

            # 6. 清理临时文件
            for path in cut_paths + portrait_paths + [concat_list, merged_audio, concat_video]:
                if os.path.exists(path):
                    os.remove(path)
            if len(portrait_paths) > 1 and os.path.exists(trans_output):
                os.remove(trans_output)

            logger.info(f"Audio-video mixing completed: {output_path}")
            return output_path

        except Exception as e:
            logger.error(f"Error cutting and mixing: {e}")
            raise

    def _generate_output_path(self, reference_path: str) -> str:
        """生成输出文件路径"""
        import os
        from datetime import datetime

        base_dir = os.path.dirname(reference_path)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return os.path.join(base_dir, f"dramaclip_narration_{timestamp}.mp4")
