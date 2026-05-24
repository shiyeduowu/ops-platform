# -*- coding: utf-8 -*-
"""
关系推断器

推断列间关系：组号/座位号耦合、层级关系、组内循环等。
"""

from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
from .column_profiler import ColumnProfiler
from ..generator.base import ColumnProfile


class RelationshipType(Enum):
    """关系类型"""
    GROUP_SEAT = "group_seat"           # 组号 + 座位号耦合
    PARENT_CHILD = "parent_child"       # 层级关系（学校→学院→专业）
    INTRA_GROUP_CYCLE = "intra_group_cycle"  # 组内循环（岗位轮换）
    SEQUENCE = "sequence"               # 序列关系（学号递增）


@dataclass
class ColumnRelationship:
    """列关系描述"""
    rel_type: RelationshipType
    parent_col: int         # 父列索引
    child_col: int          # 子列索引
    confidence: float       # 置信度 0.0-1.0
    description: str        # 描述


class RelationshipInferencer:
    """
    关系推断器

    分析多列数据，推断列间关系。
    """

    def __init__(self):
        self.profiler = ColumnProfiler()

    def infer(
        self,
        sheet,
        header_row: int,
        column_profiles: List[ColumnProfile]
    ) -> List[ColumnRelationship]:
        """
        推断列间关系

        Args:
            sheet: openpyxl worksheet
            header_row: 表头行号
            column_profiles: 列统计信息列表

        Returns:
            推断出的关系列表
        """
        relationships = []

        # 检测组号 + 座位号耦合
        group_seat = self._detect_group_seat(sheet, header_row, column_profiles)
        relationships.extend(group_seat)

        # 检测层级关系
        hierarchy = self._detect_hierarchy(column_profiles)
        relationships.extend(hierarchy)

        # 检测组内循环
        intra_cycle = self._detect_intra_group_cycle(sheet, header_row, column_profiles)
        relationships.extend(intra_cycle)

        return relationships

    def _detect_group_seat(
        self,
        sheet,
        header_row: int,
        profiles: List[ColumnProfile]
    ) -> List[ColumnRelationship]:
        """
        检测组号 + 座位号耦合

        特征：
        - 组号列：递增，唯一值较少
        - 座位号列：循环，循环长度 = 每组人数
        """
        relationships = []

        # 找组号列
        group_cols = []
        for p in profiles:
            if any(kw in p.header for kw in ['组', 'group', 'team']):
                group_cols.append(p)
            elif p.is_increasing and p.unique_count <= 20:
                group_cols.append(p)

        # 找座位号列
        seat_cols = []
        for p in profiles:
            if any(kw in p.header for kw in ['座位', '台位', 'seat', 'desk']):
                seat_cols.append(p)
            elif p.is_cyclic:
                seat_cols.append(p)

        # 配对
        for gc in group_cols:
            for sc in seat_cols:
                if gc.index != sc.index:
                    # 验证：座位号在每组内循环
                    if self._verify_group_seat_coupling(sheet, header_row, gc.index, sc.index):
                        relationships.append(ColumnRelationship(
                            rel_type=RelationshipType.GROUP_SEAT,
                            parent_col=gc.index,
                            child_col=sc.index,
                            confidence=0.9,
                            description=f"{gc.header} + {sc.header} 耦合"
                        ))

        return relationships

    def _verify_group_seat_coupling(
        self,
        sheet,
        header_row: int,
        group_col: int,
        seat_col: int
    ) -> bool:
        """验证组号+座位号耦合关系"""
        groups = []
        seats = []

        for row in range(header_row + 1, min(header_row + 20, sheet.max_row + 1)):
            g_val = sheet.cell(row=row, column=group_col + 1).value
            s_val = sheet.cell(row=row, column=seat_col + 1).value
            if g_val is not None and s_val is not None:
                try:
                    groups.append(int(str(g_val).strip()))
                    seats.append(int(str(s_val).strip()))
                except (ValueError, TypeError):
                    pass

        if len(groups) < 4:
            return False

        # 检查座位号是否在每组内循环
        cycle_len = 0
        for i in range(1, len(seats)):
            if seats[i] < seats[i - 1]:
                cycle_len = i
                break

        if cycle_len == 0:
            return False

        # 验证每组内座位号都是 1..cycle_len
        for i in range(0, len(seats), cycle_len):
            group_seats = seats[i:i + cycle_len]
            expected = list(range(1, len(group_seats) + 1))
            if group_seats != expected:
                return False

        return True

    def _detect_hierarchy(
        self,
        profiles: List[ColumnProfile]
    ) -> List[ColumnRelationship]:
        """
        检测层级关系

        如：学校 → 学院 → 专业 → 班级
        """
        relationships = []

        # 定义层级顺序
        hierarchy_keywords = [
            ['学校', 'school'],
            ['学院', 'college'],
            ['专业', 'major'],
            ['班级', 'class'],
        ]

        # 按层级排序列
        hierarchy_cols = []
        for level_keywords in hierarchy_keywords:
            for p in profiles:
                if any(kw in p.header for kw in level_keywords):
                    hierarchy_cols.append(p)
                    break

        # 创建层级关系
        for i in range(len(hierarchy_cols) - 1):
            parent = hierarchy_cols[i]
            child = hierarchy_cols[i + 1]
            relationships.append(ColumnRelationship(
                rel_type=RelationshipType.PARENT_CHILD,
                parent_col=parent.index,
                child_col=child.index,
                confidence=0.8,
                description=f"{parent.header} → {child.header}"
            ))

        return relationships

    def _detect_intra_group_cycle(
        self,
        sheet,
        header_row: int,
        profiles: List[ColumnProfile]
    ) -> List[ColumnRelationship]:
        """
        检测组内循环关系

        如：岗位在每组内轮换
        """
        relationships = []

        # 找循环列
        cyclic_cols = [p for p in profiles if p.is_cyclic]

        # 找组号列
        group_col = None
        for p in profiles:
            if any(kw in p.header for kw in ['组', 'group', 'team']):
                group_col = p
                break

        if not group_col:
            return relationships

        # 验证循环列是否在组内循环
        for cp in cyclic_cols:
            if cp.index == group_col.index:
                continue

            # 检查是否在每组内循环
            if self._verify_intra_group_cycle(sheet, header_row, group_col.index, cp.index):
                relationships.append(ColumnRelationship(
                    rel_type=RelationshipType.INTRA_GROUP_CYCLE,
                    parent_col=group_col.index,
                    child_col=cp.index,
                    confidence=0.85,
                    description=f"{cp.header} 在 {group_col.header} 内循环"
                ))

        return relationships

    def _verify_intra_group_cycle(
        self,
        sheet,
        header_row: int,
        group_col: int,
        cycle_col: int
    ) -> bool:
        """验证组内循环关系"""
        groups = []
        values = []

        for row in range(header_row + 1, min(header_row + 20, sheet.max_row + 1)):
            g_val = sheet.cell(row=row, column=group_col + 1).value
            c_val = sheet.cell(row=row, column=cycle_col + 1).value
            if g_val is not None and c_val is not None:
                groups.append(str(g_val).strip())
                values.append(str(c_val).strip())

        if len(groups) < 4:
            return False

        # 找每组大小
        group_size = 0
        for i in range(1, len(groups)):
            if groups[i] != groups[0]:
                group_size = i
                break

        if group_size == 0:
            return False

        # 验证每组内值是否相同
        first_group_values = values[:group_size]
        for i in range(group_size, len(values), group_size):
            group_values = values[i:i + group_size]
            if group_values != first_group_values:
                return False

        return True
