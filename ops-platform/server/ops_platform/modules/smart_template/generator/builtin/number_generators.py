"""
数字数据生成器

生成递增序列、随机数等数字数据。
"""

import re
from typing import Any, Dict, List, Tuple
from ..base import DataGenerator, GenerationContext, ColumnProfile


class IncrementGenerator(DataGenerator):
    """递增数字生成器"""

    @property
    def generator_id(self) -> str:
        return "increment"

    @property
    def compatible_fields(self) -> List[str]:
        return []  # 通过 profile 匹配

    def generate(self, context: GenerationContext) -> Any:
        config = context.column_config
        start = config.get('start', 1)
        step = config.get('step', 1)
        return start + context.row_index * step

    def configure(self, sample_values: List, profile: ColumnProfile) -> Dict[str, Any]:
        if not sample_values:
            return {'start': 1, 'step': 1}

        try:
            nums = [float(str(v).replace(',', '')) for v in sample_values if v is not None]
            if len(nums) >= 2:
                start = nums[0]
                step = nums[1] - nums[0]
                return {'start': start, 'step': step}
        except (ValueError, TypeError):
            pass

        return {'start': 1, 'step': 1}

    def priority(self) -> int:
        return 5

    def score_fit(self, profile: ColumnProfile) -> float:
        if profile.data_type == 'numeric' and profile.is_increasing:
            return 90.0
        return 20.0


class SequenceGenerator(DataGenerator):
    """带前缀的序列生成器（如 EXAM001, STU0001）"""

    @property
    def generator_id(self) -> str:
        return "sequence"

    @property
    def compatible_fields(self) -> List[str]:
        return ["student_no", "exam_no"]

    def generate(self, context: GenerationContext) -> str:
        config = context.column_config
        prefix = config.get('prefix', '')
        start = config.get('start', 1)
        step = config.get('step', 1)
        num_digits = config.get('num_digits', 8)

        # 如果有组信息，按组递增
        if context.group_index >= 0 and config.get('per_group', False):
            num = start + context.group_index * step
        else:
            num = start + context.row_index * step

        return f"{prefix}{int(num):0{num_digits}d}"

    def configure(self, sample_values: List, profile: ColumnProfile) -> Dict[str, Any]:
        if not sample_values:
            return {'prefix': '', 'start': 1, 'step': 1, 'num_digits': 8}

        first = str(sample_values[0])
        match = re.match(r'^([a-zA-Z一-龥]*?)(\d+)$', first)
        if match:
            prefix = match.group(1)
            start = int(match.group(2))
            num_digits = len(match.group(2))

            # 计算步长
            if len(sample_values) >= 2:
                second = str(sample_values[1])
                m2 = re.match(r'^' + re.escape(prefix) + r'(\d+)$', second)
                if m2:
                    step = int(m2.group(1)) - start
                else:
                    step = 1
            else:
                step = 1

            return {
                'prefix': prefix,
                'start': start,
                'step': step,
                'num_digits': num_digits
            }

        return {'prefix': '', 'start': 1, 'step': 1, 'num_digits': 8}

    def priority(self) -> int:
        return 8

    def score_fit(self, profile: ColumnProfile) -> float:
        if profile.prefix_pattern:
            return 85.0
        if profile.data_type == 'text' and profile.is_increasing:
            return 70.0
        return 20.0


class RandomNumberGenerator(DataGenerator):
    """随机数生成器"""

    @property
    def generator_id(self) -> str:
        return "random_number"

    @property
    def compatible_fields(self) -> List[str]:
        return ["score"]

    def generate(self, context: GenerationContext) -> float:
        config = context.column_config
        min_val = config.get('min_value', 60)
        max_val = config.get('max_value', 100)
        import random
        return round(random.uniform(min_val, max_val), 1)

    def configure(self, sample_values: List, profile: ColumnProfile) -> Dict[str, Any]:
        if profile.value_range:
            return {
                'min_value': profile.value_range[0],
                'max_value': profile.value_range[1]
            }
        return {'min_value': 60, 'max_value': 100}

    def priority(self) -> int:
        return 5

    def score_fit(self, profile: ColumnProfile) -> float:
        if profile.data_type == 'numeric':
            return 60.0
        return 20.0
