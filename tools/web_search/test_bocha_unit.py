#!/usr/bin/env python3
"""
博查搜索引擎单元测试
使用 mock 响应测试解析逻辑
"""
import json
from unittest.mock import Mock, patch


def test_bocha_response_parsing():
    """测试博查 API 响应解析逻辑"""
    # Mock 响应数据（基于官方文档示例）
    mock_response_data = {
        "code": 200,
        "log_id": "d71841ad20095f61",
        "msg": None,
        "data": {
            "_type": "SearchResponse",
            "queryContext": {"originalQuery": "Python 最佳实践"},
            "webPages": {
                "webSearchUrl": "",
                "totalEstimatedMatches": 1234567,
                "value": [
                    {
                        "id": None,
                        "name": "Python 编程最佳实践指南",
                        "url": "https://example.com/python-best-practices",
                        "displayUrl": "https://example.com/python-best-practices",
                        "snippet": "本文介绍 Python 编程的最佳实践，包括代码风格、错误处理、性能优化等...",
                        "summary": "详细的 Python 最佳实践总结，涵盖 PEP 8 规范、类型注解、异步编程等核心主题。",
                        "siteName": "Python 中文社区",
                        "siteIcon": "https://example.com/favicon.ico",
                        "datePublished": "2024-01-15T10:30:00+08:00",
                        "dateLastCrawled": "2024-01-15T10:30:00Z",
                        "cachedPageUrl": None,
                        "language": "zh-CN",
                        "isFamilyFriendly": True,
                        "isNavigational": False,
                    },
                    {
                        "id": None,
                        "name": "Python 高级编程技巧",
                        "url": "https://example.com/python-advanced",
                        "displayUrl": "https://example.com/python-advanced",
                        "snippet": "深入探讨 Python 高级特性，包括装饰器、生成器、上下文管理器等...",
                        "siteName": "技术博客",
                        "siteIcon": "https://example.com/icon.png",
                        "datePublished": "2024-02-20T14:20:00+08:00",
                    },
                ],
                "someResultsRemoved": False,
            },
            "images": {"id": None, "value": []},
            "videos": None,
        },
    }

    # Mock httpx 响应
    mock_resp = Mock()
    mock_resp.status_code = 200
    mock_resp.is_success = True
    mock_resp.json.return_value = mock_response_data

    # 导入并测试 _search_bocha 函数
    import sys
    from pathlib import Path

    tool_dir = Path(__file__).parent
    sys.path.insert(0, str(tool_dir))

    with patch("httpx.post", return_value=mock_resp):
        from tool import _search_bocha

        results = _search_bocha(
            query="Python 最佳实践",
            count=5,
            api_key="test_key",
            summary=True,
            freshness="noLimit",
        )

        # 验证结果
        assert len(results) == 2, f"期望 2 条结果，实际 {len(results)} 条"

        # 验证第一条结果
        first = results[0]
        assert first["title"] == "Python 编程最佳实践指南"
        assert first["url"] == "https://example.com/python-best-practices"
        assert "Python 编程的最佳实践" in first["snippet"]
        assert first["summary"] == "详细的 Python 最佳实践总结，涵盖 PEP 8 规范、类型注解、异步编程等核心主题。"
        assert first["site_name"] == "Python 中文社区"
        assert first["date_published"] == "2024-01-15T10:30:00+08:00"

        # 验证第二条结果
        second = results[1]
        assert second["title"] == "Python 高级编程技巧"
        assert second["url"] == "https://example.com/python-advanced"
        assert second["summary"] == ""  # 第二条没有 summary

        print("[PASS] 所有测试通过！")
        return True


def test_bocha_error_handling():
    """测试错误处理逻辑"""
    import sys
    from pathlib import Path

    tool_dir = Path(__file__).parent
    sys.path.insert(0, str(tool_dir))

    from tool import _search_bocha

    # 测试 403 错误（余额不足）
    mock_resp_403 = Mock()
    mock_resp_403.status_code = 403
    mock_resp_403.is_success = False

    with patch("httpx.post", return_value=mock_resp_403):
        try:
            _search_bocha("test", 5, "test_key")
            assert False, "应该抛出异常"
        except Exception as e:
            assert "余额不足" in str(e)
            print(f"[PASS] 403 错误处理正确: {e}")

    # 测试 401 错误（API Key 无效）
    mock_resp_401 = Mock()
    mock_resp_401.status_code = 401
    mock_resp_401.is_success = False

    with patch("httpx.post", return_value=mock_resp_401):
        try:
            _search_bocha("test", 5, "invalid_key")
            assert False, "应该抛出异常"
        except Exception as e:
            assert "API Key 无效" in str(e)
            print(f"[PASS] 401 错误处理正确: {e}")

    # 测试 429 错误（限流）
    mock_resp_429 = Mock()
    mock_resp_429.status_code = 429
    mock_resp_429.is_success = False

    with patch("httpx.post", return_value=mock_resp_429):
        try:
            _search_bocha("test", 5, "test_key")
            assert False, "应该抛出异常"
        except Exception as e:
            assert "频率达到限制" in str(e)
            print(f"[PASS] 429 错误处理正确: {e}")

    print("[PASS] 所有错误处理测试通过！")
    return True


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("博查搜索引擎单元测试")
    print("=" * 60 + "\n")

    try:
        print("测试 1: 响应解析逻辑")
        print("-" * 60)
        test_bocha_response_parsing()

        print("\n测试 2: 错误处理逻辑")
        print("-" * 60)
        test_bocha_error_handling()

        print("\n" + "=" * 60)
        print("[SUCCESS] 所有测试通过！")
        print("=" * 60 + "\n")

    except Exception as e:
        print(f"\n[FAIL] 测试失败: {e}")
        import traceback

        traceback.print_exc()
