import sys

# 修复 tools/multi_model_consult/tool.py
print("修复 tools/multi_model_consult/tool.py...")

with open("tools/multi_model_consult/tool.py", "rb") as f:
    content = f.read().decode("utf-8")

# 直接替换整个 call_litellm_model 函数
old_function_start = 'def call_litellm_model('
old_function_end = 'def call_model('

start_idx = content.find(old_function_start)
end_idx = content.find(old_function_end, start_idx)

if start_idx == -1 or end_idx == -1:
    print("ERROR: 未找到函数边界")
    sys.exit(1)

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

new_content = content[:start_idx] + new_function + content[end_idx:]

with open("tools/multi_model_consult/tool.py", "wb") as f:
    f.write(new_content.encode("utf-8"))

print("OK tools/multi_model_consult/tool.py 已修复")

# 验证语法
try:
    sys.path.insert(0, ".")
    import tools.multi_model_consult.tool as t
    print("OK 语法验证通过")
except Exception as e:
    print(f"ERROR: 语法验证失败: {e}")
    sys.exit(1)

print("\n所有修改完成！")
