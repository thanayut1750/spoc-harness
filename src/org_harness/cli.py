"""Operator commands for the local API, worker, migrations, and diagnostics."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated
from uuid import uuid4

import httpx
import typer

from org_harness.config import Settings, configure_tracing

app = typer.Typer(no_args_is_help=True, help="SPOC local agent harness")


def display(value):
    typer.echo(json.dumps(value, indent=2, default=str))


def request(method: str, path: str, *, body: dict | None = None):
    settings = Settings()
    host = settings.api_host if settings.api_host not in {"0.0.0.0", "::"} else "127.0.0.1"
    try:
        response = httpx.request(
            method,
            f"http://{host}:{settings.api_port}{path}",
            json=body,
            timeout=30,
            headers={"Idempotency-Key": str(uuid4())},
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        try:
            problem = exc.response.json()
            detail = (
                problem.get("detail", "Request rejected")
                if isinstance(problem, dict)
                else "Request rejected"
            )
        except ValueError:
            detail = "Request rejected"
        typer.echo(f"HTTP {exc.response.status_code}: {detail}", err=True)
        raise typer.Exit(1) from None
    except httpx.HTTPError:
        typer.echo("Cannot reach the local API; run spoc start.", err=True)
        raise typer.Exit(1) from None
    except ValueError:
        typer.echo(
            "The local API returned invalid JSON; check that the API service is running.", err=True
        )
        raise typer.Exit(1) from None


def service_command(action: str, *, timeout: float, force: bool = False) -> None:
    from org_harness.lifecycle import LifecycleError, ServiceManager

    try:
        settings = Settings()
    except ValueError:
        typer.echo(
            "Cannot load service configuration; check .env and environment settings.", err=True
        )
        raise typer.Exit(1) from None
    try:
        manager = ServiceManager(settings)
        if action == "start":
            result = manager.start(timeout=timeout)
        elif action == "stop":
            result = manager.stop(timeout=timeout, force=force)
        elif action == "restart":
            result = manager.restart(timeout=timeout, force=force)
        else:
            raise ValueError("Unknown service command")
    except LifecycleError as exc:
        typer.echo(f"Cannot {action} services: {exc}", err=True)
        raise typer.Exit(1) from None
    except OSError as exc:
        typer.echo(
            f"Cannot {action} services ({type(exc).__name__}); check service files and permissions.",
            err=True,
        )
        raise typer.Exit(1) from None
    display(result)


@app.command()
def start(
    timeout: Annotated[
        float, typer.Option(min=1, max=120, help="Seconds to wait for service startup.")
    ] = 15,
):
    """Start the API and worker in the background; reuse services already running."""
    service_command("start", timeout=timeout)


@app.command()
def stop(
    timeout: Annotated[
        float, typer.Option(min=1, max=120, help="Seconds to allow graceful shutdown.")
    ] = 15,
    force: Annotated[
        bool, typer.Option(help="Force verified service processes to exit after the timeout.")
    ] = False,
):
    """Stop the local API and worker, preserving saved runs and evidence."""
    service_command("stop", timeout=timeout, force=force)


@app.command()
def restart(
    timeout: Annotated[
        float, typer.Option(min=1, max=120, help="Seconds to wait for each shutdown/startup phase.")
    ] = 15,
    force: Annotated[
        bool, typer.Option(help="Force verified service processes to exit after the timeout.")
    ] = False,
):
    """Restart both services using the current environment configuration."""
    service_command("restart", timeout=timeout, force=force)


@app.command("retry")
def retry_run(run_id: str):
    """Retry failed execution from its checkpoint; interrupted commands still require review."""
    display(request("POST", f"/api/runs/{run_id}/retry"))


@app.command()
def serve(host: str | None = None, port: int | None = None):
    """Serve the API and built office frontend."""
    import uvicorn

    from org_harness.api import create_app

    settings = Settings()
    uvicorn.run(
        create_app(settings),
        host=host or settings.api_host,
        port=port or settings.api_port,
        timeout_graceful_shutdown=5,
    )


@app.command()
def worker():
    """Execute queued runs with durable graph persistence."""
    from org_harness.worker import run_worker

    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        return
    except Exception as exc:
        typer.echo(
            f"Worker stopped ({type(exc).__name__}); check database readiness and configuration.",
            err=True,
        )
        raise typer.Exit(1) from None


@app.command()
def migrate():
    """Apply application, checkpoint, and memory-store schema migrations."""
    from org_harness.worker import migrate as run_migrations

    try:
        asyncio.run(run_migrations(Settings()))
    except Exception as exc:
        typer.echo(
            f"Migration failed ({type(exc).__name__}); check database configuration.", err=True
        )
        raise typer.Exit(1) from None
    typer.echo("Migrations applied.")


async def live_diagnostics(settings: Settings) -> dict[str, object]:
    """Opt-in live provider roundtrip and read-only MCP tool discovery."""
    from langchain.mcp import MCPAdapter
    from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage

    from org_harness.providers import ZaiChatModel

    configure_tracing(settings)
    result: dict[str, object] = {}
    model = ZaiChatModel(
        model=settings.main_model,
        base_url=settings.openai_base_url,
        api_key=settings.openai_api_key,
        reasoning_effort=settings.reasoning_effort,
        timeout=settings.model_timeout,
        max_tokens=settings.model_max_tokens,
    )
    try:
        response = await model.ainvoke(
            [HumanMessage(content='Return exactly JSON {"ok": true}')],
            response_format={"type": "json_object"},
        )
        result["provider_json"] = json.loads(str(response.content)).get("ok") is True
        bound = model.bind_tools(
            [
                {
                    "type": "function",
                    "function": {
                        "name": "check_connection",
                        "description": "Check the required test connection",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ]
        )
        messages: list[BaseMessage] = [
            HumanMessage(content="Call check_connection before answering this diagnostic.")
        ]
        turn = await bound.ainvoke(messages)
        if not turn.tool_calls:
            result["provider_tool_roundtrip"] = False
        else:
            messages.append(turn)
            messages.extend(
                ToolMessage(content='{"ok":true}', tool_call_id=call["id"])
                for call in turn.tool_calls
            )
            final = await bound.ainvoke(messages)
            result["provider_tool_roundtrip"] = bool(final.content)
    except Exception as exc:
        result["provider_error"] = type(exc).__name__
    finally:
        await model.aclose()

    async def probe_mcp(kind: str, url: str) -> None:
        try:

            async def discover():
                async with MCPAdapter(
                    {
                        "mcpServers": {
                            kind: {
                                "url": url,
                                "headers": {
                                    "Authorization": f"Bearer {settings.openai_api_key.get_secret_value()}"
                                },
                            }
                        }
                    }
                ) as adapter:
                    tools = await adapter.list_tools()
                    return any(kind in tool.name.lower() for tool in tools)

            result[f"{kind}_mcp"] = await asyncio.wait_for(
                discover(), timeout=settings.model_timeout
            )
        except Exception as exc:
            result[f"{kind}_mcp"] = False
            result[f"{kind}_mcp_error"] = type(exc).__name__

    await asyncio.gather(
        probe_mcp("search", settings.search_mcp_url), probe_mcp("reader", settings.reader_mcp_url)
    )
    return result


@app.command()
def doctor(live: bool = False):
    """Check local settings/database; --live also verifies provider JSON and tools."""
    from org_harness.storage import create_storage

    async def inspect():
        settings = Settings()
        configure_tracing(settings)
        result = settings.redacted()
        storage = create_storage(settings)
        try:
            await storage.open()
            result["database_ready"] = await storage.ready()
        except Exception as exc:
            result["database_ready"] = False
            result["database_error"] = type(exc).__name__
        finally:
            await storage.close()
        if live:
            result.update(await live_diagnostics(settings))
        return result

    result = asyncio.run(inspect())
    display(result)
    if not result.get("database_ready") or (
        live
        and any(
            not result.get(check)
            for check in ("provider_json", "provider_tool_roundtrip", "search_mcp", "reader_mcp")
        )
    ):
        raise typer.Exit(1)


@app.command("run")
def submit(
    user_request: Annotated[str, typer.Argument(help="Objective for the organization")],
    workspace: Annotated[Path | None, typer.Option(exists=True, file_okay=False)] = None,
    constitution: Annotated[Path | None, typer.Option(exists=True, dir_okay=False)] = None,
):
    """Queue an objective; a worker must be running to execute it."""
    body = {"user_request": user_request}
    if workspace:
        body["workspace_path"] = str(workspace.resolve())
    if constitution:
        try:
            body["constitution"] = json.loads(constitution.read_text())
        except (ValueError, OSError):
            typer.echo("Constitution must be a readable JSON document.", err=True)
            raise typer.Exit(1) from None
    display(request("POST", "/api/runs", body=body))


@app.command()
def status(run_id: str | None = None):
    """List runs or inspect one run."""
    display(request("GET", f"/api/runs/{run_id}" if run_id else "/api/runs"))


@app.command()
def pause(run_id: str):
    display(request("POST", f"/api/runs/{run_id}/pause"))


@app.command()
def cancel(run_id: str):
    display(request("POST", f"/api/runs/{run_id}/cancel"))


@app.command()
def regenesis(
    confirm: Annotated[
        str, typer.Option(help="Type REGENESIS to erase all managed harness state.")
    ],
):
    """Erase harness runs, evidence, checkpoints and settings; keep external workspaces."""
    if confirm != "REGENESIS":
        raise typer.BadParameter("Type REGENESIS to confirm erasing harness data")
    display(request("POST", "/api/regenesis", body={"confirmation": confirm}))


@app.command()
def resume(
    run_id: str,
    action: str = "continue",
    context: str | None = None,
    kr_id: str | None = None,
    description: str | None = None,
    criterion: Annotated[list[str] | None, typer.Option()] = None,
):
    """Resolve the current review; repeat --criterion for a revised KR."""
    run = request("GET", f"/api/runs/{run_id}")
    review = run.get("review") or {}
    body = {"interrupt_id": review.get("interrupt_id", "pause"), "action": action}
    for key, value in {
        "context": context,
        "kr_id": kr_id,
        "description": description,
        "acceptance_criteria": criterion,
    }.items():
        if value is not None:
            body[key] = value
    display(request("POST", f"/api/runs/{run_id}/resume", body=body))


if __name__ == "__main__":
    app()
