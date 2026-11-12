"""Resolve prompt text once; task fixtures never carry live variants."""
from pathlib import Path
import tomllib

from nemo_eval.artifacts import digest


def resolve_variant(path=None, *, language="zh"):
    data = {"id": "production", "prompt": {"source": "production-default"}}
    if path is not None:
        path = Path(path)
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    if set(data) != {"id", "prompt"} or not isinstance(data["id"], str) or not data["id"]:
        raise ValueError("Variant requires id and prompt")
    prompt = data["prompt"]
    if not isinstance(prompt, dict):
        raise ValueError("Invalid variant prompt")
    source = prompt.get("source")
    if source == "production-default" and set(prompt) == {"source"}:
        from nemo_eval.adapters.nemo import default_prompt
        text = default_prompt(language)
    elif source == "text-file" and set(prompt) == {"source", "path"}:
        if path is None or not isinstance(prompt["path"], str):
            raise ValueError("text-file requires a path relative to the variant")
        text = (path.parent / prompt["path"]).read_text(encoding="utf-8").strip()
    else:
        raise ValueError("Unsupported variant prompt source or fields")
    if not text.strip():
        raise ValueError("Prompt variant cannot be empty")
    return {"id": data["id"], "source": source, "text": text,
            "hash": digest({"source": source, "text": text})}
