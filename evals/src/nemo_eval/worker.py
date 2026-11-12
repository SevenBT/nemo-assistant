"""One disposable process per case; offline execution disallows networking."""
import importlib.abc
import json
import socket
import sys
import tempfile
from pathlib import Path


class HeadlessImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"PyQt6", "qfluentwidgets", "uiautomation", "keyring"} or fullname == "app.core.config":
            raise ImportError(f"Desktop dependency forbidden in eval worker: {fullname}")


def main():
    payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    sys.meta_path.insert(0, HeadlessImports())
    if payload["mode"] == "offline":
        def denied(*args, **kwargs):
            raise RuntimeError("Network access forbidden in offline evaluation")
        socket.create_connection = denied
        socket.socket.connect = denied
        socket.socket.connect_ex = denied
    from nemo_eval.adapters.nemo import execute
    from nemo_eval.artifacts import write_json
    with tempfile.TemporaryDirectory(prefix="nemo-eval-") as directory:
        result = execute(payload["case"], Path(directory), payload["mode"], payload.get("config"))
        write_json(Path(sys.argv[2]), result)


if __name__ == "__main__":
    main()
