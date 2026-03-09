"""Causality SQLite manager — exchanges table with rolling cleanup."""
from __future__ import annotations

import json
import time
from typing import Any

import aiosqlite
import structlog

logger = structlog.get_logger()


class DbManager:
    def __init__(self, path: str) -> None:
        self._path = path
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        self._db = await aiosqlite.connect(self._path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS exchanges (
                id                TEXT PRIMARY KEY,
                conv_id           TEXT,
                persona           TEXT NOT NULL,
                model             TEXT NOT NULL,
                started_at        REAL NOT NULL,
                ended_at          REAL,
                duration_ms       INTEGER,
                prompt_tokens     INTEGER,
                completion_tokens INTEGER,
                tokens_per_sec    REAL,
                load_duration_ms  INTEGER,
                request_messages  TEXT,
                request_tool_names TEXT,
                response          TEXT,
                hw_before         TEXT,
                hw_after          TEXT
            )
        """)
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_started ON exchanges(started_at DESC)"
        )
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_persona ON exchanges(persona)"
        )
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS analyses (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at REAL NOT NULL,
                report     TEXT NOT NULL
            )
        """)
        await self._db.commit()

    async def cleanup_old(self, retention_days: int) -> None:
        threshold = time.time() - retention_days * 86400
        async with self._db.execute(
            "DELETE FROM exchanges WHERE started_at < ?", (threshold,)
        ) as cur:
            deleted = cur.rowcount
        await self._db.commit()
        if deleted:
            logger.info("causality_cleanup", deleted=deleted, retention_days=retention_days)

    async def insert_call_start(self, data: dict, hw_before: dict) -> None:
        await self._db.execute(
            """
            INSERT OR IGNORE INTO exchanges
              (id, conv_id, persona, model, started_at, request_messages,
               request_tool_names, hw_before)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data["call_id"],
                data.get("conv_id"),
                data["persona"],
                data["model"],
                data["ts_start"],
                json.dumps(data.get("messages", []), ensure_ascii=False),
                json.dumps(data.get("tool_names", []), ensure_ascii=False),
                json.dumps(hw_before, ensure_ascii=False),
            ),
        )
        await self._db.commit()

    async def update_call_end(self, data: dict, hw_after: dict) -> None:
        await self._db.execute(
            """
            UPDATE exchanges SET
                ended_at          = ?,
                duration_ms       = ?,
                prompt_tokens     = ?,
                completion_tokens = ?,
                tokens_per_sec    = ?,
                load_duration_ms  = ?,
                response          = ?,
                hw_after          = ?
            WHERE id = ?
            """,
            (
                data["ts_end"],
                data["duration_ms"],
                data.get("prompt_tokens"),
                data.get("completion_tokens"),
                data.get("tokens_per_sec"),
                data.get("load_duration_ms"),
                json.dumps(data.get("response", {}), ensure_ascii=False),
                json.dumps(hw_after, ensure_ascii=False),
                data["call_id"],
            ),
        )
        await self._db.commit()

    async def list_exchanges(
        self,
        limit: int,
        offset: int,
        persona: str | None,
    ) -> list[dict]:
        query = "SELECT * FROM exchanges"
        params: list[Any] = []
        if persona:
            query += " WHERE persona = ?"
            params.append(persona)
        query += " ORDER BY started_at DESC LIMIT ? OFFSET ?"
        params += [limit, offset]

        async with self._db.execute(query, params) as cur:
            rows = await cur.fetchall()

        result = []
        json_fields = (
            "request_messages", "request_tool_names",
            "response", "hw_before", "hw_after",
        )
        for row in rows:
            d = dict(row)
            for field in json_fields:
                if d.get(field):
                    try:
                        d[field] = json.loads(d[field])
                    except Exception:
                        pass
            result.append(d)
        return result

    async def get_metrics_window(self, hours: float) -> dict:
        """Compute aggregate metrics for exchanges started in the last `hours` hours."""
        import json as _json
        from collections import defaultdict
        since = time.time() - hours * 3600

        async with self._db.execute(
            "SELECT * FROM exchanges WHERE started_at >= ?", (since,)
        ) as cur:
            rows = [dict(r) for r in await cur.fetchall()]

        if not rows:
            return {"call_count": 0, "conv_count": 0}

        # Group by conv_id (exclude calls with no conv_id)
        convs: dict = defaultdict(list)
        tok_s_vals: list[float] = []

        for row in rows:
            if row.get("conv_id"):
                convs[row["conv_id"]].append(row)
            if row.get("tokens_per_sec"):
                tok_s_vals.append(row["tokens_per_sec"])

        conv_count = len(convs)
        unfinished = 0
        long_convs = 0
        total_turns = 0

        for calls in convs.values():
            n = len(calls)
            total_turns += n
            if n >= 6:
                long_convs += 1
            last = sorted(calls, key=lambda x: x.get("started_at", 0))[-1]
            try:
                resp = _json.loads(last.get("response") or "{}")
                content = (resp.get("content") or "").strip()
                if not content:
                    unfinished += 1
            except Exception:
                unfinished += 1

        tool_ok = tool_fail = 0
        for row in rows:
            try:
                msgs = _json.loads(row.get("request_messages") or "[]")
                for m in msgs:
                    if m.get("role") == "tool":
                        c = m.get("content", "")
                        if (c.startswith("❌") or "Erreur" in c
                                or "indisponible" in c.lower()):
                            tool_fail += 1
                        else:
                            tool_ok += 1
            except Exception:
                pass

        tool_total = tool_ok + tool_fail
        return {
            "call_count": len(rows),
            "conv_count": conv_count,
            "tok_s_avg": round(sum(tok_s_vals) / len(tok_s_vals), 1) if tok_s_vals else None,
            "avg_turns": round(total_turns / conv_count, 2) if conv_count else None,
            "unfinished_rate": round(unfinished / conv_count, 3) if conv_count else None,
            "long_conv_rate": round(long_convs / conv_count, 3) if conv_count else None,
            "tool_ok": tool_ok,
            "tool_fail": tool_fail,
            "tool_fail_rate": round(tool_fail / tool_total, 3) if tool_total else None,
        }

    async def get_failure_patterns(self, days: int = 7) -> dict:
        """Return structured failure patterns for LLM analysis."""
        import json as _json
        from collections import defaultdict
        since = time.time() - days * 86400
        mid = since + (days / 2) * 86400

        async with self._db.execute(
            "SELECT * FROM exchanges WHERE started_at >= ? ORDER BY started_at",
            (since,),
        ) as cur:
            rows = [dict(r) for r in await cur.fetchall()]

        if not rows:
            return {"total_calls": 0, "total_convs": 0}

        # --- per-persona stats ---
        by_persona: dict = defaultdict(list)
        for row in rows:
            key = f"{row['persona']}|{row['model']}"
            by_persona[key].append(row)

        per_persona = []
        for key, prws in by_persona.items():
            persona, model = key.split("|", 1)
            convs_p: dict = defaultdict(list)
            tok_s_p: list[float] = []
            for r in prws:
                if r.get("conv_id"):
                    convs_p[r["conv_id"]].append(r)
                if r.get("tokens_per_sec"):
                    tok_s_p.append(r["tokens_per_sec"])
            unf = long_c = total_t = 0
            for calls in convs_p.values():
                n = len(calls)
                total_t += n
                if n >= 6:
                    long_c += 1
                last = sorted(calls, key=lambda x: x.get("started_at", 0))[-1]
                try:
                    resp = _json.loads(last.get("response") or "{}")
                    if not (resp.get("content") or "").strip():
                        unf += 1
                except Exception:
                    unf += 1
            cc = len(convs_p)
            per_persona.append({
                "persona": persona,
                "model": model,
                "calls": len(prws),
                "conv_count": cc,
                "unfinished_rate": round(unf / cc, 3) if cc else 0.0,
                "avg_turns": round(total_t / cc, 2) if cc else 0.0,
                "long_conv_pct": round(long_c / cc, 3) if cc else 0.0,
                "tok_s": round(sum(tok_s_p) / len(tok_s_p), 1) if tok_s_p else 0.0,
            })

        # --- tool failure rates ---
        tool_stats: dict = defaultdict(lambda: {"ok": 0, "fail": 0})
        for row in rows:
            try:
                msgs = _json.loads(row.get("request_messages") or "[]")
                # The tool name is in the assistant message's tool_calls
                resp = _json.loads(row.get("response") or "{}")
                called_tools = [
                    tc.get("function", {}).get("name", "unknown")
                    for tc in (resp.get("tool_calls") or [])
                ]
                for m in msgs:
                    if m.get("role") == "tool":
                        # Match to a called tool if we can
                        tool_name = called_tools[0] if called_tools else "unknown"
                        c = m.get("content", "")
                        if (c.startswith("❌") or "Erreur" in c
                                or "indisponible" in c.lower()):
                            tool_stats[tool_name]["fail"] += 1
                        else:
                            tool_stats[tool_name]["ok"] += 1
            except Exception:
                pass

        tool_failures = []
        for tool, stats in sorted(tool_stats.items()):
            total = stats["ok"] + stats["fail"]
            if total >= 3:
                tool_failures.append({
                    "tool": tool,
                    "ok": stats["ok"],
                    "fail": stats["fail"],
                    "total": total,
                    "rate": round(stats["fail"] / total, 3),
                })
        tool_failures.sort(key=lambda x: x["rate"], reverse=True)

        # --- loop correlations: tool sequences in long convs ---
        all_convs: dict = defaultdict(list)
        for row in rows:
            if row.get("conv_id"):
                all_convs[row["conv_id"]].append(row)

        # For each conv, collect the tools actually called (from response.tool_calls)
        combo_stats: dict = defaultdict(lambda: {"total": 0, "loop": 0})
        for calls in all_convs.values():
            tools_in_conv: list[str] = []
            for r in calls:
                try:
                    resp = _json.loads(r.get("response") or "{}")
                    for tc in (resp.get("tool_calls") or []):
                        name = tc.get("function", {}).get("name")
                        if name and name not in tools_in_conv:
                            tools_in_conv.append(name)
                except Exception:
                    pass
            if tools_in_conv:
                key = ",".join(sorted(tools_in_conv))
                combo_stats[key]["total"] += 1
                if len(calls) >= 6:
                    combo_stats[key]["loop"] += 1

        loop_correlations = []
        for combo_key, s in combo_stats.items():
            if s["total"] >= 2 and s["loop"] > 0:
                loop_correlations.append({
                    "tools": combo_key.split(","),
                    "total": s["total"],
                    "loop_count": s["loop"],
                })
        loop_correlations.sort(key=lambda x: x["loop_count"], reverse=True)

        # --- temporal trend (first half vs second half) ---
        first_rows = [r for r in rows if r["started_at"] < mid]
        second_rows = [r for r in rows if r["started_at"] >= mid]

        def _quick_rate(rws: list) -> dict:
            convs_q: dict = defaultdict(list)
            toks: list[float] = []
            for r in rws:
                if r.get("conv_id"):
                    convs_q[r["conv_id"]].append(r)
                if r.get("tokens_per_sec"):
                    toks.append(r["tokens_per_sec"])
            unf = 0
            for calls in convs_q.values():
                last = sorted(calls, key=lambda x: x.get("started_at", 0))[-1]
                try:
                    resp = _json.loads(last.get("response") or "{}")
                    if not (resp.get("content") or "").strip():
                        unf += 1
                except Exception:
                    unf += 1
            cc = len(convs_q)
            return {
                "unfinished": round(unf / cc, 3) if cc else 0.0,
                "tok_s": round(sum(toks) / len(toks), 1) if toks else 0.0,
            }

        first_stats = _quick_rate(first_rows)
        second_stats = _quick_rate(second_rows)

        return {
            "total_calls": len(rows),
            "total_convs": len(all_convs),
            "per_persona": per_persona,
            "tool_failures": tool_failures,
            "loop_correlations": loop_correlations[:5],
            "trend": {
                "unfinished_first": first_stats["unfinished"],
                "unfinished_second": second_stats["unfinished"],
                "tok_s_first": first_stats["tok_s"],
                "tok_s_second": second_stats["tok_s"],
            },
        }

    async def save_analysis(self, report: str) -> None:
        """Persist a PatternAnalyzer report."""
        await self._db.execute(
            "INSERT INTO analyses (created_at, report) VALUES (?, ?)",
            (time.time(), report),
        )
        await self._db.commit()

    async def get_latest_analysis(self) -> dict | None:
        """Return the most recent PatternAnalyzer report, or None."""
        async with self._db.execute(
            "SELECT created_at, report FROM analyses ORDER BY created_at DESC LIMIT 1"
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        return {"created_at": row["created_at"], "report": row["report"]}

    async def close(self) -> None:
        if self._db:
            await self._db.close()
