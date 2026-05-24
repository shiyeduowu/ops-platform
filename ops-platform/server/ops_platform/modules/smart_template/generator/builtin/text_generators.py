"""
文本数据生成器

生成姓名、邮箱、地址等文本数据。
"""

import random
from typing import Any, Dict, List
from ..base import DataGenerator, GenerationContext, ColumnProfile


# 常用姓名库
SURNAMES = [
    '张', '李', '王', '赵', '刘', '陈', '杨', '黄', '周', '吴',
    '徐', '孙', '马', '朱', '胡', '郭', '林', '何', '高', '罗',
    '郑', '梁', '谢', '宋', '唐', '许', '韩', '冯', '邓', '曹',
    '彭', '曾', '萧', '田', '董', '袁', '潘', '于', '蒋', '蔡'
]

GIVEN_NAMES = [
    '伟', '芳', '娜', '秀英', '敏', '静', '丽', '强', '磊', '军',
    '洋', '勇', '艳', '杰', '涛', '明', '超', '秀兰', '霞', '平',
    '刚', '桂英', '文', '华', '飞', '玉兰', '欢', '玲', '桂兰', '婷',
    '鑫', '浩', '宇', '欣', '悦', '睿', '博', '雅', '思', '晨'
]


class RandomNameGenerator(DataGenerator):
    """随机中文姓名生成器"""

    @property
    def generator_id(self) -> str:
        return "random_name"

    @property
    def compatible_fields(self) -> List[str]:
        return ["name"]

    def generate(self, context: GenerationContext) -> str:
        return random.choice(SURNAMES) + random.choice(GIVEN_NAMES)

    def configure(self, sample_values: List, profile: ColumnProfile) -> Dict[str, Any]:
        return {}

    def priority(self) -> int:
        return 10

    def score_fit(self, profile: ColumnProfile) -> float:
        if profile.data_type == 'text' and 2 <= profile.avg_length <= 4:
            return 80.0
        return 30.0


class RandomEmailGenerator(DataGenerator):
    """随机邮箱生成器"""

    DOMAINS = ['qq.com', '163.com', '126.com', 'gmail.com', 'outlook.com', 'hotmail.com']

    @property
    def generator_id(self) -> str:
        return "random_email"

    @property
    def compatible_fields(self) -> List[str]:
        return ["email"]

    def generate(self, context: GenerationContext) -> str:
        username = ''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=8))
        domain = random.choice(self.DOMAINS)
        return f"{username}@{domain}"

    def configure(self, sample_values: List, profile: ColumnProfile) -> Dict[str, Any]:
        return {}

    def priority(self) -> int:
        return 10

    def score_fit(self, profile: ColumnProfile) -> float:
        if profile.sample_values:
            email_count = sum(1 for v in profile.sample_values if '@' in str(v))
            if email_count / len(profile.sample_values) > 0.5:
                return 90.0
        return 20.0


class FixedValueGenerator(DataGenerator):
    """固定值生成器（兜底）"""

    @property
    def generator_id(self) -> str:
        return "fixed"

    @property
    def compatible_fields(self) -> List[str]:
        return []  # 兼容所有字段，作为兜底

    def generate(self, context: GenerationContext) -> Any:
        config = context.column_config
        return config.get('default_value', '')

    def configure(self, sample_values: List, profile: ColumnProfile) -> Dict[str, Any]:
        if sample_values:
            # 使用最常见的值
            from collections import Counter
            counter = Counter(str(v) for v in sample_values if v)
            if counter:
                return {'default_value': counter.most_common(1)[0][0]}
        return {'default_value': ''}

    def priority(self) -> int:
        return 0  # 最低优先级，仅作为兜底

    def score_fit(self, profile: ColumnProfile) -> float:
        return 10.0
