"""
自定义JSON编码器，用于序列化EmotionAnalysis、ASRResult等对象
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

# 导入需要序列化的类
from app.services.analyze.asr_service import ASRResult, ASRSegment
from app.services.analyze.emotion_service import EmotionAnalysis, EmotionPoint


class CustomJSONEncoder(json.JSONEncoder):
    """
    自定义JSON编码器，支持序列化EmotionAnalysis、ASRResult等对象
    """
    
    def default(self, o: Any) -> Any:
        # 处理EmotionAnalysis对象
        if isinstance(o, EmotionAnalysis):
            return o.to_dict()
        
        # 处理EmotionPoint对象
        if isinstance(o, EmotionPoint):
            return {
                "timestamp": o.timestamp,
                "emotion": o.emotion,
                "intensity": o.intensity,
                "confidence": o.confidence,
            }
        
        # 处理ASRResult对象
        if isinstance(o, ASRResult):
            return o.to_dict()
        
        # 处理ASRSegment对象
        if isinstance(o, ASRSegment):
            return o.to_dict()
        
        # 处理Path对象
        if isinstance(o, Path):
            return str(o)
        
        # 处理datetime对象
        if isinstance(o, datetime):
            return o.isoformat()
        
        # 处理其他无法序列化的对象
        try:
            # 尝试调用对象的to_dict方法
            if hasattr(o, 'to_dict'):
                return o.to_dict()
            # 尝试调用对象的dict方法
            elif hasattr(o, '__dict__'):
                return o.__dict__
        except Exception:
            pass
        
        # 调用父类的默认方法
        return super().default(o)


def json_dumps(obj: Any, **kwargs) -> str:
    """
    使用自定义编码器序列化对象
    
    Args:
        obj: 要序列化的对象
        **kwargs: 传递给json.dumps的参数
        
    Returns:
        JSON字符串
    """
    kwargs.setdefault('ensure_ascii', False)
    kwargs.setdefault('indent', 2)
    return json.dumps(obj, cls=CustomJSONEncoder, **kwargs)


def json_loads(s: str) -> Any:
    """
    反序列化JSON字符串
    
    Args:
        s: JSON字符串
        
    Returns:
        反序列化的对象
    """
    return json.loads(s)