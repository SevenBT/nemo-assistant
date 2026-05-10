# 读取文件
with open("tools/multi_model_consult/tool.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

# 新的 call_litellm_model 函数
new_function = '''def call_litellm_model(
    config: ConfigManager,
    model_id: str,
    model_name: str,
    provider: str,
    system_prompt: str,
    query: str,
    context: str,
    timeout: float = 30.0
) -> dict:
    """直接使用 LiteLLM 库调用模型"""
    try:
        import litellm
    except ImportError:
        return {
            "model_id": model_id,
            "model_name": model_name,
            "provider": provider,
            "status": "error",
            "error": "LiteLLM 未安装",
        }
    
    api_key = config.get_litellm_provider_api_key(provider)
    if not api_key:
        return {
            "model_id": model_id,
            "model_name": model_name,
            "provider": provider,
            "status": "error",
            "error": f"{provider} API Key 未配置",
        }
    
    logger.info(f"调用 LiteLLM 模型: {model_id} ({provider}), timeout={timeout}s")
    
    litellm_model = f"{provider}/{model_id}"
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"问题：{query}\n\n上下文：{context}" if context else f"问题：{query}"}
    ]
    
    try:
        response = litellm.completion(
            model=litellm_model,
            messages=messages,
            max_tokens=config.max_tokens,
            temperature=config.temperature,
            api_key=api_key,
            timeout=timeout,
        )
        
        content = response.choices[0].message.content
        logger.info(f"模型 {model_id} 调用成功，返回内容长度: {len(content)}")
        
        return {
            "model_id": model_id,
            "model_name": model_name,
            "provider": provider,
            "status": "success",
            "content": content,
        }
    
    except Exception as e:
        logger.error(f"调用 LiteLLM 模型 {model_id} 失败: {str(e)}")
        return {
            "model_id": model_id,
            "model_name": model_name,
            "provider": provider,
            "status": "error",
            "error": str(e),
        }

'''

# 找到 call_litellm_model 函数的起始和结束行
start_idx = None
end_idx = None

for i, line in enumerate(lines):
    if "def call_litellm_model(" in line:
        start_idx = i
    if start_idx is not None and i > start_idx and line.strip().startswith("def "):
        end_idx = i
        break

if start_idx is None:
    print("ERROR: 未找到 call_litellm_model 函数")
    exit(1)

if end_idx is None:
    # 如果没有找到下一个函数，找到文件末尾
    end_idx = len(lines)

print(f"替换第 {start_idx+1} 到 {end_idx} 行")

# 替换函数
new_lines = lines[:start_idx] + [new_function] + lines[end_idx:]

# 写回文件
with open("tools/multi_model_consult/tool.py", "w", encoding="utf-8") as f:
    f.writelines(new_lines)

print("multi_model_consult/tool.py 已更新")
