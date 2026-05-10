import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tools.multi_model_consult.tool import multi_model_consult_async

async def test_partial_failure():
    print("Testing partial failure handling...")
    mock_config = MagicMock()
    mock_config.api_key = "test-key"
    mock_config.api_base_url = "https://api.openai.com/v1"
    mock_config.max_tokens = 1000
    mock_config.temperature = 0.7
    
    call_count = 0
    
    async def mock_call(config, model, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.05)
        if call_count == 2:
            raise Exception("Simulated API failure")
        return f"Response {call_count}"
    
    with patch("tools.multi_model_consult.tool.ConfigManager", return_value=mock_config):
        with patch("tools.multi_model_consult.tool.call_openai_model_async", side_effect=mock_call):
            result = await multi_model_consult_async(
                "Query",
                ["architect", "security", "performance"],
                "",
                30.0
            )
            
            has_success = "架构师" in result or "性能专家" in result
            has_failure = "调用失败的模型" in result
            has_stats = "成功 2/3" in result
            
            print(f"Has success results: {has_success}")
            print(f"Has failure section: {has_failure}")
            print(f"Has correct stats: {has_stats}")
            print(f"Partial failure handled: {has_success and has_failure and has_stats}")

asyncio.run(test_partial_failure())
