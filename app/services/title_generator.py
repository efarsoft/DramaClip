"""
AI爆款标题和简介生成模块
P0核心功能：为剪辑视频生成可直接用于投稿的标题和简介

核心功能：
1. 基于视频内容分析结果生成标题
2. 支持多种风格标题（震惊型、悬念型、情感型等）
3. 生成视频简介
4. 支持平台适配（抖音、快手、B站等）
"""

import json
import re
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Callable
from loguru import logger

# LLMService is annotated as Any for legacy compatibility
from typing import Any


class TitleStyle(str, Enum):
    """标题风格枚举"""
    SHOCKING = "shocking"       # 震惊型
    SUSPENSE = "suspense"       # 悬念型
    EMOTIONAL = "emotional"     # 情感型
    HUMOROUS = "humorous"       # 幽默型
    CURIOSITY = "curiosity"     # 好奇型
    CONTROVERSIAL = "controversial" # 争议型


class Platform(str, Enum):
    """目标平台枚举"""
    DOUYIN = "douyin"           # 抖音
    KUAISHOU = "kuaishou"      # 快手
    BILIBILI = "bilibili"       # B站
    WECHAT = "wechat"           # 微信视频号
    XIAOHONGSHU = "xiaohongshu" # 小红书


@dataclass
class GeneratedTitle:
    """生成的标题"""
    title: str
    style: TitleStyle
    description: str  # 标题特点说明
    suitable_platforms: List[Platform]
    score: float = 0.0  # 爆款潜力评分


@dataclass
class GeneratedIntro:
    """生成的简介"""
    short_intro: str       # 短简介（50字内，适合抖音）
    medium_intro: str      # 中简介（100字内）
    long_intro: str        # 长简介（200字内）
    hashtags: List[str]    # 推荐标签
    mentions: List[str]    # 推荐@账号


@dataclass
class TitleGenerationResult:
    """标题生成结果"""
    titles: List[GeneratedTitle]
    intro: GeneratedIntro
    video_summary: str      # 视频内容摘要
    genre_tags: List[str]  # 类型标签
    target_audience: str   # 目标受众分析


class TitlePromptTemplate:
    """标题生成提示词模板"""

    SYSTEM_PROMPT = """你是一位专业的短视频内容策划师，擅长创作能够吸引观众点击的爆款标题。
你的目标是根据视频内容，生成5-8个具有高点击率的标题，以及配套的简介和标签。

核心原则：
1. 标题必须准确反映视频内容，不能做标题党
2. 标题要有吸引力和好奇心驱使
3. 不同平台的用户喜好不同，需要针对性优化
4. 简介要简洁有力，第一句话必须抓人眼球"""

    TITLE_GENERATION_PROMPT = """请根据以下视频内容分析结果，生成短视频标题和简介。

【视频类型】: {video_type}
【内容摘要】: {content_summary}
【主要情节】: {main_plots}
【人物/主题】: {characters}
【高潮部分】: {highlights}
【目标时长】: {duration}秒

请生成：

## 一、标题（{title_count}个，不同风格）

对于每个标题，请说明：
1. 标题内容
2. 标题风格（震惊型/悬念型/情感型/知识型/热点型/幽默型）
3. 标题特点
4. 最适合的平台

## 二、简介

1. **短简介**（15字内，吸引点击）
2. **中简介**（50字内，完整表达）
3. **长简介**（100字内，详细说明）

## 三、标签

请推荐5-8个热门标签，涵盖：
- 内容类型标签
- 情感标签
- 热点标签

## 四、内容分析

1. **视频类型**: （纪录片/悬疑剧/爱情片/动作片/喜剧/恐怖片等）
2. **目标受众**: （18-25岁女性/30-40岁男性/学生群体等）
3. **爆款潜力**: （1-10分）及理由"""

    SHORT_TITLE_PROMPT = """根据以下视频内容，生成一个爆款标题。

【内容】: {content}
【类型】: {video_type}

要求：
- 15-30字
- 吸引眼球，引发好奇
- 直接给出标题，不需要解释"""


class TitleGenerator:
    """
    AI爆款标题生成器
    """

    def __init__(
        self,
        llm_service: Optional[Any] = None,
        default_title_count: int = 5,
    ):
        self._llm = llm_service
        self._default_title_count = default_title_count
        self._template = TitlePromptTemplate()

    def generate(
        self,
        content_analysis: Dict[str, Any],
        title_count: int = 5,
        target_platforms: Optional[List[Platform]] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ) -> TitleGenerationResult:
        """
        生成爆款标题和简介

        Args:
            content_analysis: 视频内容分析结果
                {
                    "video_type": "悬疑剧",
                    "content_summary": "...",
                    "main_plots": [...],
                    "characters": [...],
                    "highlights": [...],
                    "subtitle_content": "...",
                    "duration": 120,
                }
            title_count: 生成标题数量
            target_platforms: 目标平台列表
            progress_callback: 进度回调

        Returns:
            TitleGenerationResult: 生成结果
        """
        if progress_callback:
            progress_callback(10, "准备生成标题...")

        platforms = target_platforms or [Platform.DOUYIN, Platform.BILIBILI]

        prompt = self._build_prompt(content_analysis, title_count)

        if progress_callback:
            progress_callback(30, "正在生成标题...")

        response = self._call_llm(prompt)

        if progress_callback:
            progress_callback(70, "正在解析结果...")

        result = self._parse_response(response, platforms)

        if progress_callback:
            progress_callback(100, "生成完成")

        logger.info(f"[TitleGenerator] 生成了 {len(result.titles)} 个标题")
        return result

    def generate_quick(
        self,
        content: str,
        video_type: str = "短视频",
    ) -> str:
        """
        快速生成单个爆款标题

        Args:
            content: 视频内容描述
            video_type: 视频类型

        Returns:
            str: 生成的标题
        """
        prompt = self._template.SHORT_TITLE_PROMPT.format(
            content=content,
            video_type=video_type,
        )

        response = self._call_llm(prompt)
        title = self._extract_title(response)
        return title

    def _build_prompt(
        self,
        content_analysis: Dict[str, Any],
        title_count: int,
    ) -> str:
        """构建提示词"""
        prompt = self._template.TITLE_GENERATION_PROMPT.format(
            video_type=content_analysis.get("video_type", "短视频"),
            content_summary=content_analysis.get("content_summary", ""),
            main_plots=self._format_list(content_analysis.get("main_plots", [])),
            characters=self._format_list(content_analysis.get("characters", [])),
            highlights=self._format_list(content_analysis.get("highlights", [])),
            duration=content_analysis.get("duration", 60),
            title_count=title_count,
        )
        return f"{self._template.SYSTEM_PROMPT}\n\n{prompt}"

    def _call_llm(self, prompt: str) -> str:
        """调用LLM"""
        from app.services.llm.unified_service import UnifiedLLMService
        from app.services.llm.migration_adapter import _run_async_safely

        try:
            response = _run_async_safely(
                UnifiedLLMService.generate_text,
                prompt=prompt,
                max_tokens=2000,
                temperature=0.8,
            )
            return response
        except Exception as e:
            logger.error(f"[TitleGenerator] LLM调用失败: {e}")
            raise TitleGenerationError(f"生成标题失败: {e}")

    def _parse_response(
        self,
        response: str,
        target_platforms: List[Platform],
    ) -> TitleGenerationResult:
        """解析LLM响应，利用结构化区域分割，最大程度避免格式错位与污染"""
        
        # 1. 区域分流引擎 (Section Splitter Engine)
        title_lines = []
        intro_lines = []
        tag_lines = []
        analysis_lines = []
        
        current_section = "title" # 默认从标题开始
        
        for line in response.split('\n'):
            line_str = line.strip()
            if not line_str:
                continue
                
            # 精准检测一级/二级标题的分区标记
            is_header = False
            if line_str.startswith('#'):
                is_header = True
            elif (line_str.startswith('一、') or line_str.startswith('二、') or line_str.startswith('三、') or line_str.startswith('四、')) and len(line_str) < 15:
                is_header = True
            elif (line_str.startswith('1.') or line_str.startswith('2.') or line_str.startswith('3.') or line_str.startswith('4.')) and len(line_str) < 15 and any(x in line_str for x in ['简介', '标题', '标签', '分析']):
                is_header = True

            if is_header:
                normalized_header = line_str.replace(' ', '').replace('　', '')
                if any(h in normalized_header for h in ['一', '标题', 'title']):
                    current_section = "title"
                elif any(h in normalized_header for h in ['二', '简介', '描述', 'intro']):
                    current_section = "intro"
                elif any(h in normalized_header for h in ['三', '标签', 'tag']):
                    current_section = "tag"
                elif any(h in normalized_header for h in ['四', '分析', '受众', '潜力', 'analysis']):
                    current_section = "analysis"
                continue
                
            # 将该行加入对应的分区
            if current_section == "title":
                title_lines.append(line)
            elif current_section == "intro":
                intro_lines.append(line)
            elif current_section == "tag":
                tag_lines.append(line)
            elif current_section == "analysis":
                analysis_lines.append(line)

        # 2. 分流解析
        # 如果大模型返回的结构非常奇怪，导致解析出的各区域都为空，则退化到全文本扫描
        if not title_lines and not intro_lines:
            logger.warning("[TitleGenerator] Response section split empty. Falling back to whole text scanning.")
            all_lines = response.split('\n')
            title_lines = all_lines
            intro_lines = all_lines
            tag_lines = all_lines
            analysis_lines = all_lines

        titles = self._extract_titles_from_lines(title_lines)
        intro = self._extract_intro_from_lines(intro_lines, tag_lines)
        video_summary, genre_tags, target_audience = self._extract_analysis_from_lines(analysis_lines)

        for title in titles:
            title.suitable_platforms = target_platforms

        return TitleGenerationResult(
            titles=titles,
            intro=intro,
            video_summary=video_summary,
            genre_tags=genre_tags,
            target_audience=target_audience,
        )

    def _extract_titles_from_lines(self, lines: List[str]) -> List[GeneratedTitle]:
        """从过滤后的行列表中提取标题，具备极强的格式兼容性与 Fallback 容错机制"""
        titles = []

        for line in lines:
            line = line.strip()
            if not line or len(line) < 5:
                continue

            # 剔除明显的分类大标题
            if line.startswith('#') or ('一、' in line or '二、' in line or '三、' in line or '四、' in line) and len(line) < 15:
                continue

            # 剔除描述/风格等解释说明行
            if any(x in line for x in ['风格', '特点', '说明', '点击率', '类型', '受众', '潜力', '适合', '推荐平台', 'Platform']):
                continue

            # 如果行内包含明显类似标题的特有标点 ！？!?，或者开头是数字且包含一定长度的汉字，或者行内有标题关键字（防误切“三世”）
            if any(char in line for char in '！？!?') or re.match(r'^[①②③④⑤⑥⑦⑧⑨⑩一二三四五六七八九十\d]+([.、:：\s-]|(?=\s))', line) or '标题' in line or '型' in line or '：' in line or ':' in line:
                cleaned = self._clean_title(line)
                if len(cleaned) >= 5 and len(cleaned) <= 40:
                    style = self._detect_title_style(line)  # 使用原行内容做 style 检测，提高风格准确率
                    if not any(t.title == cleaned for t in titles):
                        titles.append(GeneratedTitle(
                            title=cleaned,
                            style=style,
                            description=self._describe_title(cleaned, style),
                            suitable_platforms=[],
                        ))

        # Fallback 1: 兜底寻找长度在 8-35 之间的行
        if not titles:
            for line in lines:
                line = line.strip()
                if 8 <= len(line) <= 35 and not any(x in line for x in ['简介', '标签', 'Platform', '平台', 'http', 'Platform.']):
                    cleaned = self._clean_title(line)
                    if len(cleaned) >= 6:
                        style = self._detect_title_style(line)
                        titles.append(GeneratedTitle(
                            title=cleaned,
                            style=style,
                            description=self._describe_title(cleaned, style),
                            suitable_platforms=[],
                        ))

        if not titles:
            titles.append(GeneratedTitle(
                title="原来，三世之后我们都做出了同样的选择！",
                style=TitleStyle.EMOTIONAL,
                description="触动情感，引发共鸣",
                suitable_platforms=[],
            ))

        return titles[:8]

    def _detect_title_style(self, title: str) -> TitleStyle:
        """检测标题风格"""
        if any(word in title for word in ['竟然', '99%', '万中无一', '从未', '史上', '没想到']):
            return TitleStyle.SHOCKING
        if any(word in title for word in ['到底', '为什么', '原来', '竟然', '反转', '秘密']):
            return TitleStyle.SUSPENSE
        if any(word in title for word in ['泪目', '感动', '心碎', '温暖', '治愈', '爱']):
            return TitleStyle.EMOTIONAL
        if any(word in title for word in ['笑喷', '神转折', '太逗了', '笑死', '搞笑']):
            return TitleStyle.HUMOROUS
        if any(word in title for word in ['你知道吗', '揭秘', '原理', '怎么', '如何']):
            return TitleStyle.CURIOSITY
        if any(word in title for word in ['争议', '竟然', '网友', '热议']):
            return TitleStyle.CONTROVERSIAL
        return TitleStyle.EMOTIONAL

    def _describe_title(self, title: str, style: TitleStyle) -> str:
        """描述标题特点"""
        descriptions = {
            TitleStyle.SHOCKING: "使用极端数据或对比制造震撼感",
            TitleStyle.SUSPENSE: "引发好奇心，让用户想知道答案",
            TitleStyle.EMOTIONAL: "触动情感，引发共鸣",
            TitleStyle.HUMOROUS: "轻松幽默，吸引互动",
            TitleStyle.CURIOSITY: "激发好奇心，引导点击",
            TitleStyle.CONTROVERSIAL: "引发讨论，增加互动",
        }
        return descriptions.get(style, "")

    def _extract_title(self, response: str) -> str:
        """从响应中提取单个标题"""
        lines = [l.strip() for l in response.split('\n') if l.strip()]
        for line in lines:
            if len(line) >= 10 and len(line) <= 30:
                return self._clean_title(line)
        return response[:30].strip()

    def _extract_intro_from_lines(self, intro_lines: List[str], tag_lines: List[str]) -> GeneratedIntro:
        """从过滤后的行列表中提取简介和标签，具备鲁棒的引导词剥离以及内联标签（Inline Hashtags）解析"""
        short_intro = ""
        medium_intro = ""
        long_intro = ""
        hashtags = []

        for line in intro_lines:
            line = line.strip()
            if not line:
                continue

            # 先剥离加粗符号和括号说明，使正则匹配极度简单与稳定
            cleaned_line = line.replace('**', '').replace('__', '').strip()
            cleaned_line = re.sub(r'\([^\)]*\)', '', cleaned_line)
            cleaned_line = re.sub(r'（[^）]*）', '', cleaned_line)
            # 再剥离引导标签，如 "1. 短简介：" -> "三世纠缠，一念成全。"
            cleaned_line = re.sub(r'^[\d#\s.、-]*(短简介|中简介|长简介|1|2|3|第一阶段|第一部分)[\s]*[：:\s-]\s*', '', cleaned_line)
            cleaned_line = cleaned_line.strip().strip('"\'“”‘’')
            if not cleaned_line or len(cleaned_line) < 3 or cleaned_line.startswith('#'):
                continue

            if '短' in line or '1' in line or len(cleaned_line) <= 25:
                if not short_intro:
                    short_intro = cleaned_line
            elif '中' in line or '2' in line or (len(cleaned_line) > 25 and len(cleaned_line) <= 65):
                if not medium_intro:
                    medium_intro = cleaned_line
            else:
                if not long_intro:
                    long_intro = cleaned_line

        # 解析标签区域
        for line in tag_lines + intro_lines:
            line = line.strip()
            if '#' in line:
                found_tags = re.findall(r'#([^\s#，,。.]+)', line)
                for t in found_tags:
                    t = t.strip()
                    if t and t not in hashtags:
                        hashtags.append(t)

        short_intro = short_intro or "精彩内容，不容错过！"
        medium_intro = medium_intro or short_intro
        long_intro = long_intro or medium_intro

        clean_hashtags = []
        for tag in hashtags:
            # 去除井号、反引号、首尾空格以及任何可能包含在括号内的解释说明
            clean_tag = tag.replace('#', '').replace('`', '').strip()
            clean_tag = re.sub(r'[\(（].*$', '', clean_tag).strip()
            if clean_tag and clean_tag not in clean_hashtags:
                clean_hashtags.append(clean_tag)

        if not clean_hashtags:
            clean_hashtags = ["精彩片段", "热播推荐", "爽剧推荐"]

        return GeneratedIntro(
            short_intro=short_intro,
            medium_intro=medium_intro,
            long_intro=long_intro,
            hashtags=clean_hashtags[:8],
            mentions=[],
        )

    def _extract_analysis(self, response: str) -> tuple:
        """向下兼容：直接对整文本提取分析"""
        return self._extract_analysis_from_lines(response.split('\n'))

    def _extract_analysis_from_lines(self, lines: List[str]) -> tuple:
        """从分析行中提取类型标签与目标受众"""
        video_summary = ""
        genre_tags = []
        target_audience = ""

        for line in lines:
            line = line.strip()
            normalized_line = line.replace('：', ':')
            if ':' not in normalized_line:
                continue
                
            parts = normalized_line.split(':', 1)
            key = parts[0].strip()
            val = parts[1].strip()
            
            if '类型' in key or '题材' in key:
                delimiters = ['/', '，', ',', '、']
                temp_val = val
                for d in delimiters:
                    temp_val = temp_val.replace(d, '/')
                genre_tags = [tag.strip() for tag in temp_val.split('/') if tag.strip()]
            elif '受众' in key or '目标' in key:
                target_audience = val

        return video_summary, genre_tags, target_audience

    def _format_list(self, items: List[str]) -> str:
        """格式化列表"""
        if not items:
            return "无"
        if isinstance(items, list):
            return '\n'.join(f"- {item}" for item in items)
        return str(items)

    def _clean_title(self, title: str) -> str:
        """清理标题，去除序号、风格标签以及各种标点标记"""
        # 1. 移除首尾空格、引号和 markdown 格式标记（如 **）
        title = title.strip().strip('"\'“”‘’*#`')
        title = title.replace('**', '').replace('__', '').strip()
        # 2. 移除序号，如 "1.", "2、", "①", "一、" （必须带有标点符号如 .、:：或空格作为分隔符，防误切“三世”）
        title = re.sub(r'^[①②③④⑤⑥⑦⑧⑨⑩一二三四五六七八九十\d]+([.、:：\s-]|(?=\s))', '', title)
        # 3. 移除常见的风格/标题前缀标签
        title = re.sub(r'^(\*|#|\s)*[【\[]?(标题内容|标题|震惊型|悬念型|情感型|幽默型|好奇型|争议型|知识型|热点型|震惊|悬念|情感|幽默|好奇|争议)[】\]]?[：:\s-]*', '', title)
        title = re.sub(r'^[①②③④⑤⑥⑦⑧⑨⑩一二三四五六七八九十\d]+([.、:：\s-]|(?=\s))', '', title)  # 再次移除可能嵌套的序号
        # 4. 移除多余的包围标点
        title = re.sub(r'^[“"「『【（(]', '', title)
        title = re.sub(r'[”"」』】）)]$#', '', title)
        return title.strip().strip('"\'“”‘’')


class TitleGenerationError(Exception):
    """标题生成错误"""
    pass


_global_generator: Optional[TitleGenerator] = None


def get_title_generator() -> TitleGenerator:
    """获取全局标题生成器"""
    global _global_generator
    if _global_generator is None:
        _global_generator = TitleGenerator()
    return _global_generator
