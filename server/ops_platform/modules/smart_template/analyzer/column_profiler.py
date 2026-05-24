"""
列统计分析器

分析每列的数据特征：类型、唯一值、递增性、循环性等。
为语义匹配提供数据验证支持。
"""

import re
from typing import List, Any, Optional, Tuple
from ..generator.base import ColumnProfile


class ColumnProfiler:
    """
    列统计分析器

    计算列的统计特征，用于：
    1. 语义匹配的第二阶段验证（消歧）
    2. 生成器配置（推断参数）
    3. 关系推断（判断组结构）
    """

    def profile(
        self,
        index: int,
        header: str,
        sample_values: List[Any],
        raw_header: str = ''
    ) -> ColumnProfile:
        """
        分析列的统计特征

        Args:
            index: 列索引（0-based）
            header: 表头名称（已清理）
            sample_values: 样本值列表
            raw_header: 原始表头（含*号等标记）

        Returns:
            ColumnProfile 统计分析结果
        """
        # 过滤非空值
        non_empty = [v for v in sample_values if v is not None and str(v).strip()]
        non_null_count = len(non_empty)

        if non_null_count == 0:
            return ColumnProfile(
                index=index,
                header=header,
                raw_header=raw_header,
                non_null_count=0,
                unique_count=0,
                data_type='empty',
                sample_values=sample_values
            )

        # 转为字符串列表
        str_values = [str(v).strip() for v in non_empty]

        # 计算各项指标
        unique_count = len(set(str_values))
        data_type = self._detect_data_type(str_values)
        is_increasing = self._check_increasing(str_values)
        is_cyclic, cycle_length = self._check_cyclic(str_values)
        value_range = self._get_value_range(str_values, data_type)
        prefix_pattern = self._extract_prefix(str_values)
        avg_length = sum(len(s) for s in str_values) / len(str_values)
        is_required = '*' in raw_header

        return ColumnProfile(
            index=index,
            header=header,
            raw_header=raw_header,
            non_null_count=non_null_count,
            unique_count=unique_count,
            data_type=data_type,
            is_increasing=is_increasing,
            is_cyclic=is_cyclic,
            cycle_length=cycle_length,
            value_range=value_range,
            prefix_pattern=prefix_pattern,
            avg_length=avg_length,
            is_required=is_required,
            sample_values=sample_values
        )

    def _detect_data_type(self, values: List[str]) -> str:
        """
        检测数据类型

        Returns:
            "numeric": 纯数字
            "text": 纯文本
            "mixed": 混合
            "date": 日期
        """
        if not values:
            return 'empty'

        numeric_count = 0
        date_count = 0

        for v in values:
            if self._is_numeric(v):
                numeric_count += 1
            elif self._is_date(v):
                date_count += 1

        total = len(values)
        if numeric_count / total > 0.8:
            return 'numeric'
        if date_count / total > 0.8:
            return 'date'
        if numeric_count / total > 0.3:
            return 'mixed'
        return 'text'

    def _is_numeric(self, value: str) -> bool:
        """判断是否为数字"""
        try:
            float(value.replace(',', ''))
            return True
        except (ValueError, TypeError):
            return False

    def _is_date(self, value: str) -> bool:
        """判断是否为日期格式"""
        date_patterns = [
            r'^\d{4}[-/]\d{1,2}[-/]\d{1,2}$',
            r'^\d{1,2}[-/]\d{1,2}[-/]\d{4}$',
            r'^\d{4}年\d{1,2}月\d{1,2}日$',
        ]
        return any(re.match(p, value) for p in date_patterns)

    def _check_increasing(self, values: List[str]) -> bool:
        """检查是否递增"""
        if len(values) < 2:
            return False

        try:
            nums = [float(v.replace(',', '')) for v in values if self._is_numeric(v)]
            if len(nums) < 2:
                return False
            return all(nums[i] <= nums[i + 1] for i in range(len(nums) - 1))
        except (ValueError, TypeError):
            # 尝试字符串递增（如 EXAM001, EXAM002）
            if all(self._has_numeric_suffix(v) for v in values[:5]):
                nums = [int(re.search(r'\d+$', v).group()) for v in values[:5]]
                return all(nums[i] <= nums[i + 1] for i in range(len(nums) - 1))
            return False

    def _has_numeric_suffix(self, value: str) -> bool:
        """检查是否有数字后缀"""
        return bool(re.search(r'\d+$', value))

    def _check_cyclic(self, values: List[str]) -> Tuple[bool, Optional[int]]:
        """
        检查是否循环

        Returns:
            (是否循环, 循环长度)
        """
        if len(values) < 4:
            return False, None

        # 尝试检测不同周期
        for cycle_len in range(2, min(len(values) // 2 + 1, 20)):
            is_cyclic = True
            for i in range(cycle_len, min(len(values), cycle_len * 3)):
                if values[i] != values[i % cycle_len]:
                    is_cyclic = False
                    break
            if is_cyclic:
                return True, cycle_len

        return False, None

    def _get_value_range(self, values: List[str], data_type: str) -> Optional[Tuple]:
        """获取值范围"""
        if data_type == 'numeric':
            try:
                nums = [float(v.replace(',', '')) for v in values if self._is_numeric(v)]
                if nums:
                    return (min(nums), max(nums))
            except (ValueError, TypeError):
                pass
        return None

    def _extract_prefix(self, values: List[str]) -> Optional[str]:
        """
        提取前缀模式

        如 EXAM001, EXAM002 -> "EXAM"
        """
        if not values:
            return None

        first = values[0]
        match = re.match(r'^([a-zA-Z一-龥]+?)(\d+)$', first)
        if not match:
            return None

        prefix = match.group(1)
        # 验证其他值是否也有相同前缀
        for v in values[1:5]:
            if not v.startswith(prefix):
                return None

        return prefix

    def detect_sequence_info(
        self,
        values: List[str]
    ) -> Optional[Tuple[str, int, int, int]]:
        """
        检测序列信息

        Returns:
            (前缀, 起始值, 步长, 数字位数) 或 None
        """
        if not values or not self._has_numeric_suffix(values[0]):
            return None

        first = values[0]
        match = re.match(r'^([a-zA-Z一-龥]*?)(\d+)$', first)
        if not match:
            return None

        prefix = match.group(1)
        nums = []
        for v in values:
            m = re.match(r'^' + re.escape(prefix) + r'(\d+)$', v)
            if m:
                nums.append(int(m.group(1)))

        if len(nums) < 2:
            return prefix, nums[0] if nums else 1, 1, len(match.group(2))

        step = nums[1] - nums[0]
        num_digits = len(match.group(2))

        return prefix, nums[0], step, num_digits

    def detect_group_structure(
        self,
        group_values: List[Any]
    ) -> Tuple[int, int]:
        """
        检测组结构

        Args:
            group_values: 组号列的样本值

        Returns:
            (组数, 每组行数)
        """
        if not group_values:
            return 1, 1

        str_values = [str(v).strip() for v in group_values if v is not None]
        if not str_values:
            return 1, 1

        # 统计每个组出现的次数
        first_group = str_values[0]
        rows_per_group = sum(1 for v in str_values if v == first_group)

        # 统计组数
        unique_groups = len(set(str_values))
        num_groups = unique_groups

        return num_groups, max(1, rows_per_group)
