"""
DramaClip - 台词情绪分析器

基于NLP关键词匹配分析台词文本的情绪强度：
- 感叹句/反问句（强烈情绪表达）
- 短剧高频抓马关键词
- 情绪词汇密度
"""

import re
from typing import Tuple, List, Dict
from loguru import logger

# 延迟导入 jieba（避免未安装时整个模块无法加载）
try:
    import jieba
except ImportError:
    jieba = None
    logger.warning("jieba 未安装，情绪分析将降级为关键词匹配模式。建议: pip install jieba")


class EmotionScorer:
    """
    台词情绪评分器
    
    对镜头片段的台词文本进行情绪分析，给出 0~1 的情绪强度得分。
    
    分析维度：
    1. 关键词命中 (40%) — 抓马/冲突/反转关键词
    2. 句式特征 (25%) — 感叹句、反问句、短促句
    3. 情绪词密度 (20%) — 正负向情绪词占比
    4. 对话强度 (15%) — 对话密集程度、角色切换频率
    """
    
    # ===== 短剧高频抓马关键词库 =====#
    
    # 冲突对抗类
    CONFLICT_KEYWORDS = [
        "住手", "不可能", "原来是你", "你竟然", "我怎么没想到",
        "背叛", "欺骗", "谎言", "真相", "复仇", "报仇",
        "杀", "死", "血", "恨", "疯子", "混蛋", "畜生",
        "滚", "闭嘴", "放肆", "大胆", "竟敢",
        "离婚", "分手", "取消婚约", "退婚",
        "打", "推倒", "抓住", "放开我", "救命",
        "报警", "坐牢", "判刑",
        # 常见短剧情节点
        "反转", "没想到", "居然", "竟然",
        "终于", "这一刻", "不可能的事",
        "全部", "一切", "从来", "一直",
    ]
    
    # 强烈情绪类
    INTENSE_EMOTION_KEYWORDS = [
        "爱", "恨", "愤怒", "崩溃", "绝望", "心碎", "痛哭",
        "狂笑", "尖叫", "颤抖", "震惊", "难以置信",
        "天哪", "上帝", "老天", "苍天", "不", "为什么",
        "怎么可能", "怎么会", "别", "不要", "不行",
        "太好了", "太棒了", "终于等到",
        "对不起", "原谅我", "我错了", "后悔",
        "我爱你", "我恨你", "再见了",
        "骗子", "虚伪", "恶心", "可怕", "恐怖",
    ]
    
    # 高潮信号词
    CLIMAX_KEYWORDS = [
        "最后的机会", "唯一的选择", "没有退路",
        "生死攸关", "千钧一发", "命悬一线",
        "真相大白", "水落石出", "尘埃落定",
        "从此以后", "永远", "发誓", "承诺",
        "开始", "结束", "终结",
        "赢了", "输了", "胜利", "失败",
    ]
    
    # 感叹/反问模式（正则）
    EXCLAMATION_PATTERNS = [
        r'！{2,}',           # 多重感叹号
        r'？{2,}',           # 多重问号  
        r'[！？]{2,}',       # 混合感叹问号
        r'^[！？\s]+',       # 开头就是感叹/问号
        r'难道.*[？！]$',     # 反问句式"难道...?"
        r'怎么.*[？！]$',     # "怎么...?" 
        r'难道.*[！]$',       # "难道...!"
        r'居然.*[！？]',      # "居然...!"
        r'竟然.*[！？]',      # "竟然...!"
        r'简直.*[！？]',      # "简直...!"
        r'到底.*[？]',        # "到底...?"
        r'究竟.*[？]',        # "究竟...?"
        r'莫非.*[？]',        # "莫非...?"
        r'该不会.*[？]',      # "该不会...?"
        r'不会吧.*[？！]',    # "不会吧...?"
        r'天哪',              # 天哪
        r'我的天',            # 我的天
        r'我的 god',          # my god
        r'no+',               # no/nooo
    ]
    
    def __init__(self):
        """初始化分词器"""
        # 预加载 jieba 词性标注（可选加速）
        if jieba:
            try:
                jieba.initialize()
            except Exception:
                logger.debug("jieba 初始化失败，使用默认分词器")
    
    def score(self, text: str) -> Tuple[float, dict]:
        """
        对台词文本进行情绪评分
        
        Args:
            text: 台词文本内容
            
        Returns:
            tuple: (得分0~1, 详细分析结果dict)
        """
        if not text or not text.strip():
            return 0.0, {"error": "empty_text"}
        
        text = text.strip()
        
        # 各维度评分
        keyword_score = self._score_keywords(text)
        pattern_score = self._score_patterns(text)
        emotion_density_score = self._score_emotion_density(text)
        intensity_score = self._score_intensity(text)
        
        # 综合加权
        total_score = (
            0.40 * keyword_score +
            0.25 * pattern_score +
            0.20 * emotion_density_score +
            0.15 * intensity_score
        )
        
        total_score = max(0.0, min(1.0, total_score))
        
        details = {
            "keyword_score": round(keyword_score, 4),
            "pattern_score": round(pattern_score, 4),
            "emotion_density_score": round(emotion_density_score, 4),
            "intensity_score": round(intensity_score, 4),
            "total_score": round(total_score, 4),
            "text_length": len(text),
            "matched_keywords": self._get_matched_keywords(text),
        }
        
        return total_score, details
    
    def _score_keywords(self, text: str) -> float:
        """
        关键词命中评分
        
        三级关键词权重不同：
        - 冲突对抗类：权重最高（1.0）
        - 高潮信号词：权重高（0.8）
        - 强烈情绪词：权重中等（0.6）
        
        匹配策略：
        - 多字关键词(>=2字)：直接子串匹配
        - 单字关键词：用jieba分词后匹配词粒度，避免误匹配
        """
        text_lower = text.lower()
        
        conflict_hits = self._count_keyword_hits(text, text_lower, self.CONFLICT_KEYWORDS)
        climax_hits = self._count_keyword_hits(text, text_lower, self.CLIMAX_KEYWORDS)
        emotion_hits = self._count_keyword_hits(text, text_lower, self.INTENSE_EMOTION_KEYWORDS)
        
        # 加权计算
        weighted_hits = (
            1.0 * conflict_hits +
            0.8 * climax_hits +
            0.6 * emotion_hits
        )
        
        # 归一化（假设命中3个以上高权关键词即为高情绪片段）
        score = min(1.0, weighted_hits / 3.0)
        return score
    
    def _count_keyword_hits(self, text: str, text_lower: str, keywords: list) -> int:
        """统计关键词命中数，对单字关键词用分词匹配避免误匹配"""
        hits = 0
        single_char_kws = []
        multi_char_kws = []
        
        for kw in keywords:
            if len(kw) == 1:
                single_char_kws.append(kw)
            else:
                multi_char_kws.append(kw)
        
        # 多字关键词：子串匹配
        for kw in multi_char_kws:
            if kw in text:
                hits += 1
        
        # 单字关键词：用jieba分词后匹配词粒度
        if single_char_kws:
            if jieba:
                try:
                    words = set(jieba.cut(text))
                    hits += sum(1 for kw in single_char_kws if kw in words)
                except Exception:
                    # jieba 失败时，跳过单字关键词（比误匹配好）
                    pass
            # jieba 不可用时，跳过单字关键词避免大量误匹配
        
        return hits
    
    def _score_patterns(self, text: str) -> float:
        """句式特征评分（感叹句、反问句等）"""
        hit_count = 0
        matched_patterns = []
        
        for pattern in self.EXCLAMATION_PATTERNS:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                hit_count += len(matches)
                matched_patterns.append(pattern)
        
        # 标准化（文本越长，允许的模式数越多）
        normalized_hits = hit_count / max(1, len(text) / 10)
        score = min(1.0, normalized_hits * 2)  # 调整敏感度
        
        return score
    
    def _score_emotion_density(self, text: str) -> float:
        """情绪词密度评分"""
        if not jieba:
            # jieba 不可用时降级为关键词匹配
            return self._score_keywords(text)
        
        try:
            words = list(jieba.cut(text))
            
            if not words:
                return 0.0
            
            # 合并所有情绪相关关键词
            all_emotion_words = set(
                self.CONFLICT_KEYWORDS + 
                self.CLIMAX_KEYWORDS + 
                self.INTENSE_EMOTION_KEYWORDS
            )
            
            emotion_count = sum(1 for w in words if w in all_emotion_words)
            density = emotion_count / len(words)
            
            # 短剧场景中，5%以上的情绪词密度就算很高了
            score = min(1.0, density * 15.0)
            return score
            
        except Exception:
            logger.debug("jieba 分词降级为关键词匹配", exc_info=True)
            return self._score_keywords(text)
    
    def _score_intensity(self, text: str) -> float:
        """对话强度评分（短促句+重复+省略）
        
        分析对话的激烈程度：
        - 短促句（1~4字）比例高 → 激烈对话
        - 字符重复（啊啊啊、不不不）→ 强烈情绪
        - 省略号多 → 欲言又止/紧张
        """
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        
        if not lines:
            return 0.0
        
        # 短促句比例
        short_lines = [l for l in lines if 1 <= len(l) <= 4]
        short_ratio = len(short_lines) / len(lines)
        
        # 重复字符检测
        repeat_pattern = re.compile(r'(.)\1{2,}')  # 连续3个相同字符
        repeats = len(repeat_pattern.findall(text))
        
        # 省略号/破折号
        ellipsis_count = text.count('...') + text.count('……') + text.count('——')
        
        # 综合强度
        intensity = (
            0.5 * short_ratio +
            0.3 * min(1.0, repeats / 3) +
            0.2 * min(1.0, ellipsis_count / 2)
        )
        
        return intensity
    
    def _get_matched_keywords(self, text: str) -> List[str]:
        """获取命中的关键词列表（用于调试和展示）"""
        matched = []
        text_lower = text.lower()
        
        all_keywords = (
            [(kw, "conflict") for kw in self.CONFLICT_KEYWORDS] +
            [(kw, "climax") for kw in self.CLIMAX_KEYWORDS] +
            [(kw, "emotion") for kw in self.INTENSE_EMOTION_KEYWORDS]
        )
        
        # 对单字关键词，用jieba分词后匹配
        single_chars = [(kw, cat) for kw, cat in all_keywords if len(kw) == 1]
        multi_chars = [(kw, cat) for kw, cat in all_keywords if len(kw) > 1]
        single_char_words = set()
        
        if single_chars and jieba:
            try:
                single_char_words = set(jieba.cut(text))
            except Exception:
                single_char_words = set()  # jieba 失败时不匹配单字
        
        for kw, category in multi_chars:
            if (category == "emotion" and kw in text_lower) or \
               (category != "emotion" and kw in text):
                matched.append(f"{kw}({category})")
        
        for kw, category in single_chars:
            if single_char_words and kw in single_char_words:
                matched.append(f"{kw}({category})")
        
        return matched[:10]  # 最多返回10个
