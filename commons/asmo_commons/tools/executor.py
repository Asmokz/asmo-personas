"""Secure command executor with strict whitelist and timeout.

Only read-only, non-destructive commands are allowed.
No shell=True, no arbitrary command injection possible.
"""
from __future__ import annotations

import asyncio
import shlex
from typing import Optional

import structlog

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Whitelist definitions
# ---------------------------------------------------------------------------

#: Top-level commands that may be executed.
ALLOWED_COMMANDS: frozenset[str] = frozenset(
    [
        "df",
        "free",
        "uptime",
        "mpstat",
        "iostat",
        "vmstat",
        "ps",
        "docker",
        "ip",
        "ss",
        "uname",
        "smartctl",  # read-only SMART queries only (see validation below)
        "cat",  # restricted to /proc and /sys below
    ]
)

#: smartctl flags that would initiate a disk test or modify device settings.
_BLOCKED_SMARTCTL_FLAGS: frozenset[str] = frozenset(["-t", "--test", "-s", "--set", "-X", "--abort"])

#: docker sub-commands that are read-only.
ALLOWED_DOCKER_SUBCOMMANDS: frozenset[str] = frozenset(
    [
        "ps",
        "stats",
        "logs",
        "inspect",
        "images",
        "info",
        "version",
        "top",
    ]
)


class ExecutorError(Exception):
    """Raised when a command fails security checks or execution."""


class CommandExecutor:
    """Execute whitelisted system commands asynchronously.

    All commands are executed without ``shell=True``.  Arguments must be
    passed as a pre-split list — never concatenate user input into the list.
    """

    def __init__(self, default_timeout: int = 10) -> None:
        self.default_timeout = default_timeout

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate(self, cmd: list[str]) -> None:
        if not cmd:
            raise ExecutorError("Empty command")

        base = cmd[0]
        if base not in ALLOWED_COMMANDS:
            raise ExecutorError(
                f"Command '{base}' is not in the whitelist. "
                f"Allowed: {sorted(ALLOWED_COMMANDS)}"
            )

        if base == "docker":
            subcmd = cmd[1] if len(cmd) > 1 else ""
            if subcmd not in ALLOWED_DOCKER_SUBCOMMANDS:
                raise ExecutorError(
                    f"Docker sub-command '{subcmd}' is not allowed. "
                    f"Allowed: {sorted(ALLOWED_DOCKER_SUBCOMMANDS)}"
                )

        if base == "smartctl":
            blocked = [a for a in cmd[1:] if a in _BLOCKED_SMARTCTL_FLAGS]
            if blocked:
                raise ExecutorError(
                    f"smartctl flag(s) {blocked} are not allowed (disk tests/writes are disabled)."
                )

        if base == "cat":
            for arg in cmd[1:]:
                if not (arg.startswith("/proc/") or arg.startswith("/sys/")):
                    raise ExecutorError(
                        "cat is only allowed for /proc/ and /sys/ paths, "
                        f"got: {arg}"
                    )

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def run(
        self,
        cmd: list[str],
        timeout: Optional[int] = None,
        stdin: Optional[str] = None,
    ) -> str:
        """Run a whitelisted command and return its stdout.

        Args:
            cmd: Pre-split command list.  Do **not** pass shell strings.
            timeout: Override the default timeout (seconds).
            stdin: Optional string to feed to the process stdin.

        Returns:
            stdout as a UTF-8 string (stderr included on non-zero exit).

        Raises:
            ExecutorError: On security violation, timeout, or missing binary.
        """
        self._validate(cmd)
        effective_timeout = timeout if timeout is not None else self.default_timeout
        cmd_str = shlex.join(cmd)

        logger.info("executor_run", command=cmd_str, timeout=effective_timeout)

        try:
            stdin_bytes = stdin.encode() if stdin else None
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.PIPE if stdin_bytes else None,
            )
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(input=stdin_bytes),
                timeout=effective_timeout,
            )

            stdout = stdout_b.decode("utf-8", errors="replace").strip()
            stderr = stderr_b.decode("utf-8", errors="replace").strip()

            if proc.returncode != 0:
                logger.warning(
                    "executor_nonzero_exit",
                    command=cmd_str,
                    returncode=proc.returncode,
                    stderr=stderr[:200],
                )
                return stdout or f"Exit {proc.returncode}: {stderr[:400]}"

            logger.debug("executor_success", command=cmd_str, output_len=len(stdout))
            return stdout

        except asyncio.TimeoutError:
            logger.error("executor_timeout", command=cmd_str, timeout=effective_timeout)
            raise ExecutorError(
                f"Command timed out after {effective_timeout}s: {cmd_str}"
            )
        except FileNotFoundError as exc:
            raise ExecutorError(f"Binary not found: {cmd[0]}") from exc
