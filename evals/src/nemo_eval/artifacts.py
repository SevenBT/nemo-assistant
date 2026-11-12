"""Strict, atomic persistence and explicit run comparisons."""
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
    fd, name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def code_fingerprint(root):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=root, stderr=subprocess.DEVNULL)
    try:
        files = git("ls-files", "-z", "--cached", "--others", "--exclude-standard").decode().split("\0")
        hashes = {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in files if p and (root / p).is_file()}
        return {"commit": git("rev-parse", "HEAD").decode().strip(), "dirty": bool(git("status", "--porcelain")), "source_hash": digest(hashes)}
    except (OSError, subprocess.SubprocessError):
        return {"commit": None, "dirty": None, "source_hash": None}


def compare(current: Path, baseline: Path, *, allow_changes=()):
    cur = json.loads((current / "manifest.json").read_text(encoding="utf-8"))
    base = json.loads((baseline / "manifest.json").read_text(encoding="utf-8"))
    permitted = {"target.model", "target.api_protocol", "target.provider", "target.base_url", "target.temperature", "target.top_p", "target.max_tokens"}
    if set(allow_changes) - permitted:
        raise ValueError("Unsupported comparison change dimension")
    conditions = []
    if allow_changes:
        configs = [json.loads(json.dumps(m.get("config", {}))) for m in (cur, base)]
        for dimension in allow_changes:
            section, field = dimension.split(".")
            values = [c.get(section, {}).pop(field, None) for c in configs]
            if values[0] != values[1]:
                conditions.append({"dimension": dimension, "current": values[0], "baseline": values[1]})
        if configs[0] != configs[1]:
            raise ValueError("Incompatible baseline: undeclared configuration change")
    for key in ("case_hash", "mode", "evaluator_version", *(() if allow_changes else ("config_hash",))):
        if cur.get(key) != base.get(key):
            raise ValueError(f"Incompatible baseline: {key}")
    if not cur.get("complete") or not base.get("complete"):
        raise ValueError("Cannot compare incomplete runs")
    def results(path):
        return {r["case_id"]: r for r in json.loads((path / "summary.json").read_text(encoding="utf-8"))["results"]}
    c, b = results(current), results(baseline)
    if set(c) != set(b):
        raise ValueError("Case results do not match")
    return [{"case_id": k, "baseline": b[k]["verdict"], "current": c[k]["verdict"], "changed_conditions": conditions} for k in sorted(c)]
