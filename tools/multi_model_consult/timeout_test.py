import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tools.multi_model_consult.tool import call_model_async

async def test_timeout():
    print("Testing timeout handling...")
    mock_config = MagicMock()
    mock_config.api_key = "test-key"
    mock_config.api_base_url = "https://api.openai.com/v1"
    mock_config.max_tokens = 1000
    mock_config.temperature = 0.7
    
    async def slow_call(*args, **kwargs):
        await asyncio.sleep(5)
        return "Should not return"
    
    with patch("tools.multi_model_consult.tool.ConfigManager", return_value=mock_config):
        with patch("tools.multi_model_consult.tool.call_openai_model_async", side_effect=slow_call):
            result = await call_model_async(mock_config, "architect", "Query", "", timeout=0.1)
            print(f"Status: {result['status']}")
            print(f"Error: {result.get('error', 'N/A')}")
            print(f"Timeout handled: {result['status'] == 'error' and '超时' in result.get('error', '')}")

async def test_exception():
    print("\nTesting exception handling...")
    mock_config = MagicMock()
    mock_config.api_key = "test-key"
    mock_config.api_base_url = "https://api.openai.com/v1"
    mock_config.max_tokens = 1000
    mock_config.temperature = 0.7
    
    with patch("tools.multi_model_consult.tool.ConfigManager", return_value=mock_config):
        with patch("tools.multi_model_consult.tool.call_openai_model_async", side_effect=Exception("API Error")):
            result = await call_model_async(mock_config, "architect", "Query", "", timeout=30.0)
            print(f"Status: {result['status']}")
            print(f"Error: {result.get('error', 'N/A')}")
            print(f"Exception handled: {result['status'] == 'error' and 'API Error' in result.get('error', '')}")

async def main():
    await test_timeout()
    await test_exception()

asyncio.run(main())
