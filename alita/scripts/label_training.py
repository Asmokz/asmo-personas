#!/usr/bin/env python3
"""Interactive labeller for the Alita training dataset.

Usage:
    python scripts/label_training.py [DB_PATH]

    DB_PATH defaults to /data/alita_training.db

Via Docker (recommended):
    docker exec -it asmo-alita python /app/scripts/label_training.py

Keys during review:
    g        → good  (SFT candidate)
    b        → bad   (prompts for a correction → DPO pair)
    s        → skip  (leave unlabelled, come back later)
    d        → detail (show full conversation, then re-prompt)
    q        → quit
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import textwrap
from datetime import datetime

# ── Config ──────────────────────────────────────────────────────────────────
DEFAULT_DB = "/data/alita_training.db"
PREVIEW_LEN = 280      # chars shown for user/assistant turns in list view
TOOL_SUMMARY = True    # show tool call names instead of full JSON

# ── ANSI colours (disabled automatically when not a tty) ────────────────────
_TTY = sys.stdout.isatty()

def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _TTY else text

def green(t: str) -> str:  return _c("32", t)
def red(t: str) -> str:    return _c("31", t)
def yellow(t: str) -> str: return _c("33", t)
def bold(t: str) -> str:   return _c("1",  t)
def dim(t: str) -> str:    return _c("2",  t)
def cyan(t: str) -> str:   return _c("36", t)


# ── Database helpers ─────────────────────────────────────────────────────────

def open_db(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con


def fetch_stats(con: sqlite3.Connection) -> dict:
    cur = con.execute(
        "SELECT quality, COUNT(*) AS n FROM training_log GROUP BY quality"
    )
    rows = cur.fetchall()
    stats = {"unlabelled": 0, "good": 0, "bad": 0}
    for r in rows:
        key = r["quality"] or "unlabelled"
        stats[key] = r["n"]
    return stats


def fetch_unlabelled(con: sqlite3.Connection) -> list[sqlite3.Row]:
    cur = con.execute(
        "SELECT * FROM training_log WHERE quality IS NULL ORDER BY timestamp ASC"
    )
    return cur.fetchall()


def set_quality(
    con: sqlite3.Connection,
    row_id: str,
    quality: str,
    correction: str | None = None,
) -> None:
    con.execute(
        "UPDATE training_log SET quality=?, correction=? WHERE id=?",
        (quality, correction, row_id),
    )
    con.commit()


# ── Context prefix stripping ─────────────────────────────────────────────────
# The stored user message contains injected blocks prepended by _get_context_prefix:
#   [Souvenirs pertinents...][Fin des souvenirs]
#   [Contenu récupéré depuis url]...[Fin du contenu]
#   [RAPPEL OUTIL : ...]
# In preview mode we strip these so only the raw user question is shown.

_INJECTED_BLOCK_RE = re.compile(
    r"\[Souvenirs pertinents.*?\[Fin des souvenirs\]\n*"
    r"|\[Contenu récupéré depuis.*?\[Fin du contenu\]\n*"
    r"|\[RAPPEL OUTIL[^\]]*\]\n*",
    re.DOTALL,
)


def _raw_user_message(content: str) -> tuple[str, bool]:
    """Return (raw_question, had_context).

    Strips injected context blocks, leaving only what the user actually typed.
    had_context=True signals that context was present (shown as a hint in preview).
    """
    stripped = _INJECTED_BLOCK_RE.sub("", content).strip()
    had_context = stripped != content.strip()
    return (stripped or content.strip(), had_context)


# ── Formatting ───────────────────────────────────────────────────────────────

def _wrap(text: str, width: int = 100, indent: str = "    ") -> str:
    lines = []
    for paragraph in text.splitlines():
        if paragraph.strip() == "":
            lines.append("")
        else:
            lines.extend(
                textwrap.wrap(paragraph, width=width - len(indent),
                              subsequent_indent=indent)
            )
    return "\n".join(f"{indent}{l}" if l else "" for l in lines)


def _format_messages(messages: list[dict], full: bool = False) -> str:
    lines = []
    first_user = True
    for msg in messages:
        role = msg.get("role", "?")
        content = (msg.get("content") or "").strip()
        tool_calls = msg.get("tool_calls")

        if role == "user":
            prefix = bold(cyan("► User"))
            if not full and first_user:
                # Strip injected context (LTM, URL fetch, tool reminders)
                # so the reviewer sees the actual question, not the augmented input.
                raw, had_context = _raw_user_message(content)
                hint = f" {dim('[+ contexte LTM/URL]')}" if had_context else ""
                text = raw[:PREVIEW_LEN] + ("…" if len(raw) > PREVIEW_LEN else "")
                lines.append(f"\n{prefix}{hint}\n{_wrap(text)}")
            else:
                text = content if full else content[:PREVIEW_LEN] + ("…" if len(content) > PREVIEW_LEN else "")
                lines.append(f"\n{prefix}\n{_wrap(text)}")
            first_user = False

        elif role == "assistant":
            prefix = bold(green("◆ Alita"))
            if tool_calls and TOOL_SUMMARY:
                names = [tc.get("function", {}).get("name", "?") for tc in tool_calls]
                lines.append(f"\n{prefix} {dim('[appelle: ' + ', '.join(names) + ']')}")
            if content:
                text = content[:PREVIEW_LEN] + ("…" if not full and len(content) > PREVIEW_LEN else "") if not full else content
                lines.append(f"\n{prefix}\n{_wrap(text)}")

        elif role == "tool":
            if full:
                tool_content = (msg.get("content") or "")[:400]
                lines.append(f"\n{dim('◇ Tool result')}\n{_wrap(dim(tool_content))}")
            # skip tool results in preview mode

    return "\n".join(lines)


def _format_header(row: sqlite3.Row, index: int, total: int) -> str:
    meta = json.loads(row["meta"])
    ts = row["timestamp"][:19].replace("T", " ")
    tools = meta.get("tools_called") or []
    tools_str = ", ".join(tools) if tools else dim("aucun")
    turns = meta.get("turns", "?")
    ms = meta.get("total_ms", "?")
    reply_len = meta.get("reply_len", "?")

    return (
        f"\n{'─' * 80}\n"
        f"  {bold(f'[{index}/{total}]')}  {dim(ts)}  "
        f"turns={cyan(str(turns))}  "
        f"tools={cyan(tools_str)}  "
        f"reply={cyan(str(reply_len))} chars  "
        f"{dim(str(ms) + 'ms')}\n"
        f"  conv_id: {dim(row['conv_id'])}\n"
        f"{'─' * 80}"
    )


def _prompt_correction() -> str | None:
    print(
        f"\n{yellow('Correction (ce que la réponse aurait dû être).')}\n"
        "Tape la correction et appuie sur Entrée (laisser vide pour aucune correction) :"
    )
    lines = []
    try:
        while True:
            line = input()
            if line == "":
                if lines:
                    break
                # empty first line = no correction
                return None
            lines.append(line)
    except EOFError:
        pass
    return "\n".join(lines) or None


# ── Main loop ────────────────────────────────────────────────────────────────

def run(db_path: str) -> None:
    con = open_db(db_path)

    stats = fetch_stats(con)
    print(
        f"\n{bold('Alita Training Labeller')}\n"
        f"DB : {dim(db_path)}\n"
        f"Stats : {green(str(stats['good']))} good  "
        f"{red(str(stats['bad']))} bad  "
        f"{yellow(str(stats['unlabelled']))} unlabelled\n"
    )

    rows = fetch_unlabelled(con)
    if not rows:
        print(yellow("Aucun échange non noté. À bientôt !"))
        return

    total = len(rows)
    labelled = 0

    for i, row in enumerate(rows, start=1):
        messages = json.loads(row["messages"])

        print(_format_header(row, i, total))
        print(_format_messages(messages, full=False))

        while True:
            prompt = (
                f"\n  {bold('[g]')}ood  {bold('[b]')}ad  "
                f"{bold('[s]')}kip  {bold('[d]')}etail  {bold('[q]')}uit  › "
            )
            try:
                choice = input(prompt).strip().lower()
            except (EOFError, KeyboardInterrupt):
                choice = "q"

            if choice == "g":
                set_quality(con, row["id"], "good")
                print(f"  {green('✓ good')}")
                labelled += 1
                break

            elif choice == "b":
                correction = _prompt_correction()
                set_quality(con, row["id"], "bad", correction)
                corr_note = green("+ correction") if correction else dim("sans correction")
                print(f"  {red('✗ bad')}  {corr_note}")
                labelled += 1
                break

            elif choice == "s":
                print(f"  {dim('→ skipped')}")
                break

            elif choice == "d":
                print(_format_messages(messages, full=True))
                # loop back to re-prompt

            elif choice == "q":
                print(f"\n{bold('Session terminée.')} {labelled} échange(s) notés.\n")
                con.close()
                sys.exit(0)

            else:
                print(f"  {dim('Touche inconnue. g / b / s / d / q')}")

    print(
        f"\n{bold('Tous les échanges passés en revue.')} "
        f"{labelled}/{total} notés.\n"
    )
    stats = fetch_stats(con)
    print(
        f"Total : {green(str(stats['good']))} good  "
        f"{red(str(stats['bad']))} bad  "
        f"{yellow(str(stats['unlabelled']))} unlabelled\n"
    )
    con.close()


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DB
    run(path)
