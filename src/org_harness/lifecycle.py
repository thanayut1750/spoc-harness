"""Manage the local API and worker without touching their durable application data."""

from __future__ import annotations

import hashlib
import json
import math
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
from pydantic import AliasChoices, SecretStr

from org_harness.config import Settings
from org_harness.text_safety import contains_invalid_json_text

ROLES = ("api", "worker")
CONFIG_ENV = "SPOC_SERVICE_MANAGER_CONFIG"


class LifecycleError(RuntimeError):
    """An operator-actionable failure whose message contains no configuration secrets."""


class ServiceManager:
    def __init__(self, settings: Settings, directory: Path | None = None):
        self.settings = settings
        self.environment = self._environment()
        if contains_invalid_json_text(self.environment) or contains_invalid_json_text(
            str(directory or "")
        ):
            raise LifecycleError(
                "Service configuration contains unsupported text; fix configuration before starting services."
            )
        try:
            self.cwd = Path.cwd().resolve()
            self.data_dir = settings.data_dir.resolve()
            self.directory = (directory or self.data_dir / "services").resolve()
        except (OSError, ValueError, RuntimeError):
            raise LifecycleError(
                "Service configuration paths are invalid or unavailable."
            ) from None
        if contains_invalid_json_text(str(self.cwd)):
            raise LifecycleError("The project directory contains unsupported text.")
        self.state_path = self.directory / "state.json"
        self.logs = {role: self.data_dir / f"{role}.log" for role in ROLES}
        self.config_identity = hashlib.sha256(
            json.dumps(self.environment, sort_keys=True).encode()
        ).hexdigest()
        self.environment[CONFIG_ENV] = self.config_identity
        host = settings.api_host
        host = "127.0.0.1" if host == "0.0.0.0" else "::1" if host == "::" else host
        self.api_url = f"http://{'[' + host + ']' if ':' in host else host}:{settings.api_port}"
        self._children: dict[int, subprocess.Popen] = {}

    def _environment(self) -> dict[str, str]:
        resolved = {}
        for name, field in type(self.settings).model_fields.items():
            value = getattr(self.settings, name)
            alias = field.validation_alias
            if isinstance(alias, AliasChoices):
                alias = alias.choices[0]
            key = alias if isinstance(alias, str) else name.upper()
            if isinstance(value, SecretStr):
                value = value.get_secret_value()
            elif isinstance(value, Path):
                if contains_invalid_json_text(str(value)):
                    raise LifecycleError(
                        "Service configuration contains unsupported text; fix configuration before starting services."
                    )
                try:
                    value = str(value.resolve())
                except (OSError, ValueError, RuntimeError):
                    raise LifecycleError(
                        "Service configuration paths are invalid or unavailable."
                    ) from None
            elif isinstance(value, bool):
                value = str(value).lower()
            resolved[key] = str(value)
        return resolved

    @contextmanager
    def _locked(self, timeout: float) -> Iterator[None]:
        if not sys.platform.startswith("linux") or not hasattr(os, "pidfd_open"):
            raise LifecycleError(
                "Managed services require Linux process identity support; use spoc serve and spoc worker in the foreground."
            )
        import fcntl

        if not math.isfinite(timeout) or timeout <= 0:
            raise LifecycleError("Timeout must be finite and positive.")
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            lock_handle = (self.directory / "manager.lock").open("a")
        except OSError:
            raise LifecycleError(
                "Cannot access service state; check directory paths and permissions."
            ) from None
        with lock_handle as handle:
            deadline = time.monotonic() + timeout
            while True:
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise LifecycleError(
                            "Another lifecycle command is still running; try again."
                        ) from None
                    time.sleep(0.05)
            try:
                yield
            except OSError:
                raise LifecycleError(
                    "Service operation failed; check state/log permissions and the Python environment."
                ) from None
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def _inspect(self, pid: int) -> dict[str, Any] | None:
        child = self._children.get(pid)
        if child is not None and child.poll() is not None:
            return None
        root = Path(f"/proc/{pid}")
        try:
            fields = (root / "stat").read_text().rsplit(")", 1)[1].split()
            if fields[0] in {"Z", "X", "x"}:
                return None
            identity = {
                "pid": pid,
                "start_time": fields[19],
                "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                "uid": root.stat().st_uid,
                "cwd": str((root / "cwd").resolve(strict=True)),
                "argv": [
                    part.decode() for part in (root / "cmdline").read_bytes().split(b"\0") if part
                ],
            }
            final_fields = (root / "stat").read_text().rsplit(")", 1)[1].split()
            if final_fields[0] in {"Z", "X", "x"} or (
                not identity["argv"] and final_fields[20] == "0"
            ):
                return None
            if final_fields[19] != identity["start_time"]:
                raise LifecycleError("Process identity changed while checking it; no signal sent.")
            return identity
        except (FileNotFoundError, ProcessLookupError):
            return None
        except (OSError, UnicodeError, IndexError):
            raise LifecycleError(
                "Cannot verify a recorded process; no signals were sent."
            ) from None

    def _is_service(self, identity: dict, role: str) -> bool:
        if identity["uid"] != os.getuid() or identity["cwd"] != str(self.cwd):
            return False
        argv = identity["argv"]
        if not argv or Path(argv[0]).resolve() != Path(sys.executable).resolve():
            return False
        command = "serve" if role == "api" else "worker"
        module = len(argv) >= 4 and argv[1:4] == ["-m", "org_harness.cli", command]
        script = (
            len(argv) >= 3
            and Path(argv[1]).resolve() == (Path(sys.executable).parent / "spoc").resolve()
            and argv[2] == command
        )
        return module or script

    def _verify(self, record: dict, role: str) -> dict | None:
        identity = self._inspect(record["pid"])
        if identity is None:
            return None
        if not self._is_service(identity, role) or any(
            identity[key] != record.get(key) for key in identity
        ):
            raise LifecycleError(
                f"Refusing to control {role}: its recorded process identity changed. No signal sent."
            )
        return identity

    def _write(self, state: dict) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", dir=self.directory, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump({"version": 1, "services": state}, handle)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            temporary.replace(self.state_path)
        finally:
            temporary.unlink(missing_ok=True)

    def _legacy(self, role: str) -> dict | None:
        path = self.data_dir / f"{role}.pid"
        if not path.exists():
            return None
        try:
            pid = int(path.read_text().strip())
            if pid <= 0:
                raise ValueError
        except (OSError, ValueError):
            raise LifecycleError(
                f"Cannot verify legacy {role}.pid; inspect it before retrying."
            ) from None
        identity = self._inspect(pid)
        if identity is None:
            path.unlink()
            return None
        if not self._is_service(identity, role):
            raise LifecycleError(
                f"Legacy {role}.pid identifies an unrelated process; refusing to signal it."
            )
        try:
            process_env = dict(
                part.split(b"=", 1)
                for part in Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
                if b"=" in part
            )
        except OSError:
            raise LifecycleError(
                f"Cannot verify legacy {role} configuration; no signals sent."
            ) from None
        exported_data_dir = process_env.get(b"SPOC_DATA_DIR")
        if exported_data_dir is not None:
            try:
                directory = os.fsdecode(exported_data_dir)
                if contains_invalid_json_text(directory):
                    raise ValueError
                owned_directory = Path(directory).resolve()
            except (OSError, ValueError, RuntimeError):
                raise LifecycleError(
                    f"Cannot verify legacy {role} data directory; no signals sent."
                ) from None
            if owned_directory != self.data_dir:
                raise LifecycleError(
                    f"Legacy {role} belongs to a different data directory; no signals sent."
                )
        # Provider/model/database changes are a reason to restart an owned
        # service. Keep its original marker so start cannot claim it already
        # runs with the new settings.
        marker = process_env.get(CONFIG_ENV.encode())
        return {**identity, "service": role, "config_identity": marker.decode() if marker else None}

    def _load(self) -> dict:
        try:
            content = (
                json.loads(self.state_path.read_text())
                if self.state_path.exists()
                else {"version": 1, "services": {}}
            )
            state = content["services"]
            if content["version"] != 1 or not isinstance(state, dict) or set(state) - set(ROLES):
                raise ValueError
            for role, record in list(state.items()):
                if (
                    not isinstance(record, dict)
                    or record.get("service") != role
                    or not isinstance(record.get("pid"), int)
                    or record["pid"] <= 0
                ):
                    raise ValueError
                if self._verify(record, role) is None:
                    del state[role]
        except (ValueError, KeyError, TypeError, OSError):
            raise LifecycleError(
                "Service state is unreadable or invalid; inspect services/state.json before retrying."
            ) from None
        adopted = []
        for role in ROLES:
            legacy_path = self.data_dir / f"{role}.pid"
            if legacy_path.exists():
                legacy = self._legacy(role)
                if legacy:
                    if role in state and state[role]["pid"] != legacy["pid"]:
                        raise LifecycleError(
                            f"Multiple verified {role} processes exist; resolve them before continuing."
                        )
                    state.setdefault(role, legacy)
                    adopted.append(legacy_path)
        self._write(state)
        for path in adopted:
            path.unlink(missing_ok=True)
        return state

    def _port_available(self) -> None:
        try:
            addresses = socket.getaddrinfo(
                self.settings.api_host, self.settings.api_port, type=socket.SOCK_STREAM
            )
            family, kind, protocol, _, address = addresses[0]
            with socket.socket(family, kind, protocol) as handle:
                handle.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                handle.bind(address)
        except OSError:
            raise LifecycleError(
                f"API port {self.settings.api_port} is occupied or unavailable; no unrelated process was stopped."
            ) from None

    def _spawn(self, role: str) -> dict:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        command = "serve" if role == "api" else "worker"
        with self.logs[role].open("ab") as log:
            child = subprocess.Popen(
                [sys.executable, "-m", "org_harness.cli", command],
                cwd=self.cwd,
                env={**os.environ, **self.environment},
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                close_fds=True,
                start_new_session=True,
            )
        self._children[child.pid] = child
        identity = self._inspect(child.pid)
        if identity is None or not self._is_service(identity, role):
            raise LifecycleError(f"The {role} process exited during startup; inspect {role}.log.")
        return {**identity, "service": role, "config_identity": self.config_identity}

    def _rollback_new(self, pids: set[int], timeout: float) -> None:
        """Stop only this invocation's exact Popen children, even if state writes failed."""
        children = [child for pid, child in reversed(list(self._children.items())) if pid in pids]
        for child in children:
            if child.poll() is None:
                child.send_signal(signal.SIGINT)
        deadline = time.monotonic() + timeout
        for child in children:
            try:
                child.wait(timeout=max(0.01, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                raise LifecycleError(
                    f"A newly started service is still shutting down; inspect PID {child.pid} and its log."
                ) from None

    def _signal(self, record: dict, role: str, signum: int) -> None:
        if self._verify(record, role) is None:
            return
        try:
            descriptor = os.pidfd_open(record["pid"])
            try:
                if self._verify(record, role) is not None:
                    signal.pidfd_send_signal(descriptor, signum)
            finally:
                os.close(descriptor)
        except ProcessLookupError:
            return
        except (OSError, AttributeError):
            raise LifecycleError(
                f"Cannot safely signal {role}; its process was left running."
            ) from None

    def _wait_gone(self, state: dict, deadline: float) -> bool:
        while True:
            if all(self._verify(record, role) is None for role, record in state.items()):
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.05)

    def _stop_records(
        self, state: dict, timeout: float, force: bool, *, persisted_state: dict | None = None
    ) -> None:
        # Stop worker first while the API is still available; SIGINT allows asyncio cleanup.
        deadline = time.monotonic() + timeout
        for role in ("worker", "api"):
            if role in state:
                if not state[role].get("stopping"):
                    state[role]["stopping"] = True
                    self._write(state if persisted_state is None else persisted_state)
                    self._signal(state[role], role, signal.SIGINT)
                if not self._wait_gone({role: state[role]}, deadline):
                    if not force:
                        raise LifecycleError(
                            f"The {role} is still shutting down; retry stop or use --force explicitly."
                        )
                    for signum in (signal.SIGTERM, signal.SIGKILL):
                        self._signal(state[role], role, signum)
                        if self._wait_gone({role: state[role]}, time.monotonic() + 2):
                            break
                    else:
                        raise LifecycleError(
                            f"The {role} could not be stopped; inspect its process before retrying."
                        )

    def _summary(self, state: dict, *, ready: bool = False) -> dict:
        return {
            "api_url": self.api_url,
            "services": {
                role: {
                    "status": ("stopping" if state[role].get("stopping") else "running")
                    if role in state
                    else "stopped",
                    "pid": state.get(role, {}).get("pid"),
                    "log": str(self.logs[role]),
                    **(
                        {"ready": ready}
                        if role == "api"
                        else {"readiness": "process_started" if role in state else "stopped"}
                    ),
                }
                for role in ROLES
            },
            "state_file": str(self.state_path),
        }

    def _start(self, state: dict, timeout: float) -> dict:
        if self.settings.storage_backend == "memory":
            raise LifecycleError(
                "Managed API and worker require shared Postgres storage; memory storage cannot share jobs."
            )
        if any(record.get("stopping") for record in state.values()):
            raise LifecycleError(
                "A managed service is still stopping; finish spoc stop before starting it again."
            )
        if any(record.get("config_identity") is None for record in state.values()):
            raise LifecycleError(
                "Legacy service configuration is unknown; use spoc restart to apply current settings."
            )
        if any(record.get("config_identity") != self.config_identity for record in state.values()):
            raise LifecycleError(
                "Managed service settings changed; use spoc restart to apply them."
            )
        if "api" not in state:
            self._port_available()
        previous_children = set(self._children)
        try:
            for role in ROLES:
                if role not in state:
                    state[role] = self._spawn(role)
                    self._write(state)
            deadline = time.monotonic() + timeout
            stable_after = time.monotonic() + 0.3
            with httpx.Client(trust_env=False, timeout=0.5) as client:
                while True:
                    for role in ROLES:
                        if self._verify(state[role], role) is None:
                            raise LifecycleError(
                                f"The {role} exited during startup; inspect {role}.log."
                            )
                    try:
                        response = client.get(f"{self.api_url}/readyz")
                        payload = response.json()
                        ready = (
                            response.status_code == 200
                            and isinstance(payload, dict)
                            and payload.get("status") == "ready"
                        )
                    except (httpx.HTTPError, ValueError):
                        ready = False
                    if ready and time.monotonic() >= stable_after:
                        return self._summary(state, ready=True)
                    if time.monotonic() >= deadline:
                        raise LifecycleError(
                            "API did not become ready; inspect api.log and database readiness/migrations."
                        )
                    time.sleep(0.05)
        except Exception:
            created_pids = set(self._children) - previous_children
            for record in state.values():
                if record["pid"] in created_pids:
                    record["stopping"] = True
            try:
                try:
                    self._write(state)
                except OSError:
                    pass  # Cleanup must not depend on writable lifecycle state.
                self._rollback_new(created_pids, min(timeout, 5))
            finally:
                try:
                    self._write(
                        {
                            role: record
                            for role, record in state.items()
                            if self._verify(record, role) is not None
                        }
                    )
                except OSError:
                    pass
            raise

    def start(self, timeout: float = 15) -> dict:
        self._require_shared_storage()
        with self._locked(timeout):
            return self._start(self._load(), timeout)

    def stop(self, timeout: float = 15, force: bool = False) -> dict:
        with self._locked(timeout):
            state = self._load()
            try:
                self._stop_records(state, timeout, force)
            finally:
                self._write(
                    {
                        role: record
                        for role, record in state.items()
                        if self._verify(record, role) is not None
                    }
                )
            return self._summary({})

    def restart(self, timeout: float = 15, force: bool = False) -> dict:
        self._require_shared_storage()
        with self._locked(timeout):
            state = self._load()
            try:
                self._stop_records(state, timeout, force)
            finally:
                remaining = {
                    role: record
                    for role, record in state.items()
                    if self._verify(record, role) is not None
                }
                self._write(remaining)
            return self._start({}, timeout)

    def _require_shared_storage(self) -> None:
        if self.settings.storage_backend == "memory":
            raise LifecycleError(
                "Managed API and worker require shared Postgres storage; memory storage cannot share jobs."
            )
