"""
Example tool: get_system_info
Reads params from stdin JSON, writes result to stdout (last line JSON).
"""
import json
import platform
import sys


def main():
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = {}

    params = payload.get("params", {})
    detail_level = params.get("detail_level", "basic")

    info: dict = {
        "os": platform.system(),
        "os_version": platform.version(),
        "machine": platform.machine(),
        "python": platform.python_version(),
    }

    if detail_level == "full":
        try:
            import psutil
            info["cpu_percent"] = psutil.cpu_percent(interval=0.5)
            mem = psutil.virtual_memory()
            info["memory_total_gb"] = round(mem.total / (1024**3), 2)
            info["memory_used_gb"] = round(mem.used / (1024**3), 2)
            info["memory_percent"] = mem.percent
        except ImportError:
            info["note"] = "Install psutil for full info: pip install psutil"

    result = {"status": "success", "data": info}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
