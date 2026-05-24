"""
语义字段匹配器

基于同义词库将列头匹配到语义字段。
两阶段匹配：Phase 1 同义词匹配，Phase 2 数据验证消歧。
"""

from typing import List, Optional, Tuple
from ..generator.base import FieldMatch, ColumnProfile
from ..config.settings import get_settings, TemplateSettings


class SemanticFieldMatcher:
    """
    语义字段匹配器

    替代原有的 if/elif 硬编码匹配链。
    基于 YAML 配置的同义词库进行匹配。

    匹配算法：
    Phase 1 - 同义词匹配：
        - 精确匹配：得分 100
        - 包含匹配：得分 80 × 匹配长度比
        - 部分匹配：得分 60 × 匹配长度比

    Phase 2 - 数据验证消歧（仅当 Phase 1 有多个高分匹配时）：
        - 手机号：11位数字，1开头
        - 身份证：18位数字
        - 邮箱：含@符号
    """

    def __init__(self, settings: Optional[TemplateSettings] = None):
        self.settings = settings or get_settings()

    def match(
        self,
        header: str,
        sample_values: Optional[List] = None,
        profile: Optional[ColumnProfile] = None
    ) -> List[FieldMatch]:
        """
        匹配列头到语义字段

        Args:
            header: 列头文本
            sample_values: 样本值列表（用于 Phase 2 消歧）
            profile: 列统计分析结果（用于 Phase 2 消歧）

        Returns:
            匹配结果列表，按置信度降序排列
        """
        # Phase 1: 同义词匹配
        matches = self._synonym_match(header)

        if not matches:
            return []

        # 按置信度降序排列
        matches.sort(key=lambda m: m.confidence, reverse=True)

        # Phase 2: 数据验证消歧（当有多个高分匹配时）
        if len(matches) >= 2 and matches[0].confidence - matches[1].confidence < 20:
            if sample_values or profile:
                matches = self._validate_with_data(matches, sample_values, profile)

        return matches

    def match_best(
        self,
        header: str,
        sample_values: Optional[List] = None,
        profile: Optional[ColumnProfile] = None
    ) -> Optional[FieldMatch]:
        """
        匹配并返回最佳结果

        Returns:
            最佳匹配结果，若无匹配则返回 None
        """
        matches = self.match(header, sample_values, profile)
        return matches[0] if matches else None

    def _synonym_match(self, header: str) -> List[FieldMatch]:
        """
        Phase 1: 同义词匹配

        遍历所有语义字段的同义词组，计算匹配得分。
        """
        header_clean = header.lower().replace(' ', '').replace('*', '').strip()
        if not header_clean:
            return []

        matches = []
        fields = self.settings.synonym_dict.get('fields', {})

        for field_id, field_config in fields.items():
            synonym_groups = field_config.get('synonym_groups', [])
            display_name = field_config.get('display_name', field_id)
            priority = field_config.get('priority', 5)

            best_score = 0.0
            best_match_type = ''

            for group in synonym_groups:
                for synonym in group:
                    synonym_clean = synonym.lower().replace(' ', '').strip()

                    # 精确匹配
                    if header_clean == synonym_clean:
                        score = 100.0
                        if score > best_score:
                            best_score = score
                            best_match_type = 'exact'

                    # 包含匹配：同义词在列头中
                    elif synonym_clean in header_clean:
                        score = 80.0 * len(synonym_clean) / len(header_clean)
                        if score > best_score:
                            best_score = score
                            best_match_type = 'contains'

                    # 包含匹配：列头在同义词中
                    elif header_clean in synonym_clean:
                        score = 80.0 * len(header_clean) / len(synonym_clean)
                        if score > best_score:
                            best_score = score
                            best_match_type = 'partial'

            # 应用优先级权重
            best_score = best_score * (1 + priority / 100)

            if best_score >= 20:  # 最低阈值
                matches.append(FieldMatch(
                    field_id=field_id,
                    display_name=display_name,
                    confidence=min(best_score, 100),
                    match_type=best_match_type
                ))

        return matches

    def _validate_with_data(
        self,
        matches: List[FieldMatch],
        sample_values: Optional[List],
        profile: Optional[ColumnProfile]
    ) -> List[FieldMatch]:
        """
        Phase 2: 数据验证消歧

        当有多个高分匹配时，通过分析样本数据来消歧。
        """
        if not sample_values and not profile:
            return matches

        # 获取样本值
        values = sample_values or (profile.sample_values if profile else [])
        if not values:
            return matches

        str_values = [str(v).strip() for v in values if v is not None and str(v).strip()]
        if not str_values:
            return matches

        # 为每个匹配计算数据验证加分
        validated_matches = []
        for match in matches:
            validation_bonus = self._validate_field(match.field_id, str_values, profile)
            validated_matches.append(FieldMatch(
                field_id=match.field_id,
                display_name=match.display_name,
                confidence=min(match.confidence + validation_bonus, 100),
                match_type=match.match_type if validation_bonus == 0 else 'data_validated'
            ))

        # 重新排序
        validated_matches.sort(key=lambda m: m.confidence, reverse=True)
        return validated_matches

    def _validate_field(
        self,
        field_id: str,
        values: List[str],
        profile: Optional[ColumnProfile]
    ) -> float:
        """
        验证字段与数据的匹配度

        Returns:
            验证加分（0-30）
        """
        bonus = 0.0

        # 手机号验证
        if field_id == 'phone':
            phone_count = sum(1 for v in values if self._is_phone(v))
            if phone_count / len(values) > 0.8:
                bonus = 30.0

        # 身份证验证
        elif field_id == 'id_card':
            id_count = sum(1 for v in values if self._is_id_card(v))
            if id_count / len(values) > 0.8:
                bonus = 30.0

        # 邮箱验证
        elif field_id == 'email':
            email_count = sum(1 for v in values if '@' in v)
            if email_count / len(values) > 0.8:
                bonus = 30.0

        # 组号验证（应该是递增的数字）
        elif field_id == 'group_no':
            if profile and profile.is_increasing and profile.data_type == 'numeric':
                bonus = 20.0

        # 座位号验证（应该是循环的数字）
        elif field_id == 'seat_number':
            if profile and profile.is_cyclic:
                bonus = 20.0

        # 性别验证（只有男/女两个值）
        elif field_id == 'gender':
            unique = set(values)
            if unique.issubset({'男', '女', 'M', 'F', 'male', 'female'}):
                bonus = 30.0

        # 学号/考试号验证（带前缀的序列）
        elif field_id in ('student_no', 'exam_no'):
            if profile and profile.prefix_pattern:
                bonus = 25.0

        return bonus

    def _is_phone(self, value: str) -> bool:
        """验证手机号格式"""
        cleaned = re.sub(r'\D', '', value)
        return len(cleaned) == 11 and cleaned[0] == '1'

    def _is_id_card(self, value: str) -> bool:
        """验证身份证号格式"""
        cleaned = value.strip()
        return len(cleaned) == 18 and cleaned[:17].isdigit()

    def _is_email(self, value: str) -> bool:
        """验证邮箱格式"""
        return '@' in value and '.' in value.split('@')[1]


# 需要导入 re
import re
