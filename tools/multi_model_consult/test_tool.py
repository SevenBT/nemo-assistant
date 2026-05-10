#!/usr/bin/env python3
"""
测试多模型咨询工具
"""
import json
import subprocess
import sys
from pathlib import Path


def test_multi_model_consult():
    """测试多模型咨询功能"""
    print("\n" + "=" * 60)
    print("测试多模型咨询工具")
    print("=" * 60 + "\n")

    # 测试用例
    test_cases = [
        {
            "name": "基础测试（3个视角）",
            "params": {
                "query": "设计一个用户认证系统，需要支持 JWT、OAuth2、多因素认证",
                "perspectives": ["architect", "security", "performance"],
                "context": "Python FastAPI 项目，预计 10K QPS",
            },
        },
        {
            "name": "成本优化测试",
            "params": {
                "query": "选择数据库方案：PostgreSQL vs MySQL vs MongoDB",
                "perspectives": ["architect", "cost"],
                "context": "初创公司，预算有限，数据量预计 1TB",
            },
        },
    ]

    tool_path = Path(__file__).parent / "tool.py"

    for i, test_case in enumerate(test_cases, 1):
        print(f"\n{'#' * 60}")
        print(f"测试用例 {i}: {test_case['name']}")
        print(f"{'#' * 60}\n")

        payload = {"params": test_case["params"]}

        print(f"查询: {test_case['params']['query']}")
        print(f"视角: {', '.join(test_case['params']['perspectives'])}")
        print(f"\n正在调用工具...\n")

        result = subprocess.run(
            [sys.executable, str(tool_path)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

        try:
            response = json.loads(result.stdout)

            if response["status"] == "success":
                print("✅ 调用成功！\n")
                print(response["data"]["result"])
            else:
                print(f"❌ 调用失败: {response['data']['message']}")

        except json.JSONDecodeError as e:
            print(f"❌ JSON 解析错误: {e}")
            print(f"原始输出: {result.stdout}")
            print(f"错误输出: {result.stderr}")

        print("\n" + "=" * 60)


if __name__ == "__main__":
    test_multi_model_consult()
