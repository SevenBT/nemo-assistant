"""
异步改造单元测试
测试 multi_model_consult 工具的异步逻辑
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tools.multi_model_consult.tool import (
    call_model_async,
    multi_model_consult_async,
    PERSPECTIVES,
)


async def test_call_model_async_success():
    """测试单个模型异步调用成功"""
    print("\n[测试 1] 测试单个模型异步调用成功...")
    
    mock_config = MagicMock()
    mock_config.api_key = "test-key"
    mock_config.api_base_url = "https://api.openai.com/v1"
    mock_config.max_tokens = 1000
    mock_config.temperature = 0.7
    
    with patch("tools.multi_model_consult.tool.ConfigManager", return_value=mock_config):
        with patch("tools.multi_model_consult.tool.call_openai_model_async") as mock_call:
            mock_call.return_value = "这是架构师的建议"
            
            result = await call_model_async(
                mock_config,
                "architect",
                "如何设计一个高可用系统？",
                "",
                timeout=30.0
            )
            
            assert result["status"] == "success"
            assert result["perspective_id"] == "architect"
            assert result["perspective_name"] == "架构师"
            assert result["content"] == "这是架构师的建议"
            assert "timestamp" in result
            
            print("✓ 单个模型异步调用成功测试通过")


async def test_call_model_async_timeout():
    """测试单个模型调用超时"""
    print("\n[测试 2] 测试单个模型调用超时...")
    
    mock_config = MagicMock()
    mock_config.api_key = "test-key"
    mock_config.api_base_url = "https://api.openai.com/v1"
    mock_config.max_tokens = 1000
    mock_config.temperature = 0.7
    
    with patch("tools.multi_model_consult.tool.ConfigManager", return_value=mock_config):
        with patch("tools.multi_model_consult.tool.call_openai_model_async") as mock_call:
            # 模拟超时
            async def slow_call(*args, **kwargs):
                await asyncio.sleep(5)
                return "不应该返回"
            
            mock_call.side_effect = slow_call
            
            result = await call_model_async(
                mock_config,
                "architect",
                "如何设计一个高可用系统？",
                "",
                timeout=0.1  # 设置很短的超时
            )
            
            assert result["status"] == "error"
            assert "超时" in result["error"]
            assert result["perspective_id"] == "architect"
            
            print("✓ 超时处理测试通过")


async def test_call_model_async_exception():
    """测试单个模型调用异常"""
    print("\n[测试 3] 测试单个模型调用异常...")
    
    mock_config = MagicMock()
    mock_config.api_key = "test-key"
    mock_config.api_base_url = "https://api.openai.com/v1"
    mock_config.max_tokens = 1000
    mock_config.temperature = 0.7
    
    with patch("tools.multi_model_consult.tool.ConfigManager", return_value=mock_config):
        with patch("tools.multi_model_consult.tool.call_openai_model_async") as mock_call:
            mock_call.side_effect = Exception("API 调用失败")
            
            result = await call_model_async(
                mock_config,
                "architect",
                "如何设计一个高可用系统？",
                "",
                timeout=30.0
            )
            
            assert result["status"] == "error"
            assert "API 调用失败" in result["error"]
            assert result["perspective_id"] == "architect"
            
            print("✓ 异常处理测试通过")


async def test_multi_model_consult_parallel():
    """测试多模型并行调用"""
    print("\n[测试 4] 测试多模型并行调用...")
    
    mock_config = MagicMock()
    mock_config.api_key = "test-key"
    mock_config.api_base_url = "https://api.openai.com/v1"
    mock_config.max_tokens = 1000
    mock_config.temperature = 0.7
    
    call_count = 0
    call_times = []
    
    async def mock_call_openai(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        call_times.append(asyncio.get_event_loop().time())
        await asyncio.sleep(0.1)  # 模拟 API 调用延迟
        return f"模型 {call_count} 的响应"
    
    with patch("tools.multi_model_consult.tool.ConfigManager", return_value=mock_config):
        with patch("tools.multi_model_consult.tool.call_openai_model_async", side_effect=mock_call_openai):
            start_time = asyncio.get_event_loop().time()
            
            result = await multi_model_consult_async(
                query="如何设计一个高可用系统？",
                perspectives=["architect", "security", "performance"],
                context="",
                timeout=30.0
            )
            
            end_time = asyncio.get_event_loop().time()
            elapsed = end_time - start_time
            
            # 验证并行调用
            assert call_count == 3, f"应该调用 3 次，实际调用 {call_count} 次"
            
            # 验证并行性：3 个调用应该几乎同时开始
            if len(call_times) >= 2:
                time_diff = max(call_times) - min(call_times)
                assert time_diff < 0.05, f"调用时间差 {time_diff}s 过大，可能不是并行"
            
            # 验证总时间：并行调用应该接近单次调用时间（0.1s），而不是串行的 3 倍（0.3s）
            assert elapsed < 0.2, f"总耗时 {elapsed}s 过长，可能不是并行调用"
            
            # 验证结果格式
            assert "多模型咨询结果" in result
            assert "架构师" in result or "安全专家" in result or "性能专家" in result
            assert "统计" in result
            
            print(f"✓ 并行调用测试通过（耗时 {elapsed:.3f}s，调用时间差 {time_diff:.3f}s）")


async def test_multi_model_consult_partial_failure():
    """测试部分模型失败的情况"""
    print("\n[测试 5] 测试部分模型失败...")
    
    mock_config = MagicMock()
    mock_config.api_key = "test-key"
    mock_config.api_base_url = "https://api.openai.com/v1"
    mock_config.max_tokens = 1000
    mock_config.temperature = 0.7
    
    call_count = 0
    
    async def mock_call_openai(config, model, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.05)
        
        # 第二个调用失败
        if call_count == 2:
            raise Exception("模拟 API 失败")
        
        return f"模型 {call_count} 的响应"
    
    with patch("tools.multi_model_consult.tool.ConfigManager", return_value=mock_config):
        with patch("tools.multi_model_consult.tool.call_openai_model_async", side_effect=mock_call_openai):
            result = await multi_model_consult_async(
                query="如何设计一个高可用系统？",
                perspectives=["architect", "security", "performance"],
                context="",
                timeout=30.0
            )
            
            # 验证结果包含成功和失败的信息
            assert "多模型咨询结果" in result
            assert "调用失败的模型" in result
            assert "统计" in result
            assert "成功 2/3" in result
            
            print("✓ 部分失败处理测试通过")


async def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("开始异步改造单元测试")
    print("=" * 60)
    
    try:
        await test_call_model_async_success()
        await test_call_model_async_timeout()
        await test_call_model_async_exception()
        await test_multi_model_consult_parallel()
        await test_multi_model_consult_partial_failure()
        
        print("\n" + "=" * 60)
        print("所有测试通过 ✓")
        print("=" * 60)
        return True
        
    except AssertionError as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    except Exception as e:
        print(f"\n✗ 测试异常: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)
