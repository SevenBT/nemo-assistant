"""测试 LiteLLM UI 配置"""
import sys
from PyQt6.QtWidgets import QApplication
from app.core.config import ConfigManager
from app.ui.settings_dialog import SettingsDialog


def test_litellm_ui():
    app = QApplication(sys.argv)
    config = ConfigManager()

    # 打印当前 LiteLLM 配置
    print("当前 LiteLLM 配置:")
    print(f"  enabled: {config.litellm_enabled}")
    print(f"  base_url: {config.litellm_base_url}")
    print(f"  default_model: {config.litellm_default_model}")
    print(f"  models: {len(config.litellm_models)} 个")
    print(f"  enabled_models: {len(config.litellm_enabled_models)} 个")

    # 打开设置对话框
    dialog = SettingsDialog(config, None)
    result = dialog.exec()

    if result:
        print("\n保存后的 LiteLLM 配置:")
        print(f"  enabled: {config.litellm_enabled}")
        print(f"  base_url: {config.litellm_base_url}")
        print(f"  default_model: {config.litellm_default_model}")
        print(f"  api_type: {config.api_type}")
        print(f"  enabled_models:")
        for model in config.litellm_enabled_models:
            print(f"    - {model['name']} ({model['provider']})")
    else:
        print("\n用户取消了设置")


if __name__ == "__main__":
    test_litellm_ui()
