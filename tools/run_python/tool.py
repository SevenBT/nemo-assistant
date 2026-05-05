import io
import json
import sys
import traceback


def main():
    payload = json.loads(sys.stdin.read() or "{}")
    code = payload.get("params", {}).get("code", "").strip()

    if not code:
        print(json.dumps({"status": "error", "data": {"message": "code is required"}}))
        return

    out_buf = io.StringIO()
    err_buf = io.StringIO()

    # ToolManager already redirected sys.stdout to its capture buffer via redirect_stdout.
    # Save current stdout/stderr so we can restore after exec, and so our final
    # print(json.dumps(...)) goes to the right place.
    saved_stdout = sys.stdout
    saved_stderr = sys.stderr

    sys.stdout = out_buf
    sys.stderr = err_buf

    exec_globals = {"__builtins__": __builtins__, "__name__": "__main__"}
    status = "success"
    error_msg = None

    try:
        exec(compile(code, "<run_python>", "exec"), exec_globals)  # noqa: S102
    except SystemExit:
        pass
    except Exception:
        status = "error"
        error_msg = traceback.format_exc()
    finally:
        sys.stdout = saved_stdout
        sys.stderr = saved_stderr

    stdout_val = out_buf.getvalue()
    stderr_val = err_buf.getvalue()
    combined = (stdout_val + ("\n" + error_msg if error_msg else "")).strip()

    print(
        json.dumps(
            {
                "status": status,
                "data": {
                    "output": stdout_val,
                    "stderr": stderr_val,
                    "error": error_msg,
                    "combined": combined,
                },
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
