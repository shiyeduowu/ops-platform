"""
加权投票聚合器

聚合多个检测策略的结果，通过加权投票选出最佳表头行。
"""

from typing import Dict, List, Optional
from collections import defaultdict
from .base import HeaderCandidate


class WeightedVoteAggregator:
    """
    加权投票聚合器

    算法：
    1. 每个策略返回带得分的候选行列表
    2. 对每个候选行，计算加权总分：final_score = Σ(strategy_score × weight)
    3. 共识奖励：若3+策略对同一行得分>0.5，final_score × 1.2
    4. 返回得分最高的候选行
    """

    def __init__(self, consensus_threshold: float = 0.5, consensus_bonus: float = 1.2):
        """
        Args:
            consensus_threshold: 共识阈值，策略得分超过此值视为"同意"
            consensus_bonus: 共识奖励系数
        """
        self.consensus_threshold = consensus_threshold
        self.consensus_bonus = consensus_bonus

    def aggregate(
        self,
        candidates_per_strategy: Dict[str, List[HeaderCandidate]],
        strategy_weights: Dict[str, float]
    ) -> Optional[HeaderCandidate]:
        """
        聚合多个策略的候选结果

        Args:
            candidates_per_strategy: {策略名称: 候选列表}
            strategy_weights: {策略名称: 权重}

        Returns:
            最佳候选行，若无候选则返回 None
        """
        if not candidates_per_strategy:
            return None

        # 构建行得分映射: row_index -> {策略名: 得分}
        row_scores: Dict[int, Dict[str, float]] = defaultdict(dict)

        for strategy_name, candidates in candidates_per_strategy.items():
            weight = strategy_weights.get(strategy_name, 0.0)
            for candidate in candidates:
                row_scores[candidate.row_index][strategy_name] = candidate.score

        # 计算加权总分
        final_candidates: List[HeaderCandidate] = []

        for row_index, strategy_scores in row_scores.items():
            # 加权求和
            weighted_sum = 0.0
            for strategy_name, score in strategy_scores.items():
                weight = strategy_weights.get(strategy_name, 0.0)
                weighted_sum += score * weight

            # 共识奖励：统计有多少策略"同意"该行
            consensus_count = sum(
                1 for score in strategy_scores.values()
                if score >= self.consensus_threshold
            )
            if consensus_count >= 3:
                weighted_sum *= self.consensus_bonus

            # 收集原因
            reasons = []
            for strategy_name, score in strategy_scores.items():
                reasons.append(f"{strategy_name}: {score:.2f}")

            final_candidates.append(HeaderCandidate(
                row_index=row_index,
                score=weighted_sum,
                strategy_name="aggregated",
                reasons=reasons
            ))

        if not final_candidates:
            return None

        # 返回得分最高的候选
        return max(final_candidates, key=lambda c: c.score)

    def aggregate_detailed(
        self,
        candidates_per_strategy: Dict[str, List[HeaderCandidate]],
        strategy_weights: Dict[str, float]
    ) -> List[HeaderCandidate]:
        """
        聚合并返回所有候选行（按得分降序）

        用于调试和分析。

        Args:
            candidates_per_strategy: {策略名称: 候选列表}
            strategy_weights: {策略名称: 权重}

        Returns:
            所有候选行列表，按得分降序排列
        """
        if not candidates_per_strategy:
            return []

        # 构建行得分映射
        row_scores: Dict[int, Dict[str, float]] = defaultdict(dict)

        for strategy_name, candidates in candidates_per_strategy.items():
            weight = strategy_weights.get(strategy_name, 0.0)
            for candidate in candidates:
                row_scores[candidate.row_index][strategy_name] = candidate.score

        # 计算加权总分
        final_candidates: List[HeaderCandidate] = []

        for row_index, strategy_scores in row_scores.items():
            weighted_sum = 0.0
            for strategy_name, score in strategy_scores.items():
                weight = strategy_weights.get(strategy_name, 0.0)
                weighted_sum += score * weight

            consensus_count = sum(
                1 for score in strategy_scores.values()
                if score >= self.consensus_threshold
            )
            if consensus_count >= 3:
                weighted_sum *= self.consensus_bonus

            reasons = []
            for strategy_name, score in strategy_scores.items():
                reasons.append(f"{strategy_name}: {score:.2f}")

            final_candidates.append(HeaderCandidate(
                row_index=row_index,
                score=weighted_sum,
                strategy_name="aggregated",
                reasons=reasons
            ))

        # 按得分降序排列
        final_candidates.sort(key=lambda c: c.score, reverse=True)
        return final_candidates
