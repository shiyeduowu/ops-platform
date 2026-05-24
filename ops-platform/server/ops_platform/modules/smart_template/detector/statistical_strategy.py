# -*- coding: utf-8 -*-
"""
统计策略

基于数据类型变化的表头检测策略。
表头行通常是"短文本"到"数据"的转折点。
"""

from typing import List, Tuple
from .base import DetectionStrategy, HeaderCandidate


class StatisticalStrategy(DetectionStrategy):
    """
    统计策略

    分析每行的数据类型分布，检测从"表头文本"到"数据"的转折点。
    表头行特征：大部分单元格是短文本，下一行开始出现长数据。
    """

    @property
    def name(self) -> str:
        return "statistical"

    @property
    def weight(self) -> float:
        return 0.25

    def detect(self, sheet, max_scan_rows: int = 15) -> List[HeaderCandidate]:
        candidates = []

        # 收集前 N 行的统计信息
        row_stats = []
        for row_idx in range(1, min(max_scan_rows + 2, sheet.max_row + 1)):
            stats = self._analyze_row(sheet, row_idx)
            row_stats.append((row_idx, stats))

        if len(row_stats) < 2:
            return candidates

        # 分析每行，寻找转折点
        for i in range(len(row_stats) - 1):
            row_idx, current = row_stats[i]
            _, next_row = row_stats[i + 1]

            score, reasons = self._detect_transition(current, next_row)
            if score > 0:
                candidates.append(HeaderCandidate(
                    row_index=row_idx,
                    score=min(score, 1.0),
                    strategy_name=self.name,
                    reasons=reasons
                ))

        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates

    def _analyze_row(self, sheet, row_idx: int) -> dict:
        """分析一行的统计信息"""
        values = []
        for col in range(1, min(sheet.max_column + 1, 21)):
            cell = sheet.cell(row=row_idx, column=col)
            val = cell.value
            if val is not None:
                values.append(str(val).strip())

        if not values:
            return {
                'non_empty': 0,
                'avg_length': 0,
                'numeric_ratio': 0,
                'short_text_ratio': 0,
                'has_formula': False
            }

        non_empty = len(values)
        avg_length = sum(len(v) for v in values) / non_empty

        # 数字比例
        numeric_count = 0
        for v in values:
            try:
                float(v.replace(',', ''))
                numeric_count += 1
            except (ValueError, TypeError):
                pass
        numeric_ratio = numeric_count / non_empty

        # 短文本比例（长度 <= 10）
        short_text_count = sum(1 for v in values if len(v) <= 10)
        short_text_ratio = short_text_count / non_empty

        return {
            'non_empty': non_empty,
            'avg_length': avg_length,
            'numeric_ratio': numeric_ratio,
            'short_text_ratio': short_text_ratio,
        }

    def _detect_transition(self, current: dict, next_row: dict) -> Tuple[float, List[str]]:
        """
        检测两行之间的数据类型转折

        表头行特征：
        - 当前行：短文本比例高，平均长度短
        - 下一行：数字比例上升，或平均长度变化
        """
        score = 0.0
        reasons = []

        # 条件1：当前行有内容
        if current['non_empty'] == 0:
            return 0.0, []

        # 条件2：当前行短文本比例高（表头通常是短标签）
        if current['short_text_ratio'] >= 0.7:
            score += 0.4
            reasons.append(f"短文本比例高: {current['short_text_ratio']:.0%}")

        # 条件3：下一行数字比例上升（数据开始）
        if next_row['numeric_ratio'] > current['numeric_ratio'] + 0.2:
            score += 0.3
            reasons.append(f"下一行数字比例上升: {next_row['numeric_ratio']:.0%}")

        # 条件4：平均长度变化（表头短，数据长或反之）
        if current['avg_length'] < 15 and next_row['avg_length'] > current['avg_length']:
            score += 0.2
            reasons.append(f"平均长度变化: {current['avg_length']:.1f} -> {next_row['avg_length']:.1f}")

        # 条件5：当前行非空列数较多（表头通常每列都有标签）
        if current['non_empty'] >= 3:
            score += 0.1
            reasons.append(f"非空列数: {current['non_empty']}")

        return score, reasons
