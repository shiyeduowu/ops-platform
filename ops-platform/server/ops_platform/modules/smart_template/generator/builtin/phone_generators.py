"""
手机号数据生成器

生成随机手机号和递增手机号。
"""

import random
from typing import Any, Dict, List
from ..base import DataGenerator, GenerationContext, ColumnProfile


# 手机号前缀
PHONE_PREFIXES = [
    '130', '131', '132', '133', '134', '135', '136', '137', '138', '139',
    '150', '151', '152', '153', '155', '156', '157', '158', '159',
    '170', '176', '177', '178',
    '180', '181', '182', '183', '184', '185', '186', '187', '188', '189',
    '191', '193', '195', '196', '197', '198', '199'
]


class RandomPhoneGenerator(DataGenerator):
    """随机手机号生成器"""

    @property
    def generator_id(self) -> str:
        return "random_phone"

    @property
    def compatible_fields(self) -> List[str]:
        return ["phone"]

    def generate(self, context: GenerationContext) -> str:
        prefix = random.choice(PHONE_PREFIXES)
        suffix = ''.join([str(random.randint(0, 9)) for _ in range(8)])
        return prefix + suffix

    def configure(self, sample_values: List, profile: ColumnProfile) -> Dict[str, Any]:
        return {}

    def priority(self) -> int:
        return 10

    def score_fit(self, profile: ColumnProfile) -> float:
        # 验证样本是否为手机号格式
        if profile.sample_values:
            phone_count = sum(
                1 for v in profile.sample_values
                if self._is_phone(str(v))
            )
            if phone_count / len(profile.sample_values) > 0.5:
                return 90.0
        return 40.0

    def _is_phone(self, value: str) -> bool:
        """验证手机号格式"""
        cleaned = ''.join(c for c in value if c.isdigit())
        return len(cleaned) == 11 and cleaned[0] == '1'


class IncrementPhoneGenerator(DataGenerator):
    """递增手机号生成器"""

    @property
    def generator_id(self) -> str:
        return "increment_phone"

    @property
    def compatible_fields(self) -> List[str]:
        return ["phone"]

    def generate(self, context: GenerationContext) -> str:
        config = context.column_config
        start = config.get('start', 13000000000)
        return str(int(start) + context.row_index)

    def configure(self, sample_values: List, profile: ColumnProfile) -> Dict[str, Any]:
        if not sample_values:
            return {'start': 13000000000}

        first = str(sample_values[0])
        cleaned = ''.join(c for c in first if c.isdigit())
        if len(cleaned) == 11:
            return {'start': int(cleaned)}
        return {'start': 13000000000}

    def priority(self) -> int:
        return 8

    def score_fit(self, profile: ColumnProfile) -> float:
        if profile.is_increasing and profile.data_type in ('numeric', 'mixed'):
            # 检查是否为递增手机号
            if profile.sample_values:
                nums = []
                for v in profile.sample_values[:5]:
                    cleaned = ''.join(c for c in str(v) if c.isdigit())
                    if len(cleaned) == 11:
                        nums.append(int(cleaned))
                if len(nums) >= 2 and all(nums[i] < nums[i+1] for i in range(len(nums)-1)):
                    return 85.0
        return 30.0
