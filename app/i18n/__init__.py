"""轻量 i18n 机制 — Python 字典 + t(key) 取值。

设计：
- 语言在启动时锁定一次（init_language），运行期不变；切换语言需重启应用。
- t(key, **kwargs) 按锁定语言取文案；缺 key 时回退到 key 本身（防崩、便于发现漏翻）。
- 文案支持 str.format 占位：t("toast.deleted_n", n=3) → "Deleted 3 items"。

用法:
    from app.i18n import t, init_language

    init_language("zh")          # main.py 启动时调用一次
    label = t("nav.chat")        # "聊天"
    msg = t("toast.deleted_n", n=3)
"""

from app.i18n.en import EN
from app.i18n.zh import ZH

_TABLES: dict[str, dict[str, str]] = {"en": EN, "zh": ZH}

# 当前锁定语言。默认 en，与 config 默认值一致；init_language 在启动时覆盖。
_current_lang: str = "en"


def init_language(lang: str) -> None:
    """锁定本次运行的界面语言。应在创建 QApplication 后、构建窗口前调用一次。"""
    global _current_lang
    _current_lang = lang if lang in _TABLES else "en"


def current_language() -> str:
    """返回本次运行锁定的语言代码（"en" / "zh"）。"""
    return _current_lang


def t(key: str, **kwargs: object) -> str:
    """按当前语言取文案。

    缺 key 时回退当前语言→英文→key 本身。含 kwargs 时做 str.format 占位填充；
    占位与文案不匹配时静默返回未格式化文案，避免运行期因文案错误崩溃。
    """
    table = _TABLES.get(_current_lang, EN)
    text = table.get(key)
    if text is None:
        text = EN.get(key, key)
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return text
    return text


def all_translations(key: str) -> set[str]:
    """返回某 key 在所有语言下的文案集合。

    用于「默认标题」这类既是展示值、又是持久化哨兵值的场景：新建项用当前语言
    文案，但判断「是否仍是默认标题」时要兼容任何语言写入的旧数据。
    """
    return {table[key] for table in _TABLES.values() if key in table}

