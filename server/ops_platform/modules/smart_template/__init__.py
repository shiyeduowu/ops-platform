# -*- coding: utf-8 -*-
"""
智能模板生成系统

核心模块：
- SmartTemplateEngine: 统一入口
- HeaderDetector: 多策略表头检测
- SemanticFieldMatcher: 语义字段匹配
- GeneratorRegistry: 数据生成器注册表
"""

from .engine import SmartTemplateEngine

__all__ = ['SmartTemplateEngine']
