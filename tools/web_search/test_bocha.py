#!/usr/bin/env python3
"""
博查搜索引擎测试脚本
测试新实现的博查 API 集成
"""
import json
import subprocess
import sys
from pathlib import Path


def test_bocha_search(query: str, api_key: str, count: int = 5, summary: bool = False):
    """测试博查搜索功能"""
    print(f"\n{'='*60}")
    print(f"测试查询: {query}")
    print(f"结果数量: {count}, 摘要: {summary}")
    print(f"{'='*60}\n")

    # 构建测试参数
    payload = {
        "params": {
            "query": query,
            "count": count,
            "provider": "bocha",
            "api_key": api_key,
            "summary": summary,
            "freshness": "noLimit",
        }
    }

    # 调用工具脚本
    tool_path = Path(__file__).parent / "tool.py"
    result = subprocess.run(
        [sys.executable, str(tool_path)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    # 解析结果
    try:
        response = json.loads(result.stdout)

        if response["status"] == "success":
            data = response["data"]
            results = data["results"]

            print(f"✅ 搜索成功！")
            print(f"提供商: {data['provider']}")
            print(f"返回结果数: {len(results)}\n")

            for i, item in enumerate(results, 1):
                print(f"[{i}] {item['title']}")
                print(f"    URL: {item['url']}")
                print(f"    摘要: {item['snippet'][:100]}...")
                if item.get('summary'):
                    print(f"    文本摘要: {item['summary'][:100]}...")
                if item.get('site_name'):
                    print(f"    网站: {item['site_name']}")
                if item.get('date_published'):
                    print(f"    发布时间: {item['date_published']}")
                print()

            return True
        else:
            print(f"❌ 搜索失败: {response['data']['message']}")
            return False

    except json.JSONDecodeError as e:
        print(f"❌ JSON 解析错误: {e}")
        print(f"原始输出: {result.stdout}")
        print(f"错误输出: {result.stderr}")
        return False
    except Exception as e:
        print(f"❌ 未知错误: {e}")
        return False


def main():
    """主测试函数"""
    print("\n" + "="*60)
    print("博查搜索引擎测试")
    print("="*60)

    # 从环境变量或命令行参数获取 API Key
    api_key = input("请输入博查 API Key (或按 Enter 跳过): ").strip()

    if not api_key:
        print("\n⚠️  未提供 API Key，跳过测试")
        print("提示: 请前往 https://open.bocha.cn 获取 API Key")
        return

    # 测试用例
    test_cases = [
        {
            "query": "Python 最佳实践",
            "count": 3,
            "summary": False,
        },
        {
            "query": "阿里巴巴2024年ESG报告",
            "count": 5,
            "summary": True,
        },
    ]

    success_count = 0
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n{'#'*60}")
        print(f"测试用例 {i}/{len(test_cases)}")
        print(f"{'#'*60}")

        if test_bocha_search(api_key=api_key, **test_case):
            success_count += 1

    # 总结
    print(f"\n{'='*60}")
    print(f"测试完成: {success_count}/{len(test_cases)} 通过")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
