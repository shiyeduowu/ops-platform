"""
数据生成器基类

定义可插拔数据生成器的抽象接口。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class GenerationContext:
    """
    数据生成上下文

    包含生成单个值所需的全部信息。

    Attributes:
        row_index: 当前行号（0-based）
        group_index: 当前组号（0-based）
        seat_index: 当前座位号（0-based，组内）
        column_config: 列配置（从样本数据解析）
        related_values: 相关列的值（用于耦合生成）
        total_rows: 总行数
        total_groups: 总组数
        rows_per_group: 每组行数
    """
    row_index: int = 0
    group_index: int = 0
    seat_index: int = 0
    column_config: Dict[str, Any] = field(default_factory=dict)
    related_values: Dict[str, Any] = field(default_factory=dict)
    total_rows: int = 0
    total_groups: int = 0
    rows_per_group: int = 1


@dataclass
class ColumnProfile:
    """
    列统计分析结果

    Attributes:
        index: 列索引（0-based）
        header: 表头名称
        raw_header: 原始表头（含*号等标记）
        non_null_count: 非空值数量
        unique_count: 唯一值数量
        data_type: 数据类型（numeric/text/mixed/date）
        is_increasing: 是否递增
        is_cyclic: 是否循环
        cycle_length: 循环长度（如果循环）
        value_range: 值范围（最小值，最大值）
        prefix_pattern: 前缀模式（如 "EXAM" from "EXAM001"）
        avg_length: 平均长度
        is_required: 是否必填（有*标记）
        sample_values: 样本值列表
    """
    index: int
    header: str
    raw_header: str = ''
    non_null_count: int = 0
    unique_count: int = 0
    data_type: str = 'text'  # numeric/text/mixed/date
    is_increasing: bool = False
    is_cyclic: bool = False
    cycle_length: Optional[int] = None
    value_range: Optional[tuple] = None
    prefix_pattern: Optional[str] = None
    avg_length: float = 0.0
    is_required: bool = False
    sample_values: List[Any] = field(default_factory=list)


@dataclass
class FieldMatch:
    """
    字段匹配结果

    Attributes:
        field_id: 语义字段ID
        display_name: 显示名称
        confidence: 置信度（0-100）
        match_type: 匹配类型（exact/contains/fuzzy/data_validated）
    """
    field_id: str
    display_name: str
    confidence: float
    match_type: str


class DataGenerator(ABC):
    """
    数据生成器抽象基类

    每个生成器负责一种数据类型（如手机号、姓名等）。
    生成器注册到 GeneratorRegistry，根据 SemanticField 选择。
    """

    @property
    @abstractmethod
    def generator_id(self) -> str:
        """生成器唯一标识符，如 'random_phone', 'increment_sequence'"""

    @property
    @abstractmethod
    def compatible_fields(self) -> List[str]:
        """兼容的语义字段ID列表"""

    @abstractmethod
    def generate(self, context: GenerationContext) -> Any:
        """
        生成单个值

        Args:
            context: 生成上下文

        Returns:
            生成的值
        """

    @abstractmethod
    def configure(self, sample_values: List, profile: ColumnProfile) -> Dict[str, Any]:
        """
        从样本数据配置生成器

        Args:
            sample_values: 样本值列表
            profile: 列统计分析结果

        Returns:
            配置字典，存储在 ColumnInfo.config 中
        """

    def priority(self) -> int:
        """优先级，更高的优先级在多个匹配时优先选择"""
        return 0

    def score_fit(self, profile: ColumnProfile) -> float:
        """
        评估生成器与列的匹配度

        Args:
            profile: 列统计分析结果

        Returns:
            匹配度得分（0-100）
        """
        return 50.0  # 默认中等匹配度
