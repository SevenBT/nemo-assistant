import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tools.multi_model_consult.tool import call_model_async, multi_model_consult_async

async def test_parallel():
    print("Testing parallel execution...")
    mock_config = MagicMock()
    mock_config.api_key = "test-key"
    mock_config.api_base_url = "https://api.openai.com/v1"
    mock_config.max_tokens = 1000
    mock_config.temperature = 0.7
    
    call_times = []
    
    async def mock_call(*args, **kwargs):
        call_times.append(asyncio.get_event_loop().time())
        await asyncio.sleep(0.1)
        return "Response"
    
    with patch("tools.multi_model_consult.tool.ConfigManager", return_value=mock_config):
        with patch("tools.multi_model_consult.tool.call_openai_model_async", side_effect=mock_call):
            start = asyncio.get_event_loop().time()
            await multi_model_consult_async("Query", ["architect", "security", "performance"], "", 30.0)
            elapsed = asyncio.get_event_loop().time() - start
            
            time_diff = max(call_times) - min(call_times) if len(call_times) >= 2 else 0
            print(f"Elapsed: {elapsed:.3f}s, Time diff: {time_diff:.3f}s")
            print(f"Parallel: {elapsed < 0.2 and time_diff < 0.05}")

asyncio.run(test_parallel())
