"""
reminder — 发送一条提醒消息。

输入（stdin JSON）:
  {"params": {"message": "该写作业了"}, "context": {}}

输出（stdout 最后一行 JSON）:
  {"status": "success", "data": {"message": "该写作业了"}}
"""
import json
import sys
from datetime import datetime


def main():
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = {}

    message = payload.get("params", {}).get("message", "提醒")
    now = datetime.now().strftime("%H:%M:%S")

    result = {
        "status": "success",
        "data": {
            "message": message,
            "time": now,
        },
    }
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
