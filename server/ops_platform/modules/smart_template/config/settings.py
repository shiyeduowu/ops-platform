"""
配置管理器

加载和管理 YAML 配置文件。
"""

import yaml
from pathlib import Path
from typing import Dict, List, Optional, Any


class TemplateSettings:
    """
    模板引擎配置管理器

    提供：
    - synonym_dict: 同义词映射
    - field_definitions: 字段行为定义
    - plugin_dirs: 插件目录
    - learned_patterns_path: 学习模式存储路径
    """

    _instance = None

    def __new__(cls, *args, **kwargs):
        """单例模式"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, config_dir: Optional[str] = None):
        if self._initialized:
            return

        if config_dir:
            self.config_dir = Path(config_dir)
        else:
            self.config_dir = Path(__file__).parent

        self.synonym_dict = self._load_yaml('synonym_dict.yaml')
        self.field_definitions = self._load_yaml('field_definitions.yaml')
        self._initialized = True

    def _load_yaml(self, filename: str) -> Dict[str, Any]:
        """加载 YAML 配置文件"""
        filepath = self.config_dir / filename
        if not filepath.exists():
            return {}
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            print(f"Warning: Failed to load {filename}: {e}")
            return {}

    def get_field_ids(self) -> List[str]:
        """获取所有已定义的字段ID"""
        fields = self.synonym_dict.get('fields', {})
        return list(fields.keys())

    def get_synonym_groups(self, field_id: str) -> List[List[str]]:
        """获取字段的同义词组"""
        fields = self.synonym_dict.get('fields', {})
        field_config = fields.get(field_id, {})
        return field_config.get('synonym_groups', [])

    def get_field_config(self, field_id: str) -> Dict[str, Any]:
        """获取字段完整配置"""
        fields = self.synonym_dict.get('fields', {})
        return fields.get(field_id, {})

    def get_generator_id(self, field_id: str) -> str:
        """获取字段对应的生成器ID"""
        field_config = self.get_field_config(field_id)
        if field_config.get('generator'):
            return field_config['generator']
        # 从 field_definitions 获取
        definitions = self.field_definitions.get('fields', {})
        def_config = definitions.get(field_id, {})
        return def_config.get('generator', 'fixed')

    def get_related_fields(self, field_id: str) -> List[str]:
        """获取关联字段"""
        field_config = self.get_field_config(field_id)
        return field_config.get('related_to', [])

    def get_priority(self, field_id: str) -> int:
        """获取字段匹配优先级"""
        field_config = self.get_field_config(field_id)
        return field_config.get('priority', 5)

    def add_custom_synonym(self, field_id: str, synonym: str, group_index: int = 0):
        """运行时添加自定义同义词"""
        if 'fields' not in self.synonym_dict:
            self.synonym_dict['fields'] = {}
        if field_id not in self.synonym_dict['fields']:
            self.synonym_dict['fields'][field_id] = {
                'display_name': field_id,
                'synonym_groups': [[]],
                'priority': 5
            }

        groups = self.synonym_dict['fields'][field_id].get('synonym_groups', [])
        while len(groups) <= group_index:
            groups.append([])
        if synonym not in groups[group_index]:
            groups[group_index].append(synonym)

    def reload(self):
        """重新加载配置"""
        self.synonym_dict = self._load_yaml('synonym_dict.yaml')
        self.field_definitions = self._load_yaml('field_definitions.yaml')


# 全局设置实例
_settings: Optional[TemplateSettings] = None


def get_settings(config_dir: Optional[str] = None) -> TemplateSettings:
    """获取全局设置实例"""
    global _settings
    if _settings is None:
        _settings = TemplateSettings(config_dir)
    return _settings


def reload_settings():
    """重新加载设置"""
    global _settings
    if _settings:
        _settings.reload()
