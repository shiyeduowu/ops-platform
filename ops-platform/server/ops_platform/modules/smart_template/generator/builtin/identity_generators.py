"""
身份信息生成器

生成身份证号、学号等身份标识数据。
"""

import random
from typing import Any, Dict, List
from ..base import DataGenerator, GenerationContext, ColumnProfile


# 身份证地区码（江苏南京）
AREA_CODES = [
    '320102', '320104', '320105', '320106', '320111',
    '320113', '320114', '320115', '320116', '320117',
    '320118', '320119', '320120', '320121', '320122'
]


class RandomIdCardGenerator(DataGenerator):
    """随机身份证号生成器"""

    @property
    def generator_id(self) -> str:
        return "random_id_card"

    @property
    def compatible_fields(self) -> List[str]:
        return ["id_card"]

    def generate(self, context: GenerationContext) -> str:
        # 地区码
        area = random.choice(AREA_CODES)

        # 出生日期（18-25岁）
        year = random.randint(1999, 2006)
        month = random.randint(1, 12)
        day = random.randint(1, 28)  # 简化处理
        birthday = f"{year}{month:02d}{day:02d}"

        # 顺序码
        seq = random.randint(10, 99)

        # 校验码（简化处理）
        check = random.randint(0, 9)

        return f"{area}{birthday}{seq}{check}"

    def configure(self, sample_values: List, profile: ColumnProfile) -> Dict[str, Any]:
        return {}

    def priority(self) -> int:
        return 10

    def score_fit(self, profile: ColumnProfile) -> float:
        # 验证样本是否为身份证格式
        if profile.sample_values:
            id_count = sum(
                1 for v in profile.sample_values
                if self._is_id_card(str(v))
            )
            if id_count / len(profile.sample_values) > 0.5:
                return 95.0
        return 30.0

    def _is_id_card(self, value: str) -> bool:
        """验证身份证号格式"""
        cleaned = value.strip()
        return len(cleaned) == 18 and cleaned[:17].isdigit()
