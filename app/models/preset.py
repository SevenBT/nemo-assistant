"""
预设角色模型

用于管理 System Prompt 模板。
"""
from dataclasses import dataclass, field


@dataclass
class Preset:
    """预设角色模型"""
    id: str
    name: str
    icon: str
    system_prompt: str
    params: dict = field(default_factory=dict)
    is_builtin: bool = False

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "id": self.id,
            "name": self.name,
            "icon": self.icon,
            "system_prompt": self.system_prompt,
            "params": self.params,
            "is_builtin": self.is_builtin,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Preset":
        """从字典创建"""
        return cls(
            id=d["id"],
            name=d["name"],
            icon=d.get("icon", "🤖"),
            system_prompt=d["system_prompt"],
            params=d.get("params", {}),
            is_builtin=d.get("is_builtin", False),
        )
