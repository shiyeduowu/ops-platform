"""
数据生成器注册表

管理所有数据生成器，根据语义字段选择最佳生成器。
支持插件化扩展。
"""

import importlib
import sys
from pathlib import Path
from typing import Dict, List, Optional, Type
from .base import DataGenerator, ColumnProfile


class GeneratorRegistry:
    """
    数据生成器注册表

    功能：
    1. 注册/注销生成器
    2. 根据字段ID查找兼容的生成器
    3. 根据列特征选择最佳生成器
    4. 动态加载外部插件
    """

    def __init__(self):
        self._generators: Dict[str, DataGenerator] = {}
        self._field_index: Dict[str, List[str]] = {}  # field_id -> [generator_ids]
        self._load_builtins()

    def register(self, generator: DataGenerator):
        """
        注册生成器

        Args:
            generator: 数据生成器实例
        """
        gen_id = generator.generator_id
        self._generators[gen_id] = generator

        # 建立字段索引
        for field_id in generator.compatible_fields:
            if field_id not in self._field_index:
                self._field_index[field_id] = []
            if gen_id not in self._field_index[field_id]:
                self._field_index[field_id].append(gen_id)

    def unregister(self, generator_id: str):
        """注销生成器"""
        if generator_id in self._generators:
            gen = self._generators[generator_id]
            for field_id in gen.compatible_fields:
                if field_id in self._field_index:
                    self._field_index[field_id] = [
                        gid for gid in self._field_index[field_id]
                        if gid != generator_id
                    ]
            del self._generators[generator_id]

    def get_generator(self, generator_id: str) -> Optional[DataGenerator]:
        """根据ID获取生成器"""
        return self._generators.get(generator_id)

    def get_generators_for_field(self, field_id: str) -> List[DataGenerator]:
        """获取兼容指定字段的所有生成器"""
        gen_ids = self._field_index.get(field_id, [])
        return [self._generators[gid] for gid in gen_ids if gid in self._generators]

    def get_best_generator(
        self,
        field_id: str,
        profile: Optional[ColumnProfile] = None
    ) -> Optional[DataGenerator]:
        """
        选择最佳生成器

        Args:
            field_id: 语义字段ID
            profile: 列统计分析结果

        Returns:
            最佳生成器，若无兼容生成器则返回 None
        """
        generators = self.get_generators_for_field(field_id)
        if not generators:
            # 尝试使用 fixed 生成器作为兜底
            return self._generators.get('fixed')

        if len(generators) == 1:
            return generators[0]

        # 按优先级和匹配度排序
        scored = []
        for gen in generators:
            score = gen.priority() * 100
            if profile:
                score += gen.score_fit(profile)
            scored.append((score, gen))

        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1]

    def get_all_generators(self) -> List[DataGenerator]:
        """获取所有已注册的生成器"""
        return list(self._generators.values())

    def _load_builtins(self):
        """加载内置生成器"""
        try:
            # 导入内置生成器模块
            from .builtin import text_generators
            from .builtin import number_generators
            from .builtin import phone_generators
            from .builtin import identity_generators
            from .builtin import cycle_generators
            from .builtin import composite_generators

            # 注册所有生成器
            for module in [
                text_generators,
                number_generators,
                phone_generators,
                identity_generators,
                cycle_generators,
                composite_generators
            ]:
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if (isinstance(attr, type) and
                        issubclass(attr, DataGenerator) and
                        attr is not DataGenerator):
                        try:
                            self.register(attr())
                        except Exception as e:
                            print(f"Warning: Failed to register generator {attr_name}: {e}")
        except ImportError as e:
            print(f"Warning: Failed to load builtin generators: {e}")

    def load_plugins(self, plugin_dir: Optional[str] = None):
        """
        加载外部插件

        Args:
            plugin_dir: 插件目录路径，默认为 generator/external/
        """
        if plugin_dir is None:
            plugin_dir = str(Path(__file__).parent / 'external')

        plugin_path = Path(plugin_dir)
        if not plugin_path.exists():
            return

        for py_file in plugin_path.glob('*.py'):
            if py_file.name.startswith('_'):
                continue

            try:
                # 动态导入模块
                module_name = py_file.stem
                spec = importlib.util.spec_from_file_location(
                    f"smart_template_plugin_{module_name}",
                    str(py_file)
                )
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[module_name] = module
                    spec.loader.exec_module(module)

                    # 查找并注册 DataGenerator 子类
                    for attr_name in dir(module):
                        attr = getattr(module, attr_name)
                        if (isinstance(attr, type) and
                            issubclass(attr, DataGenerator) and
                            attr is not DataGenerator):
                            try:
                                self.register(attr())
                                print(f"Loaded plugin generator: {attr_name}")
                            except Exception as e:
                                print(f"Warning: Failed to load plugin {attr_name}: {e}")
            except Exception as e:
                print(f"Warning: Failed to load plugin file {py_file.name}: {e}")
