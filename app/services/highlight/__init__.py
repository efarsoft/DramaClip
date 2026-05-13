"""
高光识别服务
"""

from .scorer import HighlightScorer
from .selector import HighlightSelector
from .sorter import HighlightSorter, SortStrategy

__all__ = [
    "HighlightScorer",
    "HighlightSelector",
    "HighlightSorter",
    "SortStrategy",
]
