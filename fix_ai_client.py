# 读取文件
with open("app/core/ai_client.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

# 新方法内容
new_method = '''    def _chat_stream_litellm(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
    ) -> Iterator[dict]:
        """使用 LiteLLM 库直接调用（不需要服务）"""
        try:
            import litellm
        except ImportError:
            yield {"type": "error", "message": "LiteLLM 未安装，请运行: pip install litellm"}
            return
        
        # 获取默认模型和 provider
        model_id = self._config.litellm_default_model
        model_config = self._config.get_litellm_model_by_id(model_id)
        
        if not model_config:
            yield {"type": "error", "message": f"模型 {model_id} 未找到"}
            return
        
        provider = model_config["provider"]
        api_key = self._config.get_litellm_provider_api_key(provider)
        
        if not api_key:
            yield {"type": "error", "message": f"{provider} API Key 未配置"}
            return
        
        # 构造 LiteLLM 模型名：provider/model
        litellm_model = f"{provider}/{model_id}"
        
        kwargs: dict = {
            "model": litellm_model,
            "messages": messages,
            "max_tokens": self._config.max_tokens,
            "temperature": self._config.temperature,
            "stream": True,
            "api_key": api_key,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        
        try:
            stream = litellm.completion(**kwargs)
            tc_buf: dict[int, dict] = {}
            reasoning_buf = ""
            
            for chunk in stream:
                if not hasattr(chunk, 'choices') or not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = choice.delta
                
                rc = getattr(delta, "reasoning_content", None)
                if rc:
                    reasoning_buf += rc
                
                if hasattr(delta, 'content') and delta.content:
                    yield {"type": "text", "delta": delta.content}
                
                if hasattr(delta, 'tool_calls') and delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tc_buf:
                            tc_buf[idx] = {"id": "", "name": "", "args_str": ""}
                        if tc.id:
                            tc_buf[idx]["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                tc_buf[idx]["name"] = tc.function.name
                            if tc.function.arguments:
                                tc_buf[idx]["args_str"] += tc.function.arguments
                
                if hasattr(choice, 'finish_reason') and choice.finish_reason in ("stop", "tool_calls"):
                    break
            
            for tc_data in tc_buf.values():
                try:
                    args = json.loads(tc_data["args_str"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                yield {
                    "type": "tool_call",
                    "id": tc_data["id"],
                    "name": tc_data["name"],
                    "arguments": args,
                }
            
            yield {"type": "done", "reasoning_content": reasoning_buf or None}
        
        except Exception as e:
            yield {"type": "error", "message": f"LiteLLM 调用失败: {str(e)}"}

'''

# 找到 _chat_stream_litellm 方法的起始和结束行
start_idx = None
end_idx = None

for i, line in enumerate(lines):
    if "def _chat_stream_litellm(" in line:
        start_idx = i
    if start_idx is not None and i > start_idx and line.strip().startswith("@staticmethod"):
        end_idx = i
        break

if start_idx is None or end_idx is None:
    print(f"ERROR: 未找到方法边界 (start={start_idx}, end={end_idx})")
    exit(1)

print(f"替换第 {start_idx+1} 到 {end_idx} 行")

# 替换方法
new_lines = lines[:start_idx] + [new_method] + lines[end_idx:]

# 写回文件
with open("app/core/ai_client.py", "w", encoding="utf-8") as f:
    f.writelines(new_lines)

print("ai_client.py 已更新")
