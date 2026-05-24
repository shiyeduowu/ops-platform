# -*- coding: utf-8 -*-
"""表头检测模块"""

from .base import DetectionStrategy, HeaderCandidate
from .voter import WeightedVoteAggregator
from .keyword_strategy import KeywordStrategy
from .statistical_strategy import StatisticalStrategy
from .style_strategy import StyleStrategy
from .structural_strategy import StructuralStrategy
from .header_detector import HeaderDetector

__all__ = [
    'DetectionStrategy', 'HeaderCandidate', 'WeightedVoteAggregator',
    'KeywordStrategy', 'StatisticalStrategy', 'StyleStrategy', 'StructuralStrategy',
    'HeaderDetector'
]
