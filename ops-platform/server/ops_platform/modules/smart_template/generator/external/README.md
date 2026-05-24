# 外部插件目录

将自定义生成器 .py 文件放在此目录，系统会自动加载。

## 插件开发示例

```python
from smart_template.generator.base import DataGenerator, GenerationContext, ColumnProfile
from typing import Any, Dict, List

class MyCustomGenerator(DataGenerator):
    """自定义数据生成器示例"""

    @property
    def generator_id(self) -> str:
        return "my_custom"

    @property
    def compatible_fields(self) -> List[str]:
        return ["my_field", "custom_field"]

    def generate(self, context: GenerationContext) -> Any:
        # 生成数据逻辑
        return "custom_value"

    def configure(self, sample_values: List, profile: ColumnProfile) -> Dict[str, Any]:
        # 从样本数据配置生成器
        return {}

    def priority(self) -> int:
        return 10  # 优先级
```

## 注册新字段

如果插件引入了新的字段类型，需要在 config/synonym_dict.yaml 中添加同义词定义。
