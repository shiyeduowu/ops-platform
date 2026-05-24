# -*- coding: utf-8 -*-
"""
样式策略

基于单元格样式的表头检测策略。
表头行通常有特殊样式：加粗、背景色、居中对齐等。
"""

from typing import List, Tuple
from .base import DetectionStrategy, HeaderCandidate


class StyleStrategy(DetectionStrategy):
    """
    样式策略

    分析每行的样式特征，检测表头行的典型样式：
    - 字体加粗
    - 背景色/填充色
    - 居中对齐
    - 边框
    """

    @property
    def name(self) -> str:
        return "style"

    @property
    def weight(self) -> float:
        return 0.20

    def detect(self, sheet, max_scan_rows: int = 15) -> List[HeaderCandidate]:
        candidates = []

        for row_idx in range(1, min(max_scan_rows + 1, sheet.max_row + 1)):
            score, reasons = self._analyze_row_style(sheet, row_idx)
            if score > 0:
                candidates.append(HeaderCandidate(
                    row_index=row_idx,
                    score=min(score, 1.0),
                    strategy_name=self.name,
                    reasons=reasons
                ))

        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates

    def _analyze_row_style(self, sheet, row_idx: int) -> Tuple[float, List[str]]:
        """分析一行的样式特征"""
        bold_count = 0
        fill_count = 0
        center_count = 0
        border_count = 0
        non_empty = 0

        for col in range(1, min(sheet.max_column + 1, 21)):
            cell = sheet.cell(row=row_idx, column=col)
            if cell.value is None or str(cell.value).strip() == '':
                continue

            non_empty += 1

            # 检查字体加粗
            if cell.font and cell.font.bold:
                bold_count += 1

            # 检查背景填充
            if cell.fill and cell.fill.start_color and cell.fill.start_color.rgb:
                rgb = str(cell.fill.start_color.rgb)
                if rgb and rgb != '00000000':  # 非默认色
                    fill_count += 1

            # 检查居中对齐
            if cell.alignment and cell.alignment.horizontal == 'center':
                center_count += 1

            # 检查边框
            if cell.border and (
                cell.border.top or cell.border.bottom or
                cell.border.left or cell.border.right
            ):
                border_count += 1

        if non_empty == 0:
            return 0.0, []

        score = 0.0
        reasons = []

        # 加粗比例
        bold_ratio = bold_count / non_empty
        if bold_ratio >= 0.5:
            score += 0.4 * bold_ratio
            reasons.append(f"加粗比例: {bold_ratio:.0%}")

        # 填充色比例
        fill_ratio = fill_count / non_empty
        if fill_ratio >= 0.3:
            score += 0.3 * fill_ratio
            reasons.append(f"背景色比例: {fill_ratio:.0%}")

        # 居中对齐比例
        center_ratio = center_count / non_empty
        if center_ratio >= 0.5:
            score += 0.2 * center_ratio
            reasons.append(f"居中对齐比例: {center_ratio:.0%}")

        # 边框比例
        border_ratio = border_count / non_empty
        if border_ratio >= 0.3:
            score += 0.1 * border_ratio
            reasons.append(f"边框比例: {border_ratio:.0%}")

        return score, reasons
