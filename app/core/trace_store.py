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
from contextlib import closing, contextmanager
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.runtime_paths import DATA_DIR

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = DATA_DIR / "traces.db"

# 工具入参/结果可能含用户数据，回放需要看 I/O，但要防止超长记录撑爆库。
_MAX_FIELD_CHARS = 2000

# prune 默认保留的 trace 条数（按 started_at 倒序）。
_DEFAULT_KEEP_TRACES = 2000

# Schema 版本号：每次破坏性变更时递增
_SCHEMA_VERSION = 3  # Runtime observations are independent of evaluation tables.


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

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        # WAL：读写并发更友好（多线程写场景）；busy_timeout 兜底锁等待。
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=3000")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            existing = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
            version = self._get_schema_version(conn)
            if version > _SCHEMA_VERSION:
                raise RuntimeError("Trace database belongs to a newer application")
            if existing and version < _SCHEMA_VERSION:
                self._backup_database()
            conn.execute("BEGIN IMMEDIATE")
            if 'turns' in existing and 'traces' not in existing:
                conn.execute("ALTER TABLE turns RENAME TO traces")
            schema = """
                CREATE TABLE IF NOT EXISTS traces (
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
                    cost_usd      REAL,
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

                CREATE TABLE IF NOT EXISTS iteration_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trace_id TEXT NOT NULL, turn_index INTEGER NOT NULL,
                    answer TEXT, tool_count INTEGER NOT NULL DEFAULT 0,
                    error_count INTEGER NOT NULL DEFAULT 0, had_error INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL, legacy_source_id INTEGER UNIQUE
                );
                CREATE INDEX IF NOT EXISTS idx_traces_session ON traces(session_id);
                CREATE INDEX IF NOT EXISTS idx_traces_started ON traces(started_at DESC);
                CREATE INDEX IF NOT EXISTS idx_llm_trace ON llm_calls(trace_id);
                CREATE INDEX IF NOT EXISTS idx_tool_trace ON tool_calls(trace_id);
                CREATE INDEX IF NOT EXISTS idx_state_trace ON state_trace(trace_id);
                CREATE INDEX IF NOT EXISTS idx_sec_trace ON security_events(trace_id);
                CREATE INDEX IF NOT EXISTS idx_iteration_trace ON iteration_records(trace_id);
            """
            for statement in schema.split(';'):
                if statement.strip():
                    conn.execute(statement)
            self._migrate_v1_token_columns(conn)
            columns = {r[1] for r in conn.execute("PRAGMA table_info(traces)")}
            for name in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
                if name not in columns:
                    conn.execute(f"ALTER TABLE traces ADD COLUMN {name} INTEGER NOT NULL DEFAULT 0")
            columns = {r[1] for r in conn.execute("PRAGMA table_info(llm_calls)")}
            for name, kind in [('attempt_id', 'TEXT'), ('pricing_source', 'TEXT'), ('pricing_version', 'TEXT')]:
                if name not in columns:
                    conn.execute(f"ALTER TABLE llm_calls ADD COLUMN {name} {kind}")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_llm_attempt ON llm_calls(attempt_id) WHERE attempt_id IS NOT NULL")
            if version < 3 and 'eval_samples' in existing:
                cols = {r[1] for r in conn.execute("PRAGMA table_info(eval_samples)")}
                ident = 'eval_sample_id' if 'eval_sample_id' in cols else 'id'
                turn = 'turn_index' if 'turn_index' in cols else 'turn'
                conn.execute(f"""INSERT OR IGNORE INTO iteration_records
                    (trace_id, turn_index, answer, tool_count, error_count, had_error, created_at, legacy_source_id)
                    SELECT trace_id, {turn}, answer, tool_count, error_count, had_error, created_at, {ident}
                    FROM eval_samples""")
                source_count = conn.execute("SELECT COUNT(*) FROM eval_samples").fetchone()[0]
                copied = conn.execute("SELECT COUNT(*) FROM iteration_records WHERE legacy_source_id IS NOT NULL").fetchone()[0]
                if copied != source_count:
                    raise RuntimeError("Legacy iteration copy count mismatch")
            self._set_schema_version(conn, _SCHEMA_VERSION)

    @staticmethod
    def _get_schema_version(conn: sqlite3.Connection) -> int:
        """获取当前 schema 版本号。"""
        try:
            row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
            return row[0] if row[0] is not None else 0
        except Exception:
            return 0

    @staticmethod
    def _set_schema_version(conn: sqlite3.Connection, version: int) -> None:
        """记录新的 schema 版本。"""
        conn.execute(
            "INSERT OR REPLACE INTO schema_version (version, applied_at) VALUES (?, ?)",
            (version, _now_iso()),
        )

    def _backup_database(self) -> None:
        backup_path = self._path.with_suffix(f".backup.{time.time_ns()}.db")
        with closing(sqlite3.connect(self._path)) as source, closing(sqlite3.connect(backup_path)) as target:
            source.backup(target)

    @staticmethod
    def _migrate_v1_token_columns(conn: sqlite3.Connection) -> None:
        """V1: 补充 token 统计列（兼容旧版本）。"""
        new_cols = {
            "traces": [
                ("prompt_tokens", "INTEGER NOT NULL DEFAULT 0"),
                ("completion_tokens", "INTEGER NOT NULL DEFAULT 0"),
                ("total_tokens", "INTEGER NOT NULL DEFAULT 0"),
            ],
            "llm_calls": [
                ("prompt_tokens", "INTEGER"),
                ("completion_tokens", "INTEGER"),
                ("total_tokens", "INTEGER"),
                ("cached_tokens", "INTEGER"),
                ("cost_usd", "REAL"),
            ],
        }
        for table, cols in new_cols.items():
            existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            for name, decl in cols:
                if name not in existing:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")

    # ── 写入接口（异常安全） ─────────────────────────────────────────────

    def start_trace(self, trace_id: str, session_id: str = "") -> None:
        """开始记录一次 Agent Trace。"""
        if not self.enabled:
            return
        # 优先使用 traces 表，如果不存在则回退到 turns（迁移兼容）
        table = "traces" if self._table_exists("traces") else "turns"
        self._write(
            f"INSERT OR REPLACE INTO {table} "
            "(trace_id, session_id, started_at, status) VALUES (?, ?, ?, 'running')",
            (trace_id, session_id or None, _now_iso()),
        )

    def finish_trace(
        self,
        trace_id: str,
        *,
        status: str,
        turn_count: int = 0,
        duration_ms: float | None = None,
        error: str | None = None,
    ) -> None:
        """完成一次 Agent Trace，并从已落库的 llm_calls 汇总 token 用量。"""
        if not self.enabled:
            return
        table = "traces" if self._table_exists("traces") else "turns"
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
                    f"UPDATE {table} SET ended_at = ?, status = ?, turn_count = ?, "
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
            logger.exception("[TraceStore] finish_trace failed")

    def record_llm_call(self, trace_id: str, seq: int, record: dict[str, Any]) -> None:
        """记录一次 LLM attempt 汇总（与网关 _write_log 同源字段）。"""
        if not self.enabled:
            return
        usage = record.get("usage") or {}

        # 计算成本
        cost_usd = None
        pricing_source = pricing_version = None
        provider = record.get("provider")
        model = record.get("model")
        if provider and model and usage:
            try:
                from app.core.cost_calculator import calculate_cost_from_usage, pricing_snapshot
                cost_usd = calculate_cost_from_usage(
                    provider=provider,
                    model=model,
                    usage=usage,
                )
                if cost_usd is not None:
                    pricing_source, pricing_version = pricing_snapshot(provider, model)
            except Exception as e:
                logger.debug(f"[TraceStore] Cost calculation failed: {e}")

        self._write(
            "INSERT OR IGNORE INTO llm_calls (trace_id, seq, api_type, provider, model, "
            "has_tools, input_message_count, ttft_ms, latency_ms, retry_count, "
            "status, error_type, error_kind, error_status_code, error_message, "
            "prompt_tokens, completion_tokens, total_tokens, cached_tokens, cost_usd, "
            "created_at, attempt_id, pricing_source, pricing_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
            "?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                cost_usd,
                _now_iso(),
                record.get("attempt_id"),
                record.get("pricing_source") or pricing_source,
                record.get("pricing_version") or pricing_version,
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

    def record_iteration(self, trace_id: str, *, turn: int, answer: str | None,
                         tool_count: int, error_count: int, had_error: bool) -> None:
        if not self.enabled:
            return
        self._write("INSERT INTO iteration_records (trace_id, turn_index, answer, tool_count, error_count, had_error, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (trace_id, turn, _truncate(answer), tool_count, error_count, int(had_error), _now_iso()))

    def get_trace(self, trace_id: str) -> dict[str, Any] | None:
        """按 trace_id 重组一次完整 Trace，供回放使用。"""
        if not self.enabled:
            return None
        try:
            table = "traces" if self._table_exists("traces") else "turns"
            with self._connect() as conn:
                trace_row = conn.execute(
                    f"SELECT * FROM {table} WHERE trace_id = ?", (trace_id,)
                ).fetchone()
                if trace_row is None:
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
                iterations = conn.execute(
                    "SELECT * FROM iteration_records WHERE trace_id = ? ORDER BY turn_index, id", (trace_id,)
                ).fetchall()
            return {
                "trace": dict(trace_row),
                "llm_calls": [dict(r) for r in llm],
                "tool_calls": [dict(r) for r in tools],
                "state_trace": [dict(r) for r in states],
                "security_events": [dict(r) for r in sec],
                "iterations": [dict(r) for r in iterations],
                "cost": self.summarize_cost([dict(r) for r in llm]),
            }
        except Exception:
            logger.exception("[TraceStore] get_trace failed: %s", trace_id)
            return None

    def list_traces(self, session_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        """列出最近的 Trace 汇总（可按 session 过滤），供概览/筛选。"""
        if not self.enabled:
            return []
        try:
            table = "traces" if self._table_exists("traces") else "turns"
            with self._connect() as conn:
                if session_id:
                    rows = conn.execute(
                        f"SELECT * FROM {table} WHERE session_id = ? "
                        "ORDER BY started_at DESC LIMIT ?",
                        (session_id, limit),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        f"SELECT * FROM {table} ORDER BY started_at DESC LIMIT ?",
                        (limit,),
                    ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            logger.exception("[TraceStore] list_traces failed")
            return []

    def prune(self, keep_traces: int = _DEFAULT_KEEP_TRACES) -> None:
        """限容：只保留最近 keep_traces 个 Trace，级联清掉其子记录。"""
        if not self.enabled:
            return
        try:
            table = "traces" if self._table_exists("traces") else "turns"
            with self._lock, self._connect() as conn:
                stale = conn.execute(
                    f"SELECT trace_id FROM {table} ORDER BY started_at DESC "
                    "LIMIT -1 OFFSET ?",
                    (keep_traces,),
                ).fetchall()
                if not stale:
                    return
                ids = [(r["trace_id"],) for r in stale]
                for tbl in (
                    "llm_calls", "tool_calls", "state_trace",
                    "security_events", "iteration_records", table,
                ):
                    conn.executemany(
                        f"DELETE FROM {tbl} WHERE trace_id = ?", ids
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

    @staticmethod
    def summarize_cost(calls):
        known = [c['cost_usd'] for c in calls if c.get('cost_usd') is not None]
        return {"known_cost_usd": sum(known), "unknown_calls": len(calls) - len(known),
                "complete": bool(calls) and len(known) == len(calls),
                "scope": "Only LLM attempts linked to this trace; provider charges may differ."}

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

    def _table_exists(self, table_name: str) -> bool:
        """检查表是否存在。"""
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (table_name,),
                ).fetchone()
                return row is not None
        except Exception:
            return False

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
