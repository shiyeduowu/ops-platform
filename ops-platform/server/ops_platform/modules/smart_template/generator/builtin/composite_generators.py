"""
复合数据生成器

生成耦合关系的数据，如组号+座位号。
"""

from typing import Any, Dict, List
from ..base import DataGenerator, GenerationContext, ColumnProfile


class GroupIdGenerator(DataGenerator):
    """组号生成器"""

    @property
    def generator_id(self) -> str:
        return "group_id"

    @property
    def compatible_fields(self) -> List[str]:
        return ["group_no"]

    def generate(self, context: GenerationContext) -> Any:
        config = context.column_config
        start = config.get('start', 1)
        return start + context.group_index

    def configure(self, sample_values: List, profile: ColumnProfile) -> Dict[str, Any]:
        if not sample_values:
            return {'start': 1}

        # 尝试提取起始值
        first = sample_values[0]
        try:
            start = int(str(first).strip())
            return {'start': start}
        except (ValueError, TypeError):
            return {'start': 1}

    def priority(self) -> int:
        return 10

    def score_fit(self, profile: ColumnProfile) -> float:
        header = profile.header.lower()
        if any(kw in header for kw in ['组', '队伍', 'group', 'team']):
            return 90.0
        if profile.is_increasing and profile.unique_count <= 20:
            return 60.0
        return 20.0


class SeatNumberGenerator(DataGenerator):
    """座位号生成器"""

    @property
    def generator_id(self) -> str:
        return "seat_number"

    @property
    def compatible_fields(self) -> List[str]:
        return ["seat_number"]

    def generate(self, context: GenerationContext) -> Any:
        config = context.column_config
        start = config.get('start', 1)
        return start + context.seat_index

    def configure(self, sample_values: List, profile: ColumnProfile) -> Dict[str, Any]:
        if not sample_values:
            return {'start': 1}

        first = sample_values[0]
        try:
            start = int(str(first).strip())
            return {'start': start}
        except (ValueError, TypeError):
            return {'start': 1}

    def priority(self) -> int:
        return 10

    def score_fit(self, profile: ColumnProfile) -> float:
        header = profile.header.lower()
        if any(kw in header for kw in ['座位', '台位', 'seat', 'desk']):
            return 90.0
        if profile.is_cyclic:
            return 60.0
        return 20.0


class StationNumberGenerator(DataGenerator):
    """
    台位号生成器

    生成如 E01, A02 格式的台位号。
    """

    @property
    def generator_id(self) -> str:
        return "station_number"

    @property
    def compatible_fields(self) -> List[str]:
        return ["seat_number"]  # 也可以处理座位号

    def generate(self, context: GenerationContext) -> str:
        config = context.column_config
        prefix = config.get('prefix', 'A')
        start = config.get('start', 1)
        num_digits = config.get('num_digits', 2)

        num = start + context.group_index
        return f"{prefix}{num:0{num_digits}d}"

    def configure(self, sample_values: List, profile: ColumnProfile) -> Dict[str, Any]:
        if not sample_values:
            return {'prefix': 'A', 'start': 1, 'num_digits': 2}

        first = str(sample_values[0])
        import re
        match = re.match(r'^([A-Z])(\d+)$', first)
        if match:
            prefix = match.group(1)
            start = int(match.group(2))
            num_digits = len(match.group(2))
            return {'prefix': prefix, 'start': start, 'num_digits': num_digits}

        return {'prefix': 'A', 'start': 1, 'num_digits': 2}

    def priority(self) -> int:
        return 9

    def score_fit(self, profile: ColumnProfile) -> float:
        if profile.sample_values:
            import re
            match_count = sum(
                1 for v in profile.sample_values[:5]
                if re.match(r'^[A-Z]\d{2}$', str(v))
            )
            if match_count >= 3:
                return 90.0
        return 20.0
