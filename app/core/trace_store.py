"""统一 Trace 存储 — 把一次 Agent 运行的全链路记录落到独立 SQLite。

设计目标（评测 / 安全审计的共同地基）：
    一次 AgentLoop 运行 = 一个 trace_id，贯穿其下所有 LLM 调用、工具调用、
    状态机流转。三类记录全部 keyed by 同一个 trace_id，回放即按 trace_id
    把它们重组成一次完整 turn。

关键约束：
    1. 独立 data/traces.db，不污染业务 notes.db；遥测可单独清理/限容。
    2. AgentLoop 在 QThread、只读工具在 ThreadPoolExecutor，多线程并发写——
       每次操作开独立短连接 + 进程内写锁 + WAL 模式。
    3. 记录失败绝不影响主流程：所有写入 try/except 包死，只 log 不抛。
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import DATA_DIR

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = DATA_DIR / "traces.db"

# 工具入参/结果可能含用户数据，回放需要看 I/O，但要防止超长记录撑爆库。
_MAX_FIELD_CHARS = 2000

# prune 默认保留的 turn 条数（按 started_at 倒序）。
_DEFAULT_KEEP_TURNS = 2000


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _truncate(text: str | None) -> str | None:
    """超长字段截断，标注原始长度，避免单行记录无限膨胀。"""
    if text is None:
        return None
    if len(text) <= _MAX_FIELD_CHARS:
        return text
    return text[:_MAX_FIELD_CHARS] + f"\n[truncated, original {len(text)} chars]"


def _to_json(value: Any) -> str | None:
    """把任意结构安全序列化为 JSON 字符串并截断；失败回退 str()。"""
    if value is None:
        return None
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(value)
    return _truncate(text)


class TraceStore:
    """管理 traces.db 的写入与回放查询。

    全部公开方法对调用方异常安全：写入路径吞掉所有异常（只 log），
    查询路径失败返回空结果，绝不让遥测把主流程带崩。
    """

    def __init__(self, db_path: Path | str | None = None, enabled: bool = True):
        self._path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self._enabled = enabled
        self._lock = threading.Lock()
        self._schema_ready = False
        if self._enabled:
            try:
                self._ensure_schema()
                self._schema_ready = True
            except Exception:
                logger.exception("[TraceStore] schema init failed, disabling")
                self._enabled = False

    @classmethod
    def disabled(cls) -> "TraceStore":
        return cls(enabled=False)

    @property
    def enabled(self) -> bool:
        return self._enabled and self._schema_ready

    # ── 连接管理 ────────────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        # WAL：读写并发更友好（多线程写场景）；busy_timeout 兜底锁等待。
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=3000")
        return conn

    def _ensure_schema(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS turns (
                    trace_id    TEXT PRIMARY KEY,
                    session_id  TEXT,
                    started_at  TEXT NOT NULL,
                    ended_at    TEXT,
                    status      TEXT NOT NULL DEFAULT 'running',
                    error       TEXT,
                    turn_count  INTEGER NOT NULL DEFAULT 0,
                    duration_ms REAL,
                    prompt_tokens     INTEGER NOT NULL DEFAULT 0,
                    completion_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens      INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS llm_calls (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    trace_id     TEXT NOT NULL,
                    seq          INTEGER NOT NULL,
                    api_type     TEXT,
                    provider     TEXT,
                    model        TEXT,
                    has_tools    INTEGER NOT NULL DEFAULT 0,
                    input_message_count INTEGER,
                    ttft_ms      REAL,
                    latency_ms   REAL,
                    retry_count  INTEGER NOT NULL DEFAULT 0,
                    status       TEXT,
                    error_type   TEXT,
                    error_kind   TEXT,
                    error_status_code INTEGER,
                    error_message TEXT,
                    prompt_tokens     INTEGER,
                    completion_tokens INTEGER,
                    total_tokens      INTEGER,
                    cached_tokens     INTEGER,
                    created_at   TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tool_calls (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    trace_id    TEXT NOT NULL,
                    call_id     TEXT,
                    name        TEXT NOT NULL,
                    arguments   TEXT,
                    status      TEXT,
                    error_type  TEXT,
                    result      TEXT,
                    duration_ms REAL,
                    created_at  TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS state_trace (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    trace_id    TEXT NOT NULL,
                    seq         INTEGER NOT NULL,
                    state       TEXT NOT NULL,
                    event       TEXT,
                    duration_ms REAL,
                    created_at  TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS security_events (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    trace_id    TEXT NOT NULL,
                    call_id     TEXT,
                    tool_name   TEXT NOT NULL,
                    risk        TEXT,
                    decision    TEXT NOT NULL,
                    reason      TEXT,
                    arguments   TEXT,
                    created_at  TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS eval_samples (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    trace_id    TEXT NOT NULL,
                    turn        INTEGER NOT NULL,
                    answer      TEXT,
                    tool_count  INTEGER NOT NULL DEFAULT 0,
                    error_count INTEGER NOT NULL DEFAULT 0,
                    had_error   INTEGER NOT NULL DEFAULT 0,
                    scores      TEXT,
                    created_at  TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id);
                CREATE INDEX IF NOT EXISTS idx_turns_started ON turns(started_at DESC);
                CREATE INDEX IF NOT EXISTS idx_llm_trace ON llm_calls(trace_id);
                CREATE INDEX IF NOT EXISTS idx_tool_trace ON tool_calls(trace_id);
                CREATE INDEX IF NOT EXISTS idx_state_trace ON state_trace(trace_id);
                CREATE INDEX IF NOT EXISTS idx_sec_trace ON security_events(trace_id);
                CREATE INDEX IF NOT EXISTS idx_eval_trace ON eval_samples(trace_id);
                """
            )
            conn.commit()
            self._migrate(conn)

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        """对早于 token 统计的旧库补列（CREATE TABLE IF NOT EXISTS 不会加列）。"""
        new_cols = {
            "turns": [
                ("prompt_tokens", "INTEGER NOT NULL DEFAULT 0"),
                ("completion_tokens", "INTEGER NOT NULL DEFAULT 0"),
                ("total_tokens", "INTEGER NOT NULL DEFAULT 0"),
            ],
            "llm_calls": [
                ("prompt_tokens", "INTEGER"),
                ("completion_tokens", "INTEGER"),
                ("total_tokens", "INTEGER"),
                ("cached_tokens", "INTEGER"),
            ],
        }
        for table, cols in new_cols.items():
            existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            for name, decl in cols:
                if name not in existing:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
        conn.commit()

    # ── 写入接口（异常安全） ─────────────────────────────────────────────

    def start_turn(self, trace_id: str, session_id: str = "") -> None:
        if not self.enabled:
            return
        self._write(
            "INSERT OR REPLACE INTO turns "
            "(trace_id, session_id, started_at, status) VALUES (?, ?, ?, 'running')",
            (trace_id, session_id or None, _now_iso()),
        )

    def finish_turn(
        self,
        trace_id: str,
        *,
        status: str,
        turn_count: int = 0,
        duration_ms: float | None = None,
        error: str | None = None,
    ) -> None:
        """收尾 turn，并从已落库的 llm_calls 汇总 token 用量到 turns 行。"""
        if not self.enabled:
            return
        try:
            with self._lock, self._connect() as conn:
                row = conn.execute(
                    "SELECT COALESCE(SUM(prompt_tokens), 0), "
                    "COALESCE(SUM(completion_tokens), 0), "
                    "COALESCE(SUM(total_tokens), 0) "
                    "FROM llm_calls WHERE trace_id = ?",
                    (trace_id,),
                ).fetchone()
                prompt_tokens, completion_tokens, total_tokens = row
                conn.execute(
                    "UPDATE turns SET ended_at = ?, status = ?, turn_count = ?, "
                    "duration_ms = ?, error = ?, prompt_tokens = ?, "
                    "completion_tokens = ?, total_tokens = ? WHERE trace_id = ?",
                    (
                        _now_iso(),
                        status,
                        turn_count,
                        duration_ms,
                        _truncate(error),
                        prompt_tokens,
                        completion_tokens,
                        total_tokens,
                        trace_id,
                    ),
                )
                conn.commit()
        except Exception:
            logger.exception("[TraceStore] finish_turn failed")

    def record_llm_call(self, trace_id: str, seq: int, record: dict[str, Any]) -> None:
        """记录一次 LLM attempt 汇总（与网关 _write_log 同源字段）。"""
        if not self.enabled:
            return
        usage = record.get("usage") or {}
        self._write(
            "INSERT INTO llm_calls (trace_id, seq, api_type, provider, model, "
            "has_tools, input_message_count, ttft_ms, latency_ms, retry_count, "
            "status, error_type, error_kind, error_status_code, error_message, "
            "prompt_tokens, completion_tokens, total_tokens, cached_tokens, "
            "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
            "?, ?, ?, ?, ?)",
            (
                trace_id,
                seq,
                record.get("api_type"),
                record.get("provider"),
                record.get("model"),
                1 if record.get("has_tools") else 0,
                record.get("input_message_count"),
                record.get("ttft_ms"),
                record.get("latency_ms"),
                record.get("retry_count", 0),
                record.get("status"),
                record.get("error_type"),
                record.get("error_kind"),
                record.get("error_status_code"),
                _truncate(record.get("error_message")),
                usage.get("prompt_tokens"),
                usage.get("completion_tokens"),
                usage.get("total_tokens"),
                usage.get("cached_tokens"),
                _now_iso(),
            ),
        )

    def record_tool_call(
        self,
        trace_id: str,
        *,
        call_id: str,
        name: str,
        arguments: Any,
        result: dict[str, Any] | None,
        duration_ms: float | None,
    ) -> None:
        if not self.enabled:
            return
        status = None
        error_type = None
        if isinstance(result, dict):
            status = result.get("status")
            error_type = result.get("data", {}).get("error_type") if isinstance(
                result.get("data"), dict
            ) else None
        self._write(
            "INSERT INTO tool_calls (trace_id, call_id, name, arguments, status, "
            "error_type, result, duration_ms, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                trace_id,
                call_id,
                name,
                _to_json(_redact_args(arguments)),
                status,
                error_type,
                _to_json(result),
                duration_ms,
                _now_iso(),
            ),
        )

    def record_state_trace(self, trace_id: str, trace: list[dict[str, Any]]) -> None:
        """批量落状态机流转（turn 结束时一次性写入）。"""
        if not self.enabled or not trace:
            return
        rows = [
            (
                trace_id,
                seq,
                entry.get("state", ""),
                entry.get("event"),
                entry.get("duration_ms"),
                _now_iso(),
            )
            for seq, entry in enumerate(trace)
        ]
        self._writemany(
            "INSERT INTO state_trace (trace_id, seq, state, event, duration_ms, "
            "created_at) VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )

    def record_security_event(
        self,
        trace_id: str,
        *,
        call_id: str,
        tool_name: str,
        risk: str | None,
        decision: str,
        reason: str | None,
        arguments: Any,
    ) -> None:
        """记录一次高风险工具调用的安全审计事件（含裁决：allow/reject）。"""
        if not self.enabled:
            return
        self._write(
            "INSERT INTO security_events (trace_id, call_id, tool_name, risk, "
            "decision, reason, arguments, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                trace_id,
                call_id,
                tool_name,
                risk,
                decision,
                _truncate(reason),
                _to_json(_redact_args(arguments)),
                _now_iso(),
            ),
        )

    def record_eval_sample(
        self,
        trace_id: str,
        *,
        turn: int,
        answer: str | None,
        tool_count: int,
        error_count: int,
        had_error: bool,
    ) -> None:
        """记录一轮迭代的评测样本（最终答复 + 工具/错误计数）。scores 留空待离线打分。"""
        if not self.enabled:
            return
        self._write(
            "INSERT INTO eval_samples (trace_id, turn, answer, tool_count, "
            "error_count, had_error, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                trace_id,
                turn,
                _truncate(answer),
                tool_count,
                error_count,
                1 if had_error else 0,
                _now_iso(),
            ),
        )

    # ── 回放 / 查询接口 ──────────────────────────────────────────────────

    def get_turn(self, trace_id: str) -> dict[str, Any] | None:
        """按 trace_id 重组一次完整 turn，供回放使用。"""
        if not self.enabled:
            return None
        try:
            with self._connect() as conn:
                turn_row = conn.execute(
                    "SELECT * FROM turns WHERE trace_id = ?", (trace_id,)
                ).fetchone()
                if turn_row is None:
                    return None
                llm = conn.execute(
                    "SELECT * FROM llm_calls WHERE trace_id = ? ORDER BY seq, id",
                    (trace_id,),
                ).fetchall()
                tools = conn.execute(
                    "SELECT * FROM tool_calls WHERE trace_id = ? ORDER BY id",
                    (trace_id,),
                ).fetchall()
                states = conn.execute(
                    "SELECT * FROM state_trace WHERE trace_id = ? ORDER BY seq, id",
                    (trace_id,),
                ).fetchall()
                sec = conn.execute(
                    "SELECT * FROM security_events WHERE trace_id = ? ORDER BY id",
                    (trace_id,),
                ).fetchall()
                evals = conn.execute(
                    "SELECT * FROM eval_samples WHERE trace_id = ? ORDER BY turn, id",
                    (trace_id,),
                ).fetchall()
            return {
                "turn": dict(turn_row),
                "llm_calls": [dict(r) for r in llm],
                "tool_calls": [dict(r) for r in tools],
                "state_trace": [dict(r) for r in states],
                "security_events": [dict(r) for r in sec],
                "eval_samples": [dict(r) for r in evals],
            }
        except Exception:
            logger.exception("[TraceStore] get_turn failed: %s", trace_id)
            return None

    def list_turns(self, session_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        """列出最近的 turn 汇总（可按 session 过滤），供概览/筛选。"""
        if not self.enabled:
            return []
        try:
            with self._connect() as conn:
                if session_id:
                    rows = conn.execute(
                        "SELECT * FROM turns WHERE session_id = ? "
                        "ORDER BY started_at DESC LIMIT ?",
                        (session_id, limit),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT * FROM turns ORDER BY started_at DESC LIMIT ?",
                        (limit,),
                    ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            logger.exception("[TraceStore] list_turns failed")
            return []

    def prune(self, keep_turns: int = _DEFAULT_KEEP_TURNS) -> None:
        """限容：只保留最近 keep_turns 个 turn，级联清掉其子记录。"""
        if not self.enabled:
            return
        try:
            with self._lock, self._connect() as conn:
                stale = conn.execute(
                    "SELECT trace_id FROM turns ORDER BY started_at DESC "
                    "LIMIT -1 OFFSET ?",
                    (keep_turns,),
                ).fetchall()
                if not stale:
                    return
                ids = [(r["trace_id"],) for r in stale]
                for table in (
                    "llm_calls", "tool_calls", "state_trace",
                    "security_events", "eval_samples", "turns",
                ):
                    conn.executemany(
                        f"DELETE FROM {table} WHERE trace_id = ?", ids
                    )
                conn.commit()
        except Exception:
            logger.exception("[TraceStore] prune failed")

    def list_security_events(self, limit: int = 200) -> list[dict[str, Any]]:
        """列出最近的安全审计事件（高风险工具调用 + 裁决），供安全概览。"""
        if not self.enabled:
            return []
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM security_events ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            logger.exception("[TraceStore] list_security_events failed")
            return []

    def list_eval_samples(self, limit: int = 200) -> list[dict[str, Any]]:
        """列出最近的评测样本，供离线打分/导出数据集。"""
        if not self.enabled:
            return []
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM eval_samples ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            logger.exception("[TraceStore] list_eval_samples failed")
            return []

    # ── 内部写入辅助 ────────────────────────────────────────────────────

    def _write(self, sql: str, params: tuple) -> None:
        try:
            with self._lock, self._connect() as conn:
                conn.execute(sql, params)
                conn.commit()
        except Exception:
            logger.exception("[TraceStore] write failed")

    def _writemany(self, sql: str, rows: list[tuple]) -> None:
        try:
            with self._lock, self._connect() as conn:
                conn.executemany(sql, rows)
                conn.commit()
        except Exception:
            logger.exception("[TraceStore] writemany failed")


# 敏感参数键名（工具入参里出现就打码），避免把 key/token 落进遥测库。
_SENSITIVE_KEYS = frozenset({
    "api_key", "apikey", "token", "password", "secret", "authorization",
})


def _redact_args(arguments: Any) -> Any:
    """对工具入参做浅层脱敏：命中敏感键名的值替换为掩码。

    同时剥掉 AgentLoop 注入的内部参数（_session_id 等），它们对回放无意义。
    """
    if not isinstance(arguments, dict):
        return arguments
    redacted: dict[str, Any] = {}
    for key, value in arguments.items():
        if isinstance(key, str) and key.startswith("_"):
            continue
        if isinstance(key, str) and key.lower() in _SENSITIVE_KEYS:
            redacted[key] = "***"
        else:
            redacted[key] = value
    return redacted
