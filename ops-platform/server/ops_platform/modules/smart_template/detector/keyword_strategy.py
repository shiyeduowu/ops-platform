# -*- coding: utf-8 -*-
"""
关键词策略

基于同义词字典的表头检测策略。
使用 TF-IDF 思想：稀有关键词权重更高。
"""

import re
from typing import List, Dict, Set, Tuple
from .base import DetectionStrategy, HeaderCandidate
from ..config.settings import TemplateSettings


class KeywordStrategy(DetectionStrategy):
    """
    关键词策略

    扫描每行的单元格值，与同义词字典匹配。
    匹配到的关键词越多、越稀有，得分越高。
    """

    def __init__(self, settings: TemplateSettings = None):
        self._settings = settings or TemplateSettings()
        self._keyword_index = self._build_keyword_index()

    @property
    def name(self) -> str:
        return "keyword"

    @property
    def weight(self) -> float:
        return 0.35

    def detect(self, sheet, max_scan_rows: int = 15) -> List[HeaderCandidate]:
        candidates = []

        for row_idx in range(1, min(max_scan_rows + 1, sheet.max_row + 1)):
            values = self._get_row_values(sheet, row_idx)
            if self._is_empty_row(values):
                continue

            score, reasons = self._score_row(values)
            if score > 0:
                candidates.append(HeaderCandidate(
                    row_index=row_idx,
                    score=min(score, 1.0),
                    strategy_name=self.name,
                    reasons=reasons
                ))

        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates

    def _build_keyword_index(self) -> Dict[str, Tuple[str, float]]:
        """
        构建关键词索引

        Returns:
            {keyword: (field_id, weight)} 映射
        """
        index = {}
        for field_id in self._settings.get_field_ids():
            synonym_groups = self._settings.get_synonym_groups(field_id)
            # 计算关键词的 IDF 权重（越稀有权重越高）
            all_keywords = set()
            for group in synonym_groups:
                for kw in group:
                    all_keywords.add(kw.lower())

            # 基础权重 + 长度奖励（长关键词更具体）
            for kw in all_keywords:
                base_weight = 1.0
                if len(kw) >= 4:
                    base_weight = 1.5  # 长关键词权重更高
                if kw not in index or base_weight > index[kw][1]:
                    index[kw] = (field_id, base_weight)

        return index

    def _score_row(self, values: List[str]) -> Tuple[float, List[str]]:
        """
        计算一行的关键词匹配得分

        Returns:
            (score, reasons) 元组
        """
        matched_fields = set()
        total_weight = 0.0
        reasons = []

        for val in values:
            if not val:
                continue

            val_lower = val.lower().strip()

            # 精确匹配
            if val_lower in self._keyword_index:
                field_id, weight = self._keyword_index[val_lower]
                matched_fields.add(field_id)
                total_weight += weight
                reasons.append(f"'{val}' 精确匹配 {field_id}")
                continue

            # 包含匹配（检查值是否包含关键词）
            for kw, (field_id, weight) in self._keyword_index.items():
                if len(kw) >= 2 and kw in val_lower:
                    matched_fields.add(field_id)
                    total_weight += weight * 0.8  # 包含匹配权重略低
                    reasons.append(f"'{val}' 包含关键词 '{kw}' -> {field_id}")
                    break

        if not matched_fields:
            return 0.0, []

        # 计算得分：匹配字段数 / 行总列数
        non_empty = sum(1 for v in values if v)
        if non_empty == 0:
            return 0.0, []

        # 基础分 = 匹配字段数 / 非空列数
        base_score = len(matched_fields) / non_empty

        # 密度奖励：匹配密度越高，得分越高
        density = len(matched_fields) / len(values) if values else 0

        # 最终得分
        score = base_score * 0.7 + density * 0.3

        return score, reasons
