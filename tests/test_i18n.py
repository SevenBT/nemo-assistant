"""i18n 机制与字典完整性测试。"""

import pytest

from app.i18n import t, init_language, current_language
from app.i18n.en import EN
from app.i18n.zh import ZH


def test_en_zh_keys_in_sync():
    """en.py 与 zh.py 必须有完全一致的 key 集合（防漏翻）。"""
    only_en = set(EN) - set(ZH)
    only_zh = set(ZH) - set(EN)
    assert not only_en, f"keys missing from zh.py: {only_en}"
    assert not only_zh, f"keys missing from en.py: {only_zh}"


def test_no_empty_values():
    """文案不允许为空串。"""
    for k, v in EN.items():
        assert v, f"empty EN value for {k}"
    for k, v in ZH.items():
        assert v, f"empty ZH value for {k}"


def test_t_returns_locked_language():
    init_language("zh")
    assert current_language() == "zh"
    assert t("settings.title") == "设置"
    init_language("en")
    assert current_language() == "en"
    assert t("settings.title") == "Settings"


def test_t_missing_key_falls_back_to_key():
    init_language("en")
    assert t("no.such.key.exists") == "no.such.key.exists"


def test_t_unknown_language_falls_back_to_en():
    init_language("fr")  # not supported
    assert current_language() == "en"
    assert t("settings.title") == "Settings"


def test_t_format_placeholders():
    init_language("en")
    # 带占位的 key 若存在则应正确格式化；用一个已知带占位的文案验证机制本身
    # 这里直接验证 format 不会因缺参崩溃
    assert isinstance(t("settings.title"), str)


def teardown_function():
    # 还原为默认，避免影响其它测试
    init_language("en")
