# -*- coding: utf-8 -*-
"""
结构策略

基于表格结构的表头检测策略。
检测合并单元格、边框、说明行等结构特征。
"""

from typing import List, Tuple, Set
from .base import DetectionStrategy, HeaderCandidate


class StructuralStrategy(DetectionStrategy):
    """
    结构策略

    分析表格的结构特征：
    - 合并单元格（表头常有合并）
    - 说明行检测（跳过纯文本说明）
    - 空行分隔（表头前常有空行）
    """

    @property
    def name(self) -> str:
        return "structural"

    @property
    def weight(self) -> float:
        return 0.20

    def detect(self, sheet, max_scan_rows: int = 15) -> List[HeaderCandidate]:
        candidates = []

        # 获取合并单元格信息
        merged_ranges = self._get_merged_ranges(sheet)

        for row_idx in range(1, min(max_scan_rows + 1, sheet.max_row + 1)):
            score, reasons = self._analyze_row_structure(sheet, row_idx, merged_ranges)
            if score > 0:
                candidates.append(HeaderCandidate(
                    row_index=row_idx,
                    score=min(score, 1.0),
                    strategy_name=self.name,
                    reasons=reasons
                ))

        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates

    def _get_merged_ranges(self, sheet) -> Set[int]:
        """获取包含合并单元格的行号集合"""
        merged_rows = set()
        for merge_range in sheet.merged_cells.ranges:
            for row in range(merge_range.min_row, merge_range.max_row + 1):
                merged_rows.add(row)
        return merged_rows

    def _analyze_row_structure(
        self,
        sheet,
        row_idx: int,
        merged_rows: Set[int]
    ) -> Tuple[float, List[str]]:
        """分析一行的结构特征"""
        score = 0.0
        reasons = []

        # 检查是否是合并单元格行
        if row_idx in merged_rows:
            score += 0.3
            reasons.append("包含合并单元格")

        # 检查是否是说明行（应跳过）
        if self._is_description_row(sheet, row_idx):
            score -= 0.5  # 降低得分
            reasons.append("疑似说明行（长文本）")

        # 检查前一行是否为空行（表头前常有空行）
        if row_idx > 1:
            prev_values = self._get_row_values(sheet, row_idx - 1)
            if self._is_empty_row(prev_values):
                score += 0.2
                reasons.append("前一行为空行")

        # 检查行内单元格数量变化
        non_empty = self._count_non_empty(sheet, row_idx)
        if non_empty >= 3:
            score += 0.1
            reasons.append(f"非空单元格: {non_empty}")

        # 检查是否有边框（表头常有边框）
        border_ratio = self._check_borders(sheet, row_idx)
        if border_ratio >= 0.5:
            score += 0.2
            reasons.append(f"边框比例: {border_ratio:.0%}")

        return score, reasons

    def _is_description_row(self, sheet, row_idx: int) -> bool:
        """
        检测是否是说明行

        说明行特征：
        - 单元格文本很长（> 30字符）
        - 只有少数单元格有内容
        """
        long_text_count = 0
        non_empty = 0

        for col in range(1, min(sheet.max_column + 1, 21)):
            cell = sheet.cell(row=row_idx, column=col)
            if cell.value is not None:
                val = str(cell.value).strip()
                if val:
                    non_empty += 1
                    if len(val) > 30:
                        long_text_count += 1

        # 如果有长文本且非空列数少，可能是说明行
        if long_text_count > 0 and non_empty <= 3:
            return True

        return False

    def _count_non_empty(self, sheet, row_idx: int) -> int:
        """计算一行中非空单元格数量"""
        count = 0
        for col in range(1, min(sheet.max_column + 1, 21)):
            cell = sheet.cell(row=row_idx, column=col)
            if cell.value is not None and str(cell.value).strip():
                count += 1
        return count

    def _check_borders(self, sheet, row_idx: int) -> float:
        """检查一行中有边框的单元格比例"""
        non_empty = 0
        bordered = 0

        for col in range(1, min(sheet.max_column + 1, 21)):
            cell = sheet.cell(row=row_idx, column=col)
            if cell.value is not None and str(cell.value).strip():
                non_empty += 1
                if cell.border and (
                    cell.border.top or cell.border.bottom or
                    cell.border.left or cell.border.right
                ):
                    bordered += 1

        return bordered / non_empty if non_empty > 0 else 0.0
