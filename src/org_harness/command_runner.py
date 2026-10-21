"""Linux command supervisor with durable identity and completion records.

This module deliberately uses only the standard library: it also runs as an
independent process after a harness worker exits. User commands start only after
their process identity is durably recorded. Recovery signals exact pidfds, never
an unverified PID or a process group whose leader may have been replaced.
"""

from __future__ import annotations

import ctypes
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(value, handle, ensure_ascii=True, allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        temporary.replace(path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def process_identity(pid: int) -> dict[str, Any] | None:
    """Read Linux start time as well as PID; a recycled PID is a different process."""
    try:
        text = Path(f"/proc/{pid}/stat").read_text()
        fields = text[text.rindex(")") + 2 :].split()
        return {
            "pid": pid,
            "ppid": int(fields[1]),
            "start_ticks": int(fields[19]),
            "pgid": int(fields[2]),
            "session": int(fields[3]),
            "uid": Path(f"/proc/{pid}").stat().st_uid,
            "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
            "state": fields[0],
        }
    except (FileNotFoundError, ProcessLookupError):
        return None


def same_process(expected: dict, actual: dict | None) -> bool:
    return (
        isinstance(expected, dict)
        and isinstance(actual, dict)
        and all(
            expected.get(key) == actual.get(key)
            for key in ("pid", "start_ticks", "pgid", "session", "uid", "boot_id")
        )
    )


def signal_process(identity: dict, sig: int) -> bool:
    """Pin a process before checking its identity and sending a signal."""
    pid = identity.get("pid")
    if not isinstance(pid, int) or pid <= 1:
        return False
    try:
        descriptor = os.pidfd_open(pid)
    except ProcessLookupError:
        return False
    try:
        if not same_process(identity, process_identity(pid)):
            return False
        signal.pidfd_send_signal(descriptor, sig)
        return True
    except ProcessLookupError:
        return False
    finally:
        os.close(descriptor)


def session_children(identity: dict) -> list[dict]:
    # The verified live leader reserves this session identity. Never infer
    # ownership from a session number after its leader has disappeared/recycled.
    if not same_process(identity, process_identity(identity["pid"])):
        return []
    candidates = {}
    for name in os.listdir("/proc"):
        if not name.isdecimal() or int(name) == identity["pid"]:
            continue
        candidate = process_identity(int(name))
        if candidate:
            candidates[candidate["pid"]] = candidate
    # The private supervisor is a Linux child subreaper. Detached/double-forked
    # descendants are adopted by it, even when they create a new session.
    owned = {identity["pid"]}
    while True:
        following = owned | {
            pid
            for pid, child in candidates.items()
            if child["session"] == identity["session"] or child["ppid"] in owned
        }
        if following == owned:
            break
        owned = following
    return [child for pid, child in candidates.items() if pid in owned and child["state"] != "Z"]


def stop_session_children(identity: dict, *, grace: float = 1) -> bool:
    children = session_children(identity)
    for child in children:
        signal_process(child, signal.SIGTERM)
    deadline = time.monotonic() + grace
    while session_children(identity) and time.monotonic() < deadline:
        time.sleep(0.02)
    # Stop fork activity before the final kill pass. Each pidfd is checked again,
    # so a child that exited and had its PID reused is never targeted.
    for child in session_children(identity):
        signal_process(child, signal.SIGSTOP)
    for child in session_children(identity):
        signal_process(child, signal.SIGKILL)
    deadline = time.monotonic() + 1
    while session_children(identity) and time.monotonic() < deadline:
        time.sleep(0.02)
    return not session_children(identity)


def supervise(manifest_path: Path, lock_descriptor: int, token: str) -> int:
    # The inherited flock remains held until this supervisor exits, even if the
    # harness dies before it receives the subprocess handle.
    os.fstat(lock_descriptor)
    manifest = json.loads(manifest_path.read_text())
    if manifest["token"] != token:
        raise RuntimeError("Command supervisor identity does not match its operation")
    # PR_SET_CHILD_SUBREAPER keeps orphaned descendants owned by this isolated
    # supervisor, so setsid/double-fork cannot escape command cleanup.
    if ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) != 0:
        raise RuntimeError("Linux child-subreaper support is required before command execution")
    identity = process_identity(os.getpid())
    if identity is None or identity["session"] != os.getpid() or identity["pgid"] != os.getpid():
        raise RuntimeError("Command supervisor requires a private Linux session")
    manifest.update(phase="running", process=identity)
    atomic_json(manifest_path, manifest)
    interrupted = False

    def interrupt(_signal: int, _frame: Any) -> None:
        nonlocal interrupted
        interrupted = True

    signal.signal(signal.SIGTERM, interrupt)
    signal.signal(signal.SIGINT, interrupt)
    started = time.monotonic()
    process = subprocess.Popen(
        ["/bin/bash", "-lc", manifest["command"]], cwd=manifest["cwd"], start_new_session=True
    )
    timed_out = False
    while process.poll() is None:
        timed_out = time.monotonic() - started >= manifest["timeout"]
        if interrupted or timed_out:
            stop_session_children(identity)
            break
        time.sleep(0.05)
    background = bool(session_children(identity))
    stopped = stop_session_children(identity)
    try:
        exit_code = process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        stopped = False
        exit_code = 125
    while True:
        try:
            reaped, _ = os.waitpid(-1, os.WNOHANG)
            if reaped == 0:
                break
        except ChildProcessError:
            break
    if timed_out:
        exit_code = 124
    elif interrupted or background:
        exit_code = exit_code if exit_code != 0 else 130
    result = {
        "operation_id": manifest["operation_id"],
        "request_fingerprint": manifest["request_fingerprint"],
        "process": identity,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "interrupted": interrupted or background,
        "effects_uncertain": interrupted or timed_out or background,
        "execution_stopped": stopped,
        "duration_seconds": round(time.monotonic() - started, 3),
    }
    atomic_json(manifest_path.with_suffix(".result.json"), result)
    return 0 if exit_code == 0 else 1


if __name__ == "__main__":
    raise SystemExit(supervise(Path(sys.argv[1]), int(sys.argv[2]), sys.argv[3]))
