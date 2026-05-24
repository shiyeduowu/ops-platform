# -*- coding: utf-8 -*-
"""
模式匹配器

匹配已学习的模式到新模板。
"""

from typing import List, Dict, Optional, Tuple
from .pattern_store import PatternStore, LearnedPattern


class PatternMatcher:
    """
    模式匹配器

    功能：
    1. 精确签名匹配
    2. 相似度匹配（列名重叠度）
    3. 反馈记录
    """

    def __init__(self, store: PatternStore = None):
        self._store = store or PatternStore()

    def match(
        self,
        headers: List[str],
        exact_only: bool = False
    ) -> Optional[LearnedPattern]:
        """
        匹配模板

        Args:
            headers: 列名列表
            exact_only: 是否只进行精确匹配

        Returns:
            匹配到的模式，若无则返回 None
        """
        # 1. 精确签名匹配
        signature = self._store.compute_signature(headers)
        pattern = self._store.find_by_signature(signature)
        if pattern:
            return pattern

        if exact_only:
            return None

        # 2. 相似度匹配
        best_match = None
        best_similarity = 0.0

        for existing in self._store.get_all_patterns():
            similarity = self._compute_similarity(headers, existing)
            if similarity > best_similarity and similarity >= 0.7:
                best_similarity = similarity
                best_match = existing

        return best_match

    def _compute_similarity(
        self,
        headers: List[str],
        pattern: LearnedPattern
    ) -> float:
        """
        计算模板相似度

        基于列名重叠度。
        """
        # 从 pattern.column_mappings 提取列名
        pattern_headers = set()
        for col_idx, field_id in pattern.column_mappings.items():
            # 使用 field_id 作为列名
            pattern_headers.add(field_id.lower())

        # 归一化当前列名
        current_headers = set(h.strip().lower() for h in headers if h)

        if not pattern_headers or not current_headers:
            return 0.0

        # 计算 Jaccard 相似度
        intersection = pattern_headers & current_headers
        union = pattern_headers | current_headers

        return len(intersection) / len(union) if union else 0.0

    def record_feedback(
        self,
        pattern_id: str,
        success: bool,
        corrections: Optional[Dict[str, str]] = None
    ):
        """
        记录用户反馈

        Args:
            pattern_id: 模式ID
            success: 是否成功
            corrections: 用户修正 {列索引: 正确的字段ID}
        """
        self._store.record_usage(pattern_id, success)

        if corrections:
            pattern = self._store.get_pattern(pattern_id)
            if pattern:
                # 更新列映射
                for col_idx, field_id in corrections.items():
                    pattern.column_mappings[col_idx] = field_id
                self._store.save()
