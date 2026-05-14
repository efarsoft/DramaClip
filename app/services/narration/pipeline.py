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
from moviepy import VideoFileClip, AudioFileClip

from app.services.direct_cut.pipeline import DirectCutPipeline

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
            output_dir = "/tmp/narration_audio"
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
    ) -> str:
        """
        执行完整的AI解说流水线

        Args:
            video_paths: 输入视频路径列表（多集）
            output_path: 输出文件路径（可选，默认自动生成）
            target_duration: 目标时长（秒，可选）。为 None 时不限制时长

        Returns:
            输出文件路径
        """
        if not video_paths:
            raise ValueError("No video paths provided")

        logger.info(f"Starting NarrationPipeline with {len(video_paths)} videos")
        if target_duration:
            logger.info(f"Target duration: {target_duration}s")
        else:
            logger.info("Target duration: unlimited")

        # 1. 剧情解析
        logger.info("Step 1: Plot parsing")
        plot_info = self.plot_parser.parse(video_paths)

        # 2. 解说文案生成
        logger.info("Step 2: Narration generation")
        narration = self.narration_generator.generate(plot_info, target_duration)

        # 3. TTS语音合成
        logger.info("Step 3: TTS synthesis")
        audio_paths = self.tts_composer.synthesize(narration)

        # 4. 使用DirectCutPipeline剪辑原片
        logger.info("Step 4: Direct cut for video segments")
        video_segments = self.direct_cut_pipeline.run(
            video_paths, target_duration=target_duration
        )

        # 5. 音画合成
        logger.info("Step 5: Audio-video mixing")
        if output_path is None:
            output_path = self._generate_output_path(video_paths[0])

        final_path = self._mix_audio_video(
            video_segments, audio_paths, narration, output_path
        )

        logger.info(f"Pipeline completed: {final_path}")
        return final_path

    def _mix_audio_video(
        self,
        video_path: str,
        audio_paths: List[str],
        narration: List[Dict],
        output_path: str,
    ) -> str:
        """
        音画合成

        Args:
            video_path: 视频文件路径（已剪辑好的）
            audio_paths: 解说音频文件路径列表
            narration: 解说文案（用于时间戳对齐）
            output_path: 输出文件路径

        Returns:
            输出文件路径
        """
        logger.info("Mixing audio and video")

        try:
            # 1. 加载视频
            video_clip = VideoFileClip(video_path)

            # 2. 合并所有解说音频
            if audio_paths:
                audio_clips = []
                for audio_path in audio_paths:
                    audio_clip = AudioFileClip(audio_path)
                    audio_clips.append(audio_clip)

                # 拼接音频
                from moviepy.editor import concatenate_audioclips

                narration_audio = concatenate_audioclips(audio_clips)

                # 设置音频到视频
                final_clip = video_clip.set_audio(narration_audio)
            else:
                final_clip = video_clip

            # 3. 输出
            final_clip.write_videofile(
                output_path,
                codec="libx264",
                audio_codec="aac",
                temp_audiofile=os.path.join(tempfile.gettempdir(), 'temp-audio.m4a'),
                remove_temp=True,
            )

            logger.info(f"Audio-video mixing completed: {output_path}")
            return output_path

        except Exception as e:
            logger.error(f"Error mixing audio and video: {e}")
            raise

    def _generate_output_path(self, reference_path: str) -> str:
        """生成输出文件路径"""
        import os
        from datetime import datetime

        base_dir = os.path.dirname(reference_path)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return os.path.join(base_dir, f"dramaclip_narration_{timestamp}.mp4")
