# -*- coding: utf-8 -*-
"""
模式存储

持久化存储学习到的模板模式。
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict


@dataclass
class LearnedPattern:
    """学习到的模板模式"""
    pattern_id: str                         # 模式ID
    template_signature: str                 # 模板签名（列名组合的hash）
    header_row: int                         # 表头行号
    column_mappings: Dict[str, str]         # {列索引: 语义字段ID}
    column_configs: Dict[str, Dict]         # {列索引: 生成器配置}
    usage_count: int = 0                    # 使用次数
    success_count: int = 0                  # 成功次数
    last_used: str = ""                     # 最后使用时间
    metadata: Dict[str, Any] = field(default_factory=dict)


class PatternStore:
    """
    模式存储

    功能：
    1. 保存学习到的模式
    2. 加载已保存的模式
    3. 根据签名查找匹配的模式
    """

    def __init__(self, store_path: Optional[str] = None):
        if store_path is None:
            store_path = str(
                Path(__file__).parent.parent.parent.parent.parent /
                'data' / 'learned_patterns.json'
            )
        self._store_path = Path(store_path)
        self._patterns: Dict[str, LearnedPattern] = {}
        self._load()

    def _load(self):
        """从文件加载模式"""
        if not self._store_path.exists():
            return

        try:
            with open(self._store_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for pattern_id, pattern_data in data.items():
                    self._patterns[pattern_id] = LearnedPattern(
                        pattern_id=pattern_id,
                        **pattern_data
                    )
        except (json.JSONDecodeError, Exception) as e:
            print(f"Warning: Failed to load patterns: {e}")

    def save(self):
        """保存模式到文件"""
        self._store_path.parent.mkdir(parents=True, exist_ok=True)

        data = {}
        for pattern_id, pattern in self._patterns.items():
            data[pattern_id] = {
                'template_signature': pattern.template_signature,
                'header_row': pattern.header_row,
                'column_mappings': pattern.column_mappings,
                'column_configs': pattern.column_configs,
                'usage_count': pattern.usage_count,
                'success_count': pattern.success_count,
                'last_used': pattern.last_used,
                'metadata': pattern.metadata
            }

        with open(self._store_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def add_pattern(self, pattern: LearnedPattern):
        """添加或更新模式"""
        self._patterns[pattern.pattern_id] = pattern
        self.save()

    def get_pattern(self, pattern_id: str) -> Optional[LearnedPattern]:
        """根据ID获取模式"""
        return self._patterns.get(pattern_id)

    def find_by_signature(self, signature: str) -> Optional[LearnedPattern]:
        """根据签名查找模式"""
        for pattern in self._patterns.values():
            if pattern.template_signature == signature:
                return pattern
        return None

    def get_all_patterns(self) -> List[LearnedPattern]:
        """获取所有模式"""
        return list(self._patterns.values())

    def record_usage(self, pattern_id: str, success: bool = True):
        """记录模式使用情况"""
        pattern = self._patterns.get(pattern_id)
        if pattern:
            pattern.usage_count += 1
            if success:
                pattern.success_count += 1
            self.save()

    def compute_signature(self, headers: List[str]) -> str:
        """
        计算模板签名

        基于列名组合生成唯一签名。
        """
        import hashlib
        normalized = [h.strip().lower() for h in headers]
        content = '|'.join(normalized)
        return hashlib.md5(content.encode('utf-8')).hexdigest()[:16]
