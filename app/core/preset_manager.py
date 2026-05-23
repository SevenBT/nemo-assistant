"""
预设角色管理器

负责加载/保存预设角色配置，提供 CRUD 操作。
"""
import json
from pathlib import Path
from typing import Optional

from app.core.config import CONFIG_DIR
from app.models.preset import Preset

PRESETS_FILE = CONFIG_DIR / "presets.json"

BUILTIN_PRESETS = [
    {
        "id": "default",
        "name": "默认助手",
        "icon": "🤖",
        "system_prompt": "你是一个智能AI助手。你可以调用工具来帮助用户完成任务。\n\n请用中文回复。",
        "params": {},
        "is_builtin": True,
    },
    {
        "id": "translator",
        "name": "翻译官",
        "icon": "🌐",
        "system_prompt": "你是一个专业翻译。请检测用户输入的语言，如果是中文则翻译为英文，如果是英文则翻译为中文。保持原文的语气和风格。",
        "params": {"temperature": 0.3},
        "is_builtin": True,
    },
    {
        "id": "coder",
        "name": "代码助手",
        "icon": "💻",
        "system_prompt": "你是一个专业的编程助手。擅长代码生成、调试、优化和技术问题解答。回复时优先提供可运行的代码示例。",
        "params": {},
        "is_builtin": True,
    },
    {
        "id": "writer",
        "name": "写作助手",
        "icon": "✏️",
        "system_prompt": "你是一个专业的写作助手。擅长各类文体的创作、修改和润色。请根据用户需求提供高质量的文案。",
        "params": {},
        "is_builtin": True,
    },
    {
        "id": "summarizer",
        "name": "摘要大师",
        "icon": "📋",
        "system_prompt": "你是一个专业的内容总结助手。擅长提取关键信息，用简洁的语言概括长文内容。请用条目或段落形式输出摘要。",
        "params": {},
        "is_builtin": True,
    },
]


class PresetManager:
    """预设角色管理器"""

    def __init__(self):
        self._presets: dict[str, Preset] = {}
        self._builtin_originals: dict[str, Preset] = {}  # 保存原始内置预设
        self._load()

    def _load(self):
        """加载预设角色，首次运行时创建内置预设"""
        if not PRESETS_FILE.exists():
            self._create_builtin()
            self._save_builtin_originals()
            return

        try:
            with open(PRESETS_FILE, encoding="utf-8") as f:
                data = json.load(f)
            for item in data:
                preset = Preset.from_dict(item)
                self._presets[preset.id] = preset
        except Exception as e:
            print(f"[PresetManager] Failed to load presets: {e}")
            self._create_builtin()

        # 保存原始内置预设的副本
        self._save_builtin_originals()

    def _save_builtin_originals(self):
        """保存原始内置预设的深拷贝"""
        for preset in self._presets.values():
            if preset.is_builtin:
                self._builtin_originals[preset.id] = Preset(
                    id=preset.id,
                    name=preset.name,
                    icon=preset.icon,
                    system_prompt=preset.system_prompt,
                    params=dict(preset.params),
                    is_builtin=preset.is_builtin,
                )

    def _create_builtin(self):
        """创建内置预设角色"""
        for item in BUILTIN_PRESETS:
            preset = Preset.from_dict(item)
            self._presets[preset.id] = preset
        self._save()

    def _save(self):
        """保存预设角色到文件"""
        import time
        start = time.time()
        print(f"[PresetManager] Starting save to {PRESETS_FILE}")

        try:
            # 确保目录存在
            PRESETS_FILE.parent.mkdir(parents=True, exist_ok=True)
            print(f"[PresetManager] Directory ensured")

            # 序列化数据
            data = [p.to_dict() for p in self._presets.values()]
            print(f"[PresetManager] Serialized {len(data)} presets")

            # 原子写入：先写临时文件，再重命名
            temp_file = PRESETS_FILE.with_suffix('.tmp')
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"[PresetManager] Wrote temp file: {temp_file}")

            # 原子替换
            temp_file.replace(PRESETS_FILE)

            elapsed = time.time() - start
            print(f"[PresetManager] Save completed in {elapsed: .3f}s")

        except PermissionError as e:
            print(f"[PresetManager] Permission error: {e}")
            raise IOError(f"无法保存配置文件：权限不足\n{PRESETS_FILE}") from e
        except OSError as e:
            print(f"[PresetManager] OS error: {e}")
            raise IOError(f"无法保存配置文件：磁盘错误\n{str(e)}") from e
        except Exception as e:
            print(f"[PresetManager] Unknown error: {e}")
            import traceback
            traceback.print_exc()
            raise IOError(f"保存配置文件时发生未知错误：{str(e)}") from e

    # ------------------------------------------------------------------ crud
    def get_all(self) -> list[Preset]:
        """获取所有预设角色，内置角色排在前面"""
        builtin = [p for p in self._presets.values() if p.is_builtin]
        custom = [p for p in self._presets.values() if not p.is_builtin]
        return builtin + custom

    def get(self, preset_id: str) -> Optional[Preset]:
        """获取指定预设角色"""
        return self._presets.get(preset_id)

    def create(self, preset: Preset) -> Preset:
        """创建新预设角色"""
        self._presets[preset.id] = preset
        self._save()
        return preset

    def update(self, preset: Preset):
        """更新预设角色（所有预设都可修改）"""
        self._presets[preset.id] = preset
        self._save()

    def delete(self, preset_id: str):
        """删除预设角色（内置角色不可删除）"""
        preset = self._presets.get(preset_id)
        if preset and preset.is_builtin:
            raise ValueError("内置预设角色不可删除，但可以编辑或恢复默认")
        self._presets.pop(preset_id, None)
        self._save()

    def restore_builtin(self, preset_id: str):
        """恢复内置预设到原始状态"""
        original = self._builtin_originals.get(preset_id)
        if not original:
            raise ValueError(f"预设 {preset_id} 不是内置预设")

        # 恢复到原始状态（深拷贝）
        self._presets[preset_id] = Preset(
            id=original.id,
            name=original.name,
            icon=original.icon,
            system_prompt=original.system_prompt,
            params=dict(original.params),
            is_builtin=original.is_builtin,
        )
        self._save()

    def is_modified(self, preset_id: str) -> bool:
        """检查内置预设是否被修改"""
        preset = self._presets.get(preset_id)
        original = self._builtin_originals.get(preset_id)

        if not preset or not original:
            return False

        # 比较关键字段
        return (
            preset.name != original.name
            or preset.icon != original.icon
            or preset.system_prompt != original.system_prompt
            or preset.params != original.params
        )

    def duplicate(self, preset_id: str, new_name: str = None) -> Preset:
        """
        复制预设角色

        Args:
            preset_id: 要复制的预设 ID
            new_name: 新预设的名称（可选，默认为 "原名称 副本"）

        Returns:
            新创建的预设对象
        """
        original = self._presets.get(preset_id)
        if not original:
            raise ValueError(f"预设 {preset_id} 不存在")

        # 生成新的 ID
        import uuid
        new_id = str(uuid.uuid4())[:8]

        # 生成新的名称
        if not new_name:
            new_name = f"{original.name} 副本"

        # 创建新预设（is_builtin=False，可编辑）
        new_preset = Preset(
            id=new_id,
            name=new_name,
            icon=original.icon,
            system_prompt=original.system_prompt,
            params=dict(original.params),  # 深拷贝
            is_builtin=False  # 关键：复制的预设不是内置的
        )

        self._presets[new_id] = new_preset
        self._save()
        return new_preset

    # ------------------------------------------------------------------ import/export
    def export_to_file(self, file_path: Path):
        """导出所有预设角色到文件"""
        data = [p.to_dict() for p in self._presets.values() if not p.is_builtin]
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def import_from_file(self, file_path: Path):
        """从文件导入预设角色"""
        with open(file_path, encoding="utf-8") as f:
            data = json.load(f)
        for item in data:
            preset = Preset.from_dict(item)
            if preset.id not in self._presets:
                self._presets[preset.id] = preset
        self._save()
