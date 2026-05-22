"""
情绪分析服务
基于 LLM 的精准情绪识别，支持上下文理解和复杂情绪检测

支持两种模式：
1. LLM 模式：使用大模型进行精准分析（推荐）
2. 关键词模式：本地关键词匹配（降级方案）
"""

import json
import re
import asyncio
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass, field
from loguru import logger


@dataclass
class EmotionPoint:
    """情绪数据点"""
    timestamp: float
    emotion: str              # 主要情绪
    sub_emotion: str = ""     # 细分情绪（如：无奈、纠结、嫉妒等）
    intensity: float = 0.0    # 0.0 - 1.0
    confidence: float = 0.0   # 置信度
    context: str = ""         # 触发情绪的上下文文本


@dataclass
class EmotionAnalysis:
    """情绪分析结果"""
    video_id: str
    overall_emotion: str
    overall_intensity: float = 0.0
    emotion_curve: List[EmotionPoint] = field(default_factory=list)
    emotion_distribution: Dict[str, float] = field(default_factory=dict)
    peak_moments: List[Dict] = field(default_factory=list)
    sentiment_summary: str = ""  # 情绪总结

    def to_dict(self) -> Dict:
        return {
            "video_id": self.video_id,
            "overall_emotion": self.overall_emotion,
            "overall_intensity": self.overall_intensity,
            "emotion_curve": [
                {
                    "timestamp": p.timestamp,
                    "emotion": p.emotion,
                    "sub_emotion": p.sub_emotion,
                    "intensity": p.intensity,
                    "confidence": p.confidence,
                    "context": p.context,
                }
                for p in self.emotion_curve
            ],
            "emotion_distribution": self.emotion_distribution,
            "peak_moments": self.peak_moments,
            "sentiment_summary": self.sentiment_summary,
        }


class EmotionService:
    """
    基于 LLM 的情绪分析服务
    
    支持：
    - 上下文理解（"我不开心" → negative）
    - 复杂情绪识别（无奈、纠结、嫉妒、释然等）
    - 情绪强度量化
    - 讽刺/反话检测
    """

    # 情绪颜色映射（用于图表）
    EMOTION_COLORS: Dict[str, str] = {
        "joy": "#FFD700",
        "sadness": "#4169E1",
        "anger": "#FF4500",
        "fear": "#8B008B",
        "surprise": "#FF69B4",
        "disgust": "#9ACD32",
        "neutral": "#808080",
        # 细分情绪
        "helplessness": "#9370DB",   # 无奈
        "ambivalence": "#20B2AA",    # 纠结
        "jealousy": "#FF6347",       # 嫉妒
        "relief": "#98FB98",         # 释然
        "excitement": "#FF4500",     # 兴奋
        "tenderness": "#FFB6C1",     # 温柔
        "contempt": "#696969",       # 轻蔑
        "anticipation": "#FFA500",   # 期待
    }

    # 情绪中文标签
    EMOTION_LABELS: Dict[str, str] = {
        "joy": "喜悦",
        "sadness": "悲伤",
        "anger": "愤怒",
        "fear": "恐惧",
        "surprise": "惊讶",
        "disgust": "厌恶",
        "neutral": "平静",
        "helplessness": "无奈",
        "ambivalence": "纠结",
        "jealousy": "嫉妒",
        "relief": "释然",
        "excitement": "兴奋",
        "tenderness": "温柔",
        "contempt": "轻蔑",
        "anticipation": "期待",
    }

    # LLM 分析 prompt
    EMOTION_ANALYSIS_PROMPT = """你是一位专业的情绪分析师，擅长分析对话文本中的情绪。

请分析以下对话片段的情绪，返回 JSON 格式的结果。

## 分析要求

1. **主要情绪** (emotion)：选择最能代表整体情绪的类别
   - joy（喜悦）：开心、快乐、兴奋、满足
   - sadness（悲伤）：难过、失落、遗憾、心碎
   - anger（愤怒）：生气、愤怒、暴怒、恼火
   - fear（恐惧）：害怕、紧张、焦虑、担忧
   - surprise（惊讶）：震惊、意外、惊喜、惊吓
   - disgust（厌恶）：讨厌、嫌弃、恶心、反感
   - neutral（中性）：平静、客观、无明显情绪

2. **细分情绪** (sub_emotion)：更精准的情绪描述，如：
   - 无奈、纠结、嫉妒、释然、兴奋、温柔、轻蔑、期待、愧疚、傲娇、冷淡、敷衍

3. **情绪强度** (intensity)：0.0-1.0，表示情绪的强烈程度
   - 0.0-0.3：轻微
   - 0.3-0.6：中等
   - 0.6-0.8：强烈
   - 0.8-1.0：极端

4. **上下文触发** (context)：指出触发情绪的具体文本片段

## 返回格式

```json
{
  "emotion": "anger",
  "sub_emotion": "无奈",
  "intensity": 0.7,
  "context": "你为什么总是这样"
}
```

## 注意事项

- 注意反话和讽刺（如"真是太好了"可能是愤怒或失望）
- 结合上下文理解情绪（如"没关系"可能是真的没关系，也可能是生气）
- 如果情绪复杂混合，选择最主要的情绪

## 待分析文本

{text}"""

    def __init__(self, use_llm: bool = True, fallback_to_keyword: bool = True):
        """
        初始化情绪分析服务
        
        Args:
            use_llm: 是否使用 LLM 分析（默认 True）
            fallback_to_keyword: LLM 失败时是否降级到关键词匹配（默认 True）
        """
        self.use_llm = use_llm
        self.fallback_to_keyword = fallback_to_keyword
        self._cancel_flag = False
        self._llm_provider: Optional[Any] = None

    def cancel(self):
        """取消分析"""
        self._cancel_flag = True

    def _get_llm_provider(self) -> Optional[Any]:
        """获取 LLM 提供商实例"""
        if self._llm_provider is not None:
            return self._llm_provider

        try:
            from app.services.llm.manager import LLMServiceManager
            
            if not LLMServiceManager.is_registered():
                logger.warning("LLM 提供商未注册，将使用关键词匹配")
                return None
            
            # 获取文本模型提供商
            self._llm_provider = LLMServiceManager.get_text_provider()
            logger.info(f"情绪分析 LLM 提供商已就绪: {type(self._llm_provider).__name__}")
            return self._llm_provider
            
        except Exception as e:
            logger.warning(f"获取 LLM 提供商失败: {e}，将使用关键词匹配")
            return None

    def analyze(
        self,
        text_segments: List[Dict[str, Any]],
        video_id: str,
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ) -> EmotionAnalysis:
        """
        分析情绪（同步版本）

        Args:
            text_segments: 文本片段列表 [{start, end, text}]
            video_id: 视频 ID
            progress_callback: 进度回调

        Returns:
            EmotionAnalysis 情绪分析结果
        """
        # 在事件循环中运行异步分析
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 如果已有事件循环在运行，使用线程池
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(
                        asyncio.run,
                        self._analyze_async(text_segments, video_id, progress_callback)
                    )
                    return future.result()
            else:
                return loop.run_until_complete(
                    self._analyze_async(text_segments, video_id, progress_callback)
                )
        except RuntimeError:
            # 没有事件循环，直接创建
            return asyncio.run(
                self._analyze_async(text_segments, video_id, progress_callback)
            )

    async def _analyze_async(
        self,
        text_segments: List[Dict[str, Any]],
        video_id: str,
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ) -> EmotionAnalysis:
        """异步分析情绪"""
        self._cancel_flag = False
        emotion_curve: List[EmotionPoint] = []
        emotion_counts: Dict[str, int] = {}
        intensity_sum: float = 0.0

        # 尝试使用 LLM，失败则降级
        use_llm = self.use_llm and self._get_llm_provider() is not None
        
        total = len(text_segments)
        for i, seg in enumerate(text_segments):
            if self._cancel_flag:
                raise InterruptedError("Analysis cancelled")

            text = seg.get("text", "")
            timestamp = seg.get("start", 0)

            # 选择分析方法
            if use_llm:
                result = await self._analyze_with_llm_async(text)
            else:
                result = self._analyze_with_keyword(text)

            if result is None:
                # 分析失败，使用中性情绪
                result = {"emotion": "neutral", "sub_emotion": "", "intensity": 0.3, "context": ""}

            point = EmotionPoint(
                timestamp=timestamp,
                emotion=result.get("emotion", "neutral"),
                sub_emotion=result.get("sub_emotion", ""),
                intensity=result.get("intensity", 0.3),
                confidence=0.9 if use_llm else 0.6,
                context=result.get("context", text[:50]),
            )
            emotion_curve.append(point)
            emotion_counts[point.emotion] = emotion_counts.get(point.emotion, 0) + 1
            intensity_sum += point.intensity

            if progress_callback and i % 3 == 0:
                progress = int((i / total) * 100)
                method = "LLM" if use_llm else "关键词"
                progress_callback(progress, f"[{method}] 已分析 {i}/{total} 段...")

        # 计算整体情绪
        overall = "neutral"
        if emotion_counts:
            overall = max(emotion_counts.keys(), key=lambda k: emotion_counts[k])

        # 计算平均强度
        avg_intensity = intensity_sum / len(emotion_curve) if emotion_curve else 0.0

        # 计算情绪分布（百分比）
        total_count = sum(emotion_counts.values())
        emotion_distribution = {
            e: round((c / total_count * 100), 1) if total_count > 0 else 0
            for e, c in emotion_counts.items()
        }

        # 找出情绪高峰
        peak_moments = self._find_peak_moments(emotion_curve)

        # 生成情绪总结
        sentiment_summary = self._generate_summary(emotion_distribution, peak_moments)

        return EmotionAnalysis(
            video_id=video_id,
            overall_emotion=overall,
            overall_intensity=round(avg_intensity, 2),
            emotion_curve=emotion_curve,
            emotion_distribution=emotion_distribution,
            peak_moments=peak_moments,
            sentiment_summary=sentiment_summary,
        )

    async def _analyze_with_llm_async(self, text: str) -> Optional[Dict[str, Any]]:
        """
        使用 LLM 分析文本情绪（异步版本）
        
        Args:
            text: 待分析文本
            
        Returns:
            {"emotion": str, "sub_emotion": str, "intensity": float, "context": str}
        """
        if not text or not text.strip():
            return None

        try:
            provider = self._get_llm_provider()
            if provider is None:
                return None

            prompt = self.EMOTION_ANALYSIS_PROMPT.format(text=text)
            
            # 调用 LLM（异步）
            response = await provider.generate_text(
                prompt=prompt,
                max_tokens=200,
                temperature=0.3,  # 低温度，更确定性的输出
            )

            # 解析 JSON 响应
            result = self._parse_llm_response(response)
            return result

        except Exception as e:
            logger.debug(f"LLM 情绪分析失败: {e}，降级到关键词匹配")
            return self._analyze_with_keyword(text) if self.fallback_to_keyword else None

    def _parse_llm_response(self, response: str) -> Optional[Dict[str, Any]]:
        """解析 LLM 返回的 JSON"""
        try:
            # 尝试直接解析
            if response.strip().startswith("{"):
                return json.loads(response)
            
            # 提取 JSON 块
            json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', response)
            if json_match:
                return json.loads(json_match.group(1))
            
            # 提取 {...} 块
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                return json.loads(json_match.group(1))
            
            logger.warning(f"无法从 LLM 响应中提取 JSON: {response[:100]}")
            return None
            
        except json.JSONDecodeError as e:
            logger.warning(f"JSON 解析失败: {e}")
            return None

    def _analyze_with_keyword(self, text: str) -> Dict[str, Any]:
        """
        基于关键词的情绪分析（降级方案）
        
        Args:
            text: 待分析文本
            
        Returns:
            情绪分析结果
        """
        if not text:
            return {"emotion": "neutral", "sub_emotion": "", "intensity": 0.0, "context": ""}

        # 扩展的关键词库
        EMOTION_KEYWORDS: Dict[str, List[str]] = {
            "joy": ["开心", "高兴", "快乐", "笑", "哈哈", "欢呼", "太棒了", "完美", "好", "爱", "喜欢", "美", "幸福"],
            "sadness": ["难过", "伤心", "哭", "痛苦", "悲伤", "失落", "遗憾", "可惜", "孤独", "寂寞", "心碎"],
            "anger": ["生气", "愤怒", "可恶", "混蛋", "该死", "气死我了", "滚", "恨", "讨厌", "烦", "怒"],
            "fear": ["害怕", "恐惧", "担心", "紧张", "惊恐", "不安", "焦虑", "害怕"],
            "surprise": ["惊讶", "吃惊", "意外", "震惊", "想不到", "天哪", "居然", "竟然"],
            "disgust": ["恶心", "讨厌", "嫌弃", "厌恶", "反感", "脏", "呕"],
            # 细分情绪
            "helplessness": ["没办法", "无奈", "只能", "无能为力", "唉"],
            "ambivalence": ["纠结", "犹豫", "不知道", "怎么办", "左右为难"],
            "jealousy": ["嫉妒", "羡慕", "凭什么是他", "不公平"],
            "relief": ["终于", "还好", "松了口气", "放心了", "太好了"],
            "excitement": ["激动", "兴奋", "期待", "迫不及待", "太刺激了"],
            "tenderness": ["温柔", "心疼", "抱抱", "乖", "宝贝"],
        }

        text_lower = text.lower()
        scores: Dict[str, int] = {}

        for emotion, keywords in EMOTION_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in text_lower)
            if score > 0:
                scores[emotion] = score

        if not scores:
            return {"emotion": "neutral", "sub_emotion": "", "intensity": 0.3, "context": ""}

        # 获取主要情绪
        primary_emotions = ["joy", "sadness", "anger", "fear", "surprise", "disgust"]
        sub_emotions = ["helplessness", "ambivalence", "jealousy", "relief", "excitement", "tenderness"]
        
        # 从得分中找主要情绪和细分情绪
        top_emotion = max(scores.keys(), key=lambda k: scores[k])
        
        if top_emotion in primary_emotions:
            emotion = top_emotion
            # 查找是否有细分情绪
            sub_emotion = next((e for e in sub_emotions if e in scores), "")
        else:
            # 细分情绪作为主要情绪时，映射到基础情绪
            emotion = "neutral"
            sub_emotion = top_emotion

        intensity = min(1.0, scores[top_emotion] * 0.15 + 0.4)
        
        return {
            "emotion": emotion,
            "sub_emotion": sub_emotion,
            "intensity": round(intensity, 2),
            "context": text[:50],
        }

    def _find_peak_moments(self, curve: List[EmotionPoint]) -> List[Dict[str, Any]]:
        """找出情绪高峰时刻"""
        peaks: List[Dict[str, Any]] = []
        for point in curve:
            # 高强度情绪或强烈情绪类型
            if point.intensity > 0.6 and point.emotion in ["joy", "anger", "surprise", "sadness"]:
                peaks.append({
                    "timestamp": point.timestamp,
                    "emotion": point.emotion,
                    "sub_emotion": point.sub_emotion,
                    "intensity": point.intensity,
                    "context": point.context,
                })
        
        # 按强度排序，返回前 10 个
        peaks.sort(key=lambda x: x["intensity"], reverse=True)
        return peaks[:10]

    def _generate_summary(self, distribution: Dict[str, float], peaks: List[Dict[str, Any]]) -> str:
        """生成情绪总结文本"""
        if not distribution:
            return "视频情绪分析结果为空"

        # 找出主要情绪
        sorted_emotions = sorted(distribution.items(), key=lambda x: x[1], reverse=True)
        primary = sorted_emotions[0] if sorted_emotions else ("neutral", 0.0)
        
        primary_label = self.EMOTION_LABELS.get(primary[0], primary[0])
        primary_pct = primary[1]
        
        summary = f"整体情绪以{primary_label}为主（{primary_pct:.1f}%）"
        
        if len(sorted_emotions) > 1:
            second = sorted_emotions[1]
            if second[1] > 10:  # 第二情绪占比超过 10%
                second_label = self.EMOTION_LABELS.get(second[0], second[0])
                summary += f"，伴有{second_label}（{second[1]:.1f}%）"
        
        if peaks:
            peak_count = len(peaks)
            summary += f"。共检测到 {peak_count} 个情绪高峰时刻"
        
        return summary

    def get_emotion_color(self, emotion: str) -> str:
        """获取情绪对应的颜色"""
        return self.EMOTION_COLORS.get(emotion, "#808080")

    def get_emotion_label(self, emotion: str) -> str:
        """获取情绪中文标签"""
        return self.EMOTION_LABELS.get(emotion, emotion)

    def save_result(self, result: EmotionAnalysis, output_path: Path) -> None:
        """保存分析结果"""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        logger.info(f"情绪分析结果已保存: {output_path}")

    def load_result(self, result_path: Path) -> Optional[EmotionAnalysis]:
        """加载分析结果"""
        if not result_path.exists():
            return None
        
        try:
            data = json.loads(result_path.read_text(encoding="utf-8"))
            return EmotionAnalysis(
                video_id=data.get("video_id", ""),
                overall_emotion=data.get("overall_emotion", "neutral"),
                overall_intensity=data.get("overall_intensity", 0.0),
                emotion_curve=[
                    EmotionPoint(
                        timestamp=p["timestamp"],
                        emotion=p["emotion"],
                        sub_emotion=p.get("sub_emotion", ""),
                        intensity=p.get("intensity", 0.0),
                        confidence=p.get("confidence", 0.0),
                        context=p.get("context", ""),
                    )
                    for p in data.get("emotion_curve", [])
                ],
                emotion_distribution=data.get("emotion_distribution", {}),
                peak_moments=data.get("peak_moments", []),
                sentiment_summary=data.get("sentiment_summary", ""),
            )
        except Exception as e:
            logger.error(f"加载情绪分析结果失败: {e}")
            return None


# 全局单例
_emotion_service: Optional[EmotionService] = None


def get_emotion_service() -> EmotionService:
    """获取全局情绪分析服务实例"""
    global _emotion_service
    if _emotion_service is None:
        _emotion_service = EmotionService()
    return _emotion_service
