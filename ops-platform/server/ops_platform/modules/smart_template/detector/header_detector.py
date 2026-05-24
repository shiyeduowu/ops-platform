# -*- coding: utf-8 -*-
"""
表头检测器

编排多个检测策略，通过加权投票选出最佳表头行。
"""

from typing import List, Dict, Optional
from .base import DetectionStrategy, HeaderCandidate
from .keyword_strategy import KeywordStrategy
from .statistical_strategy import StatisticalStrategy
from .style_strategy import StyleStrategy
from .structural_strategy import StructuralStrategy
from .voter import WeightedVoteAggregator
from ..config.settings import TemplateSettings


class HeaderDetector:
    """
    表头检测器

    编排多个检测策略，通过加权投票选出最佳表头行。
    """

    def __init__(self, settings: TemplateSettings = None):
        self._settings = settings or TemplateSettings()
        self._strategies = self._init_strategies()
        self._voter = WeightedVoteAggregator()

    def _init_strategies(self) -> List[DetectionStrategy]:
        """初始化所有检测策略"""
        return [
            KeywordStrategy(self._settings),
            StatisticalStrategy(),
            StyleStrategy(),
            StructuralStrategy()
        ]

    def detect(self, sheet, max_scan_rows: int = 15) -> Optional[HeaderCandidate]:
        """
        检测表头行

        Args:
            sheet: openpyxl worksheet 对象
            max_scan_rows: 最大扫描行数

        Returns:
            最佳表头候选行，若无则返回 None
        """
        candidates_per_strategy: Dict[str, List[HeaderCandidate]] = {}
        strategy_weights: Dict[str, float] = {}

        for strategy in self._strategies:
            try:
                candidates = strategy.detect(sheet, max_scan_rows)
                candidates_per_strategy[strategy.name] = candidates
                strategy_weights[strategy.name] = strategy.weight
            except Exception as e:
                print(f"Warning: Strategy {strategy.name} failed: {e}")

        return self._voter.aggregate(candidates_per_strategy, strategy_weights)

    def detect_detailed(self, sheet, max_scan_rows: int = 15) -> List[HeaderCandidate]:
        """
        检测表头行（详细模式）

        返回所有候选行，按得分降序排列。用于调试。

        Args:
            sheet: openpyxl worksheet 对象
            max_scan_rows: 最大扫描行数

        Returns:
            候选行列表，按得分降序排列
        """
        candidates_per_strategy: Dict[str, List[HeaderCandidate]] = {}
        strategy_weights: Dict[str, float] = {}

        for strategy in self._strategies:
            try:
                candidates = strategy.detect(sheet, max_scan_rows)
                candidates_per_strategy[strategy.name] = candidates
                strategy_weights[strategy.name] = strategy.weight
            except Exception as e:
                print(f"Warning: Strategy {strategy.name} failed: {e}")

        return self._voter.aggregate_detailed(candidates_per_strategy, strategy_weights)
