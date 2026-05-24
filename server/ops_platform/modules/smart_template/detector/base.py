"""
表头检测策略基类

定义多策略表头检测的抽象接口。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple


@dataclass
class HeaderCandidate:
    """
    表头候选行

    Attributes:
        row_index: 行索引（1-based）
        score: 置信度得分（0.0-1.0）
        strategy_name: 策略名称
        reasons: 得分原因列表
    """
    row_index: int
    score: float
    strategy_name: str
    reasons: List[str] = field(default_factory=list)


class DetectionStrategy(ABC):
    """
    表头检测策略抽象基类

    每个策略实现一种检测方法，返回候选行列表。
    通过加权投票聚合多个策略的结果。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """策略名称"""

    @property
    @abstractmethod
    def weight(self) -> float:
        """策略权重（0.0-1.0），用于加权投票"""

    @abstractmethod
    def detect(self, sheet, max_scan_rows: int = 15) -> List[HeaderCandidate]:
        """
        检测表头行

        Args:
            sheet: openpyxl worksheet 对象
            max_scan_rows: 最大扫描行数

        Returns:
            候选行列表，按得分降序排列
        """

    def _get_row_values(self, sheet, row_index: int, max_cols: int = 20) -> List[str]:
        """获取指定行的值列表"""
        values = []
        for col in range(1, min(sheet.max_column + 1, max_cols + 1)):
            cell = sheet.cell(row=row_index, column=col)
            values.append(str(cell.value).strip() if cell.value else '')
        return values

    def _is_empty_row(self, values: List[str]) -> bool:
        """判断是否为空行"""
        return all(not v for v in values)
