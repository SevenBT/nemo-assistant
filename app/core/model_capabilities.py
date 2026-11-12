"""Pure model capability heuristics."""
# Substrings that mark a model name as vision-capable.
# Used only for the "auto" heuristic; users can override via visionSupport.
_VISION_MODEL_MARKERS = (
    "gpt-4o", "gpt-4.1", "gpt-4-turbo", "gpt-4-vision", "gpt-5",
    "o1", "o3", "o4",
    "claude-3", "claude-4", "claude-opus", "claude-sonnet", "claude-haiku",
    "claude-fable", "claude-mythos", "claude-sonnet-5", "claude-haiku-5",
    "gemini",
    "deepseek",
    "vl", "vision", "llava", "qwen-vl", "qwen2-vl", "qwen2.5-vl", "qwen3",
    "pixtral", "internvl", "minicpm-v", "glm-4v", "glm-5v", "step-1v",
)


def model_supports_vision(model: str) -> bool:
    """Heuristic: does this OpenAI-compatible model name imply image input?"""
    name = (model or "").strip().lower()
    if not name:
        return False
    return any(marker in name for marker in _VISION_MODEL_MARKERS)
