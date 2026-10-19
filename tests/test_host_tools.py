import asyncio
import base64
import hashlib
import json
from pathlib import Path

import httpx
import pytest

from org_harness.models import EscalationSignal, RunCreate
from org_harness.storage import MemoryStorage, PostgresStorage, RunNotFoundError, fingerprint
from org_harness.text_safety import contains_invalid_json_text
from org_harness.tools import (
    Artifacts,
    ExpectedToolInputError,
    HostTools,
    json_safe_display,
    read_reference_page,
)


async def test_reference_fetch_preserves_actual_source_and_removes_hidden_html(monkeypatch):
    requests = []

    def response(request):
        requests.append(request)
        if request.url.path == "/reference":
            return httpx.Response(302, headers={"location": "/final"})
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text="<html><script>untrusted code()</script><h1>Worlds</h1><p>Earth &amp; sky.</p></html>",
        )

    client = httpx.AsyncClient
    monkeypatch.setattr(
        "org_harness.tools.httpx.AsyncClient",
        lambda **kwargs: client(transport=httpx.MockTransport(response), **kwargs),
    )
    result = await read_reference_page("https://example.com/reference")
    assert result == {
        "requested_url": "https://example.com/reference",
        "url": "https://example.com/final",
        "status_code": 200,
        "transport": "direct_http",
        "content_type": "text/html",
        "text": "Worlds\nEarth & sky.",
    }
    assert len(requests) == 2


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(403), "HTTP 403"),
        (httpx.Response(200, content=b"x" * 2_000_001), "source limit"),
        (httpx.Response(200, headers={"content-type": "image/png"}), "textual page"),
        (
            httpx.Response(200, headers={"content-type": "text/html"}, text="<html></html>"),
            "no readable text",
        ),
    ],
)
async def test_reference_fetch_failures_are_bounded_tool_input_errors(
    monkeypatch, response, message
):
    client = httpx.AsyncClient
    monkeypatch.setattr(
        "org_harness.tools.httpx.AsyncClient",
        lambda **kwargs: client(transport=httpx.MockTransport(lambda _: response), **kwargs),
    )
    with pytest.raises(ValueError, match=message):
        await read_reference_page("https://example.com/reference")


async def test_reference_fetch_rejects_non_http_without_network():
    with pytest.raises(ValueError, match="http:// or https://"):
        await read_reference_page("file:///etc/passwd")


async def make_host(tmp_path, storage=None):
    storage = storage or MemoryStorage()
    run = await storage.create_run(
        RunCreate(user_request="Test host tools").model_dump(mode="json")
    )
    artifacts = Artifacts(storage, tmp_path, run["run_id"])

    async def emit(*args, **kwargs):
        pass

    host = HostTools(
        storage,
        artifacts,
        run,
        kr_id="kr-1",
        department="engineering",
        epoch=0,
        role="backend_coder",
        emit=emit,
    )
    return storage, run, artifacts, host


async def test_completed_command_is_not_reexecuted(tmp_path):
    storage, run, artifacts, host = await make_host(tmp_path)
    command = "echo executed >> marker.txt; cat marker.txt"
    first = await host.run_command("call-1", command)
    second = await host.run_command("call-1", command)
    assert first == second
    assert (host.workspace / "marker.txt").read_text().splitlines() == ["executed"]
    assert len(await storage.list_artifacts(run["run_id"])) == 2


async def test_unknown_command_requires_review(tmp_path):
    storage, run, artifacts, host = await make_host(tmp_path)
    operation = host.operation_id("call-1", "run_command")
    await storage.begin_operation(
        run["run_id"], operation, "command", {"command": "echo hello", "cwd": None, "timeout": 300}
    )
    with pytest.raises(EscalationSignal, match="Review interrupted command"):
        await host.run_command("call-1", "echo hello")
    await storage.complete_operation(operation, None, status="retry_approved")
    result = await host.run_command("call-1", "echo hello")
    assert result["stdout"].strip() == "hello"


async def test_cancel_terminates_host_process(tmp_path):
    storage, run, artifacts, host = await make_host(tmp_path)
    command = asyncio.create_task(host.run_command("call-1", "sleep 30"))
    await asyncio.sleep(0.15)
    await storage.command(run["run_id"], "cancel", {})
    with pytest.raises(EscalationSignal) as result:
        await asyncio.wait_for(command, 3)
    assert result.value.kind == "cancelled"


async def test_timeout_and_artifact_integrity(tmp_path):
    storage, run, artifacts, host = await make_host(tmp_path)
    result = await host.run_command("call-1", "sleep 30", timeout=1)
    assert result["exit_code"] == 124
    artifact = await artifacts.save("source.py", "print('hello')", kr_id="kr-1")
    metadata, content = await artifacts.read(artifact["artifact_id"])
    assert content == "print('hello')"
    Path(metadata["path"]).write_text("changed")
    with pytest.raises(ValueError, match="evidence record"):
        await artifacts.read(artifact["artifact_id"])


async def test_silent_command_has_receipt_instead_of_empty_output_artifacts(tmp_path):
    import json

    storage, run, artifacts, host = await make_host(tmp_path)
    result = await host.run_command("quiet", "true")
    assert result["exit_code"] == 0
    saved = await storage.list_artifacts(run["run_id"])
    assert len(saved) == 1
    assert saved[0]["kind"] == "command_result"
    assert saved[0]["size"] > 0
    _, content = await artifacts.read(saved[0]["artifact_id"])
    assert json.loads(content)["command"] == "true"
    assert json.loads(content)["exit_code"] == 0


@pytest.mark.parametrize(("stdout_size", "stderr_size"), [(32768, 32769), (32769, 32768)])
async def test_command_preview_marks_truncation_and_preserves_full_logs(
    tmp_path, stdout_size, stderr_size
):
    storage, run, artifacts, host = await make_host(tmp_path)
    command = (
        'python3 -c "import sys; '
        f"sys.stdout.write('x' * {stdout_size}); sys.stderr.write('y' * {stderr_size})\""
    )
    result = await host.run_command("bounded-preview", command)
    assert result["exit_code"] == 0
    assert result["stdout"] == "x" * 32768
    assert result["stderr"] == "y" * 32768
    assert result["stdout_truncated"] is (stdout_size > 32768)
    assert result["stderr_truncated"] is (stderr_size > 32768)
    assert await host.run_command("bounded-preview", command) == result
    saved = await storage.list_artifacts(run["run_id"])
    for suffix, size, byte in (("stdout", stdout_size, b"x"), ("stderr", stderr_size, b"y")):
        log = next(item for item in saved if item["name"].endswith(f".{suffix}.txt"))
        assert log["size"] == size
        assert Path(log["path"]).read_bytes() == byte * size
    receipt = next(item for item in saved if item["kind"] == "command_result")
    _, content = await artifacts.read(receipt["artifact_id"], limit=None)
    assert json.loads(content)["stdout_truncated"] is result["stdout_truncated"]
    assert json.loads(content)["stderr_truncated"] is result["stderr_truncated"]


async def test_cached_operation_rejects_a_different_request(tmp_path):
    _, _, _, host = await make_host(tmp_path)
    await host.run_command("reused-id", "true")
    with pytest.raises(EscalationSignal) as error:
        await host.run_command("reused-id", "false")
    assert error.value.kind == "operation_conflict"


async def test_reverting_a_file_keeps_the_final_snapshot_authoritative(tmp_path, monkeypatch):
    storage, run, artifacts, host = await make_host(tmp_path)
    for call_id, content in [
        ("first", "answer = 1\n"),
        ("second", "answer = 42\n"),
        ("revert", "answer = 1\n"),
    ]:
        await host.write_file(call_id, "answer.py", content)
    list_artifacts = storage.list_artifacts

    async def reversed_rows(run_id):
        return list(reversed(await list_artifacts(run_id)))

    monkeypatch.setattr(storage, "list_artifacts", reversed_rows)
    current = await host.recorded_artifacts(current=True)
    assert len(current) == 1
    _, content = await artifacts.read(current[0]["artifact_id"])
    assert content == (host.workspace / "answer.py").read_text() == "answer = 1\n"
    assert len(await storage.list_artifacts(run["run_id"])) == 3


async def test_reused_provider_ids_are_isolated_between_work_packages_and_attempts(tmp_path):
    storage, run, artifacts, host = await make_host(tmp_path)
    command = "echo executed >> attempts.txt"
    await host.run_command("provider-id", command)
    for work_package, attempt in [("second-package", 0), ("second-package", 1)]:
        other = HostTools(
            storage,
            artifacts,
            run,
            kr_id="kr-1",
            department="engineering",
            epoch=0,
            role="backend_coder",
            emit=host.emit,
            work_package_id=work_package,
            attempt=attempt,
        )
        await other.run_command("provider-id", command)
        await other.run_command("provider-id", command)  # Same attempt is a replay.
    assert (host.workspace / "attempts.txt").read_text().splitlines() == ["executed"] * 3


async def test_parallel_identical_operation_ids_execute_once(tmp_path):
    storage, run, artifacts, host = await make_host(tmp_path)
    command = "echo executed >> duplicate.txt; sleep 0.05; cat duplicate.txt"
    first, second = await asyncio.gather(
        host.run_command("same-id", command), host.run_command("same-id", command)
    )
    assert first == second
    assert (host.workspace / "duplicate.txt").read_text().splitlines() == ["executed"]
    assert (await storage.get_run(run["run_id"]))["tool_calls"] == 1


@pytest.mark.parametrize(
    "error",
    [
        KeyError("bug"),
        LookupError("bug"),
        ValueError("bug"),
        OSError("storage fault"),
        RunNotFoundError("Run not found"),
    ],
)
async def test_journal_does_not_complete_unclassified_failures(tmp_path, error):
    storage, _, _, host = await make_host(tmp_path)

    async def fail():
        raise error

    with pytest.raises(type(error)):
        await host.journal("unexpected", "read_file", {}, fail)
    assert (await storage.get_operation(host.operation_id("unexpected", "read_file")))[
        "status"
    ] == "pending"


async def test_journal_completes_only_typed_input_error_and_replays_it(tmp_path):
    storage, run, _, host = await make_host(tmp_path)
    executions = 0

    async def fail():
        nonlocal executions
        executions += 1
        raise ExpectedToolInputError("Use a real artifact ID")

    first = await host.journal("input-error", "read_artifact", {}, fail)
    assert first == await host.journal("input-error", "read_artifact", {}, fail)
    assert first["error"] == "ExpectedToolInputError"
    assert executions == 1
    assert (await storage.get_run(run["run_id"]))["tool_calls"] == 1


@pytest.mark.parametrize("stage", ["get_operation", "reserve_budget", "begin_operation", "get_run"])
async def test_journal_storage_setup_failure_never_executes_tool(tmp_path, monkeypatch, stage):
    storage, _, _, host = await make_host(tmp_path)
    executed = False

    async def storage_failure(*args, **kwargs):
        raise RunNotFoundError("Run not found")

    async def execute():
        nonlocal executed
        executed = True
        return {"success": True}

    monkeypatch.setattr(storage, stage, storage_failure)
    with pytest.raises(RunNotFoundError):
        await host.journal("setup", "read_file", {}, execute)
    assert not executed
    assert all(item["status"] == "pending" for item in storage.operations.values())


@pytest.mark.parametrize("stage", ["register_artifact", "complete_operation", "final_event"])
async def test_command_finalization_failure_keeps_side_effect_pending(tmp_path, monkeypatch, stage):
    storage, run, _, host = await make_host(tmp_path)

    async def fail(*args, **kwargs):
        raise OSError("Persistence unavailable")

    if stage == "final_event":

        async def emit(role, activity, summary, **kwargs):
            if summary.startswith("Command exited"):
                await fail()

        monkeypatch.setattr(host, "emit", emit)
    else:
        monkeypatch.setattr(storage, stage, fail)
    command = "echo once >> effect.txt"
    with pytest.raises(OSError):
        await host.run_command("finalization", command)
    assert (host.workspace / "effect.txt").read_text().splitlines() == ["once"]
    pending = await storage.uncertain_operations(run["run_id"])
    assert len(pending) == 1
    with pytest.raises(EscalationSignal) as error:
        await host.run_command("finalization", command)
    assert error.value.kind == "unknown_operation"
    assert (host.workspace / "effect.txt").read_text().splitlines() == ["once"]


async def test_cancelled_command_task_preserves_pending_operation(tmp_path):
    storage, run, _, host = await make_host(tmp_path)
    command = "echo started > started.txt; sleep 30"
    task = asyncio.create_task(host.run_command("interrupted", command))
    marker = host.workspace / "started.txt"
    async with asyncio.timeout(5):
        while not marker.exists():
            await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(await storage.uncertain_operations(run["run_id"])) == 1
    with pytest.raises(EscalationSignal) as error:
        await host.run_command("interrupted", command)
    assert error.value.kind == "unknown_operation"


async def test_configured_workspace_race_is_a_resource_blocker(tmp_path):
    storage, run, artifacts, host = await make_host(tmp_path)
    run["workspace_path"] = str(tmp_path / "removed")
    with pytest.raises(EscalationSignal) as error:
        HostTools(
            storage,
            artifacts,
            run,
            kr_id="kr",
            department="engineering",
            epoch=0,
            role="backend_coder",
            emit=host.emit,
        )
    assert error.value.kind == "missing_resource"


async def test_managed_workspace_storage_failure_is_not_an_input_error(tmp_path, monkeypatch):
    storage, run, artifacts, host = await make_host(tmp_path)

    def fail(*args, **kwargs):
        raise OSError("Managed data disk unavailable")

    monkeypatch.setattr(Path, "mkdir", fail)
    with pytest.raises(OSError):
        HostTools(
            storage,
            artifacts,
            run,
            kr_id="new-kr",
            department="engineering",
            epoch=0,
            role="backend_coder",
            emit=host.emit,
        )


PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aCYQAAAAASUVORK5CYII="
)


async def check_pending_png_read_and_completed_command(storage, tmp_path):
    storage, run, artifacts, host = await make_host(tmp_path, storage)
    png = host.workspace / "render_evidence.png"
    png.write_bytes(PNG)
    command = "echo once >> command-count.txt"
    original = await host.run_command("completed-command", command)
    read_operation = host.operation_id("pending-image-read", "read_file")
    await storage.begin_operation(run["run_id"], read_operation, "tool", {"path": str(png)})
    result, replayed = await asyncio.gather(
        host.read_file("pending-image-read", str(png)),
        host.run_command("completed-command", command),
    )
    assert result["error"] == "ExpectedToolInputError"
    assert "binary" in result["detail"]
    assert not contains_invalid_json_text(result)
    assert replayed == original
    assert (host.workspace / "command-count.txt").read_text().splitlines() == ["once"]
    assert png.read_bytes() == PNG
    assert (await storage.get_operation(read_operation))["status"] == "done"
    assert not await storage.uncertain_operations(run["run_id"])
    artifact = await artifacts.save("image.png", PNG)
    with pytest.raises(ExpectedToolInputError, match="binary"):
        await artifacts.read(artifact["artifact_id"])
    assert Path(artifact["path"]).read_bytes() == PNG


async def test_pending_binary_read_recovers_without_replaying_completed_command(tmp_path):
    await check_pending_png_read_and_completed_command(MemoryStorage(), tmp_path)


async def check_unsafe_request_and_output_boundaries(storage, tmp_path):
    storage, run, artifacts, host = await make_host(tmp_path, storage)
    for index, invalid in enumerate(("\x00", "\ud800", "\udfff")):
        request = {"command": f"echo never >> unsafe.txt{invalid}", "cwd": None, "timeout": 300}
        first = await host.run_command(f"unsafe-{index}", request["command"])
        second = await host.run_command(f"unsafe-{index}", request["command"])
        assert first == second
        assert first["error"] == "ExpectedToolInputError"
        operation = await storage.get_operation(host.operation_id(f"unsafe-{index}", "run_command"))
        assert operation["request"] == {
            "invalid_input": True,
            "request_fingerprint": fingerprint(request),
        }
        assert operation["kind"] == "invalid_input"
        assert operation["status"] == "done"
        invalid_path = await host.read_file(f"unsafe-path-{index}", f"missing{invalid}")
        invalid_content = await host.write_file(
            f"unsafe-content-{index}", "never.txt", f"bad{invalid}"
        )
        assert invalid_path["error"] == "ExpectedToolInputError"
        assert invalid_content["error"] == "ExpectedToolInputError"
    assert not (host.workspace / "unsafe.txt").exists()
    assert not (host.workspace / "never.txt").exists()
    result = await host.run_command("nul-output", "printf 'before\\000after'")
    assert result["stdout"] == "before\\u0000after"
    assert result["display_encoding"] == "json-string-escape"
    logs = [
        item
        for item in await storage.list_artifacts(run["run_id"])
        if item["kind"] == "command_log"
    ]
    assert any(Path(item["path"]).read_bytes() == b"before\x00after" for item in logs)

    raw = {
        "response": {
            "text": "source\x00content",
            "surrogate": "\ud800",
            "\\u0000": "literal",
            "\x00": "actual",
        }
    }

    async def source():
        return raw

    recorded = await host.record_research(
        "nul-source", "web_reader", {"url": "https://example.com"}, source
    )
    assert recorded["display_encoding"] == "json-string-escape"
    assert not contains_invalid_json_text(recorded)
    metadata, content = await artifacts.read(recorded["artifact_id"], limit=None)
    assert json.loads(content) == raw
    assert metadata["kind"] == "research"
    assert not await storage.uncertain_operations(run["run_id"])


async def test_unsafe_requests_have_zero_effects_and_outputs_have_lossless_display(tmp_path):
    await check_unsafe_request_and_output_boundaries(MemoryStorage(), tmp_path)


@pytest.mark.integration
async def test_postgres_binary_read_and_unsafe_request_output_boundaries(tmp_path, postgres_url):
    storage = PostgresStorage(postgres_url)
    await storage.open()
    try:
        await storage.migrate()
        await check_pending_png_read_and_completed_command(storage, tmp_path / "png")
        await check_unsafe_request_and_output_boundaries(storage, tmp_path / "text")
    finally:
        await storage.close()


def test_display_escaping_is_reversible_without_key_collisions():
    original = {
        "\x00": "actual\x00value",
        "\\u0000": "literal\\u0000value",
        "nested": ['line\nquote"\ud800'],
        7: "numeric key",
    }
    escaped = json_safe_display(original)
    assert len(escaped) == 4
    assert escaped[7] == "numeric key"
    assert not contains_invalid_json_text(escaped)

    def restore(value):
        if isinstance(value, str):
            return json.loads('"' + value + '"')
        if isinstance(value, dict):
            return {restore(key): restore(item) for key, item in value.items()}
        if isinstance(value, list):
            return [restore(item) for item in value]
        return value

    assert restore(escaped) == original


async def check_existing_html_publication(storage, tmp_path):
    storage, run, artifacts, host = await make_host(tmp_path, storage)
    body = (
        b"\xef\xbb\xbf<!doctype html><html><script>const scene = '"
        + "🌏".encode()
        + b"';</script></html>"
        + b" " * 11000
    )
    target = host.workspace / "index.html"
    target.write_bytes(body)
    first = await host.publish_file("publish-html", "index.html")
    assert set(first) == {"artifact_id", "path", "size", "sha256"}
    assert first["size"] == len(body)
    assert first["sha256"] == hashlib.sha256(body).hexdigest()
    assert target.read_bytes() == body
    metadata = await storage.get_artifact(first["artifact_id"])
    assert metadata["kind"] == "source"
    assert metadata["kr_id"] == host.kr_id
    assert metadata["version"] == host.version
    assert metadata["epoch"] == host.epoch
    assert metadata["scope"] == host.scope
    assert metadata["original_path"] == str(target)
    assert metadata["write_id"] == host.operation_id("publish-html", "publish_file")
    assert Path(metadata["path"]).read_bytes() == body
    target.unlink()
    assert await host.publish_file("publish-html", "index.html") == first
    assert (await storage.get_run(run["run_id"]))["tool_calls"] == 1
    replacement = b"<!doctype html><html>Updated final HTML</html>"
    target.write_bytes(replacement)
    second = await host.publish_file("publish-updated", "index.html")
    assert second["artifact_id"] != first["artifact_id"]
    current = await host.recorded_artifacts(current=True)
    assert [item["artifact_id"] for item in current] == [second["artifact_id"]]
    assert Path(metadata["path"]).read_bytes() == body
    assert not await storage.uncertain_operations(run["run_id"])


async def test_publish_existing_html_preserves_bytes_scope_and_replay(tmp_path):
    await check_existing_html_publication(MemoryStorage(), tmp_path)


@pytest.mark.integration
async def test_postgres_publish_existing_html_preserves_bytes_scope_and_replay(
    tmp_path, postgres_url
):
    storage = PostgresStorage(postgres_url)
    await storage.open()
    try:
        await storage.migrate()
        await check_existing_html_publication(storage, tmp_path)
    finally:
        await storage.close()


@pytest.mark.parametrize("body", [b"", b" \n\t", PNG, b"text\x00binary", b"\xff", b"x" * 2_000_001])
async def test_publish_rejects_empty_binary_invalid_and_oversized_outputs(tmp_path, body):
    storage, run, artifacts, host = await make_host(tmp_path)
    target = host.workspace / "invalid-output"
    target.write_bytes(body)
    result = await host.publish_file("invalid-publication", str(target))
    assert result["error"] == "ExpectedToolInputError"
    assert target.read_bytes() == body
    assert not await storage.list_artifacts(run["run_id"])
    operation = await storage.get_operation(
        host.operation_id("invalid-publication", "publish_file")
    )
    assert operation["status"] == "done"


async def test_publish_accepts_exact_size_bound_and_rejects_missing_output(tmp_path):
    storage, run, artifacts, host = await make_host(tmp_path)
    target = host.workspace / "large.txt"
    target.write_bytes(b"x" * 2_000_000)
    result = await host.publish_file("maximum", str(target))
    assert result["size"] == 2_000_000
    assert (await host.publish_file("missing", "missing.txt"))["error"] == "ExpectedToolInputError"
    assert (await host.publish_file("directory", "."))["error"] == "ExpectedToolInputError"
