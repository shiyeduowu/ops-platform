"""
循环数据生成器

生成循环值数据，如岗位轮换、性别交替等。
"""

from typing import Any, Dict, List
from collections import Counter
from ..base import DataGenerator, GenerationContext, ColumnProfile


# 默认岗位列表
DEFAULT_POSITIONS = [
    ['营销总监', '财务总监', '生产总监', '项目总监', '采购总监', '人力资源总监', '行政总监', '运营总监'],
    ['绩效内控', '投融资管理', '营运分析', '预算管理', '税务管理', '资金管理', '财务分析', '成本管理']
]

# 默认学院
DEFAULT_COLLEGES = ['商学院', '信息学院', '会计学院', '金融学院', '管理学院']

# 默认专业
DEFAULT_MAJORS = ['大数据与会计', '电子商务', '市场营销', '金融科技', '国际贸易']

# 默认班级
DEFAULT_CLASSES = ['2024级1班', '2024级2班', '2024级3班', '2024级4班']

# 默认学历
DEFAULT_EDUCATIONS = ['本科', '专科']

# 默认性别
DEFAULT_GENDERS = ['男', '女']

# 默认入学年份
DEFAULT_YEARS = ['2024', '2023', '2022']


class CycleGenerator(DataGenerator):
    """循环值生成器"""

    @property
    def generator_id(self) -> str:
        return "cycle"

    @property
    def compatible_fields(self) -> List[str]:
        return [
            "position", "gender", "college", "major", "class_name",
            "education", "enrollment_year", "is_coop"
        ]

    def generate(self, context: GenerationContext) -> Any:
        config = context.column_config
        values = config.get('values', [''])

        # 根据配置选择循环方式
        cycle_within = config.get('cycle_within', 'global')

        if cycle_within == 'group':
            # 组内循环：每组内从头开始
            index = context.seat_index % len(values)
        elif cycle_within == 'row':
            # 行循环：逐行递增
            index = context.row_index % len(values)
        else:
            # 全局循环
            index = context.row_index % len(values)

        return values[index]

    def configure(self, sample_values: List, profile: ColumnProfile) -> Dict[str, Any]:
        if not sample_values:
            return {'values': self._get_default_values(profile), 'cycle_within': 'global'}

        # 从样本数据提取循环值
        str_values = [str(v).strip() for v in sample_values if v is not None]
        unique_values = list(dict.fromkeys(str_values))  # 保持顺序去重

        if unique_values:
            # 判断循环方式
            cycle_within = self._detect_cycle_within(str_values, unique_values)
            return {
                'values': unique_values,
                'cycle_within': cycle_within
            }

        return {'values': self._get_default_values(profile), 'cycle_within': 'global'}

    def _get_default_values(self, profile: ColumnProfile) -> List[str]:
        """根据字段名获取默认值"""
        header = profile.header.lower()

        if '岗位' in header or 'position' in header:
            return DEFAULT_POSITIONS[0]
        elif '性别' in header or 'gender' in header:
            return DEFAULT_GENDERS
        elif '学院' in header or 'college' in header:
            return DEFAULT_COLLEGES
        elif '专业' in header or 'major' in header:
            return DEFAULT_MAJORS
        elif '班级' in header or 'class' in header:
            return DEFAULT_CLASSES
        elif '学历' in header or 'education' in header:
            return DEFAULT_EDUCATIONS
        elif '年份' in header or 'year' in header:
            return DEFAULT_YEARS
        elif '是否' in header:
            return ['是', '否']

        return ['']

    def _detect_cycle_within(self, values: List[str], unique_values: List[str]) -> str:
        """检测循环方式"""
        if len(values) < 4:
            return 'global'

        # 检查是否组内循环（值在每组内重复）
        cycle_len = len(unique_values)
        if cycle_len >= 2:
            is_group_cycle = True
            for i in range(cycle_len, min(len(values), cycle_len * 3)):
                if values[i] != values[i % cycle_len]:
                    is_group_cycle = False
                    break
            if is_group_cycle:
                return 'group'

        return 'global'

    def priority(self) -> int:
        return 5

    def score_fit(self, profile: ColumnProfile) -> float:
        if profile.is_cyclic:
            return 80.0
        if profile.unique_count <= 10 and profile.data_type == 'text':
            return 70.0
        return 30.0


class PositionCycleGenerator(CycleGenerator):
    """岗位循环生成器（特殊处理）"""

    @property
    def generator_id(self) -> str:
        return "position_cycle"

    @property
    def compatible_fields(self) -> List[str]:
        return ["position"]

    def priority(self) -> int:
        return 8  # 比通用 cycle 更高优先级

    def configure(self, sample_values: List, profile: ColumnProfile) -> Dict[str, Any]:
        config = super().configure(sample_values, profile)

        # 岗位通常组内循环
        if not sample_values:
            config['values'] = DEFAULT_POSITIONS[0]
        config['cycle_within'] = 'group'

        return config
