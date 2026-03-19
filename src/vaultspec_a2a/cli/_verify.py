"""Prod-like Docker verification helpers for the CLI."""

from __future__ import annotations

import atexit
import http.client
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from urllib import error, parse, request

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_PRODLIKE_COMPOSE_FILES = (
    "docker-compose.prod.yml",
    "docker-compose.prod.postgres.yml",
)
_PROVIDER_COMPOSE_FILES = (
    "docker-compose.prod.yml",
    "docker-compose.prod.postgres.yml",
    "docker-compose.prod.providers.yml",
)
_HEALTH_URL = "http://localhost:8000/api/health"
_THREADS_URL = "http://localhost:8000/api/threads"
_JAEGER_QUERY_URL = "http://localhost:16686/api/traces"
_DEFAULT_INTERNAL_TOKEN = "vaultspec-internal-test-token"
_TRACE_SERVICES = ("vaultspec-a2a", "vaultspec-worker")
_PRODLIKE_TRACE_SERVICES = ("vaultspec-a2a",)
_LOG_SERVICES = ("gateway", "worker", "postgres", "jaeger")
_ARTIFACT_ROOT = _ROOT / ".vault" / "runtime" / "verify-prodlike-docker"
_SUPPORTED_PROVIDERS = frozenset({"claude", "gemini"})
_JAEGER_TRACE_LOOKBACK = "1h"
_DOCKER_GEMINI_CLI_HOME = "/gemini-cli-home"
_EMPTY_GEMINI_CLI_HOME = _ROOT / ".vault" / "runtime" / "empty-gemini-cli-home"
_DOCKER_PROVIDER_PROBE_WORKDIR = "/tmp"
_ISOLATED_GEMINI_DIR_NAME = ".gemini"
_ISOLATED_GEMINI_HOME_CACHE: dict[str, Path] = {}
_ISOLATED_GEMINI_HOME_PATHS: set[Path] = set()


def _compose_cmd(compose_files: tuple[str, ...], *args: str) -> list[str]:
    cmd = ["docker", "compose"]
    for compose_file in compose_files:
        cmd.extend(["-f", compose_file])
    cmd.extend(args)
    return cmd


def _provider_probe_exec_cmd(provider: str) -> list[str]:
    return _compose_cmd(
        _PROVIDER_COMPOSE_FILES,
        "exec",
        "-T",
        "-w",
        _DOCKER_PROVIDER_PROBE_WORKDIR,
        "worker",
        "/app/.venv/bin/python",
        "-m",
        f"vaultspec_a2a.providers.probes.{provider}",
    )


def _cleanup_isolated_gemini_homes() -> None:
    while _ISOLATED_GEMINI_HOME_PATHS:
        path = _ISOLATED_GEMINI_HOME_PATHS.pop()
        shutil.rmtree(path, ignore_errors=True)


def _extract_gemini_auth_settings(source_home: Path) -> dict[str, object]:
    settings_path = source_home / _ISOLATED_GEMINI_DIR_NAME / "settings.json"
    if not settings_path.exists():
        return {"security": {"auth": {"selectedType": "oauth-personal"}}}

    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {"security": {"auth": {"selectedType": "oauth-personal"}}}

    selected_type = (
        payload.get("security", {}) if isinstance(payload.get("security"), dict) else {}
    )
    selected_type = (
        selected_type.get("auth", {}) if isinstance(selected_type, dict) else {}
    )
    selected_type = (
        selected_type.get("selectedType")
        if isinstance(selected_type, dict)
        else "oauth-personal"
    )
    if not isinstance(selected_type, str) or not selected_type.strip():
        selected_type = "oauth-personal"
    return {"security": {"auth": {"selectedType": selected_type}}}


def _prepare_isolated_gemini_host_cli_home(source_home: Path) -> Path:
    cache_key = str(source_home.resolve())
    cached = _ISOLATED_GEMINI_HOME_CACHE.get(cache_key)
    if cached is not None:
        return cached

    isolated_home = Path(tempfile.mkdtemp(prefix="vaultspec-gemini-cli-home-"))
    isolated_gemini_dir = isolated_home / _ISOLATED_GEMINI_DIR_NAME
    isolated_gemini_dir.mkdir(parents=True, exist_ok=True)

    source_gemini_dir = source_home / _ISOLATED_GEMINI_DIR_NAME
    for filename in ("oauth_creds.json", "google_accounts.json"):
        source = source_gemini_dir / filename
        if source.exists():
            (isolated_gemini_dir / filename).write_text(
                source.read_text(encoding="utf-8"),
                encoding="utf-8",
            )

    auth_settings = _extract_gemini_auth_settings(source_home)
    (isolated_gemini_dir / "settings.json").write_text(
        json.dumps(auth_settings, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    _ISOLATED_GEMINI_HOME_CACHE[cache_key] = isolated_home
    _ISOLATED_GEMINI_HOME_PATHS.add(isolated_home)
    return isolated_home


def _compose_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("VAULTSPEC_INTERNAL_TOKEN", _DEFAULT_INTERNAL_TOKEN)
    env.setdefault("COMPOSE_DISABLE_ENV_FILE", "1")
    env.setdefault("VAULTSPEC_LOG_LEVEL", "DEBUG")
    env.setdefault("PYTHONUNBUFFERED", "1")
    host_cli_home = _resolve_gemini_host_cli_home(env)
    env.setdefault("GEMINI_CLI_HOME", _DOCKER_GEMINI_CLI_HOME)
    if host_cli_home is None:
        _EMPTY_GEMINI_CLI_HOME.mkdir(parents=True, exist_ok=True)
        host_cli_home = _EMPTY_GEMINI_CLI_HOME
    else:
        host_cli_home = _prepare_isolated_gemini_host_cli_home(host_cli_home)
    env.setdefault("GEMINI_HOST_CLI_HOME", str(host_cli_home))
    return env


def _artifact_dir() -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    artifact_dir = _ARTIFACT_ROOT / timestamp
    artifact_dir.mkdir(parents=True, exist_ok=True)
    return artifact_dir


atexit.register(_cleanup_isolated_gemini_homes)


def _iso_utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _run_compose(
    compose_files: tuple[str, ...], *args: str, capture: bool = False
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        _compose_cmd(compose_files, *args),
        cwd=_ROOT,
        env=_compose_env(),
        check=True,
        text=True,
        capture_output=capture,
    )


def _read_json(
    url: str,
    *,
    method: str = "GET",
    body: dict[str, object] | None = None,
) -> dict[str, object]:
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = request.Request(url, data=data, headers=headers, method=method)
    with request.urlopen(req, timeout=2) as response:
        return json.loads(response.read().decode("utf-8"))


def _write_text(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")


def _write_json(path: Path, payload: object) -> None:
    _write_text(path, json.dumps(payload, indent=2, sort_keys=True))


def _summarize_health(health: dict[str, object]) -> dict[str, object]:
    keys = (
        "status",
        "database_backend",
        "checkpoint_backend",
        "worker_connected",
        "worker_status",
        "circuit_breaker",
    )
    return {key: health[key] for key in keys if key in health}


def _capture_health_probe(
    url: str,
) -> tuple[dict[str, object], dict[str, object] | None]:
    probe: dict[str, object] = {
        "timestamp": _iso_utc_now(),
        "url": url,
    }
    try:
        health = _read_json(url)
    except (
        OSError,
        error.URLError,
        http.client.HTTPException,
        json.JSONDecodeError,
    ) as exc:
        probe["ok"] = False
        probe["error"] = str(exc)
        return probe, None
    probe["response"] = _summarize_health(health)
    probe["ok"] = health.get("status") == "ok"
    return probe, health


def _wait_for_health(
    *,
    url: str = _HEALTH_URL,
    max_attempts: int = 60,
    sleep_seconds: float = 2.0,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    probe_history: list[dict[str, object]] = []
    last_error: str | None = None
    for _ in range(max_attempts):
        probe, health = _capture_health_probe(url)
        probe_history.append(probe)
        if health is not None and health.get("status") == "ok":
            return health, probe_history
        if "error" in probe:
            last_error = str(probe["error"])
        else:
            last_error = json.dumps(probe.get("response", {}), indent=2, sort_keys=True)
        time.sleep(sleep_seconds)
    total_seconds = int(max_attempts * sleep_seconds)
    raise RuntimeError(f"gateway not ready after {total_seconds}s: {last_error}")


def _jaeger_trace_query_url(
    service: str,
    *,
    query_url: str = _JAEGER_QUERY_URL,
    lookback: str = _JAEGER_TRACE_LOOKBACK,
    limit: int = 20,
) -> str:
    params = {
        "service": service,
        "lookback": lookback,
        "limit": limit,
    }
    return f"{query_url}?{parse.urlencode(params)}"


def _wait_for_traces(
    *,
    services: tuple[str, ...],
    query_url: str = _JAEGER_QUERY_URL,
    lookback: str = _JAEGER_TRACE_LOOKBACK,
) -> dict[str, dict[str, object]]:
    last_results: dict[str, dict[str, object]] = {}
    for _ in range(30):
        all_present = True
        for service in services:
            result = _read_json(
                _jaeger_trace_query_url(
                    service,
                    query_url=query_url,
                    lookback=lookback,
                )
            )
            last_results[service] = result
            if not result.get("data"):
                all_present = False
        if all_present:
            return last_results
        time.sleep(2)
    missing = [
        service for service, result in last_results.items() if not result.get("data")
    ]
    raise RuntimeError(
        "Jaeger trace verification failed; no traces found for services: "
        + ", ".join(sorted(missing))
    )


def _verify_health(health: dict[str, object]) -> None:
    if health.get("database_backend") != "postgres":
        raise RuntimeError(f"expected database_backend=postgres, got {health!r}")
    if health.get("checkpoint_backend") != "postgres":
        raise RuntimeError(f"expected checkpoint_backend=postgres, got {health!r}")


def _verify_thread_flow() -> str:
    thread = _read_json(
        _THREADS_URL,
        method="POST",
        body={
            "initial_message": "Prod-like docker verification thread.",
            "autonomous": False,
        },
    )
    thread_id = thread.get("thread_id")
    if not isinstance(thread_id, str) or not thread_id:
        raise RuntimeError(f"thread creation failed: {thread!r}")
    state = _read_json(f"{_THREADS_URL}/{thread_id}/state")
    if state.get("thread_id") != thread_id:
        raise RuntimeError(f"state lookup failed: {state!r}")
    return thread_id


def _capture_compose_logs(
    artifact_dir: Path, *, compose_files: tuple[str, ...], services: tuple[str, ...]
) -> None:
    try:
        compose_ps = _run_compose(compose_files, "ps", capture=True).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        compose_ps = f"compose ps failed: {exc}"
    _write_text(artifact_dir / "compose.ps.txt", compose_ps)
    for service in services:
        try:
            result = _run_compose(
                compose_files,
                "logs",
                "--no-color",
                "--timestamps",
                service,
                capture=True,
            )
            contents = result.stdout
        except (OSError, subprocess.CalledProcessError) as exc:
            contents = f"compose logs failed for {service}: {exc}"
        _write_text(artifact_dir / f"{service}.log", contents)


def _capture_compose_config(
    artifact_dir: Path, *, compose_files: tuple[str, ...]
) -> None:
    try:
        compose_config = _run_compose(compose_files, "config", capture=True).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        compose_config = f"compose config failed: {exc}"
    _write_text(artifact_dir / "compose.config.yaml", compose_config)


def _capture_container_inspect(
    artifact_dir: Path, *, compose_files: tuple[str, ...], services: tuple[str, ...]
) -> None:
    for service in services:
        try:
            result = _run_compose(compose_files, "ps", "-q", service, capture=True)
            container_ids = [
                line.strip() for line in result.stdout.splitlines() if line.strip()
            ]
            if not container_ids:
                _write_json(
                    artifact_dir / f"{service}.inspect.json",
                    {
                        "service": service,
                        "container_ids": [],
                        "error": "no container ids returned",
                    },
                )
                continue
            inspect_result = subprocess.run(
                ["docker", "inspect", *container_ids],
                cwd=_ROOT,
                env=_compose_env(),
                check=True,
                text=True,
                capture_output=True,
            )
            _write_text(
                artifact_dir / f"{service}.inspect.json",
                inspect_result.stdout,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            _write_json(
                artifact_dir / f"{service}.inspect.json",
                {
                    "service": service,
                    "error": str(exc),
                },
            )


def _extract_trace_ids(result: dict[str, Any]) -> list[str]:
    data = result.get("data")
    if not isinstance(data, list):
        return []
    trace_ids: list[str] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        trace_id = item.get("traceID")
        if isinstance(trace_id, str) and trace_id:
            trace_ids.append(trace_id)
    return trace_ids


def _capture_jaeger_diagnostics(
    artifact_dir: Path,
    *,
    start_ms: int,
    services: tuple[str, ...] = _TRACE_SERVICES,
    trace_results: dict[str, dict[str, object]] | None = None,
    query_url: str = _JAEGER_QUERY_URL,
    lookback: str = _JAEGER_TRACE_LOOKBACK,
) -> dict[str, object]:
    end_ms = int(time.time() * 1000)
    trace_manifest: dict[str, object] = {
        "start_ms": start_ms,
        "end_ms": end_ms,
        "lookback": lookback,
        "services": list(services),
    }
    for service in services:
        if trace_results is not None and service in trace_results:
            result = trace_results[service]
        else:
            try:
                result = _read_json(
                    _jaeger_trace_query_url(
                        service,
                        query_url=query_url,
                        lookback=lookback,
                    )
                )
            except Exception as exc:  # pragma: no cover - diagnostics-only path
                result = {"error": str(exc)}
        _write_json(artifact_dir / f"jaeger-{service}.json", result)
        trace_ids = _extract_trace_ids(result) if isinstance(result, dict) else []
        trace_manifest[service] = {
            "trace_count": len(trace_ids),
            "trace_ids": trace_ids,
            "artifact": f"jaeger-{service}.json",
        }
    _write_json(artifact_dir / "trace-manifest.json", trace_manifest)
    return trace_manifest


def _write_provider_probe_artifacts(
    artifact_dir: Path,
    *,
    provider: str,
    result: subprocess.CompletedProcess[str] | None = None,
    error: str | None = None,
) -> dict[str, object]:
    artifact_payload: dict[str, object] = {"provider": provider}
    if result is not None:
        _write_text(artifact_dir / f"{provider}.probe.stdout.txt", result.stdout)
        _write_text(artifact_dir / f"{provider}.probe.stderr.txt", result.stderr)
        artifact_payload["returncode"] = result.returncode
        artifact_payload["stdout_artifact"] = f"{provider}.probe.stdout.txt"
        artifact_payload["stderr_artifact"] = f"{provider}.probe.stderr.txt"
    if error is not None:
        artifact_payload["error"] = error
    _write_json(artifact_dir / f"{provider}.probe.json", artifact_payload)
    return artifact_payload


def _write_evidence_manifest(
    artifact_dir: Path,
    *,
    compose_files: tuple[str, ...],
    services: tuple[str, ...],
    probe_history: list[dict[str, object]],
    trace_manifest: dict[str, object] | None = None,
    trace_services: tuple[str, ...] = (),
    run_context: dict[str, object] | None = None,
) -> None:
    run_context = run_context or {}
    raw_health = run_context.get("health")
    health: dict[str, object] | None = (
        cast("dict[str, object]", raw_health) if isinstance(raw_health, dict) else None
    )
    thread_id = run_context.get("thread_id")
    failure = run_context.get("failure")
    provider = run_context.get("provider")
    provider_probe = run_context.get("provider_probe")
    service_artifacts = {
        service: {
            "log": f"{service}.log",
            "inspect": f"{service}.inspect.json",
        }
        for service in services
    }
    evidence_manifest: dict[str, object] = {
        "run_id": artifact_dir.name,
        "generated_at": _iso_utc_now(),
        "compose_files": list(compose_files),
        "thread_id": thread_id,
        "provider": provider,
        "failure": failure,
        "health": _summarize_health(health) if health is not None else None,
        "readiness_probe_count": len(probe_history),
        "artifacts": {
            "compose_ps": "compose.ps.txt",
            "compose_config": "compose.config.yaml",
            "readiness_probes": "readiness-probes.json",
            "health": "health.json" if health is not None else None,
            "thread": "thread.json" if thread_id is not None else None,
            "failure": "failure.json" if failure is not None else None,
            "trace_manifest": (
                "trace-manifest.json" if trace_manifest is not None else None
            ),
            "provider_probe": (
                f"{provider}.probe.json"
                if provider is not None and provider_probe is not None
                else None
            ),
        },
        "services": service_artifacts,
    }
    if trace_manifest is not None:
        evidence_manifest["trace_services"] = {
            service: trace_manifest.get(service)
            for service in trace_services
            if service in trace_manifest
        }
    if provider_probe is not None:
        evidence_manifest["provider_probe"] = provider_probe
    _write_json(artifact_dir / "evidence-manifest.json", evidence_manifest)


def _resolve_gemini_host_cli_home(
    env: dict[str, str] | None = None,
) -> Path | None:
    source = env or os.environ
    cli_home = source.get("GEMINI_CLI_HOME")
    base = Path(cli_home) if cli_home and cli_home.strip() else Path.home()
    creds_path = base / ".gemini" / "oauth_creds.json"
    return base if creds_path.exists() else None


def _require_provider_auth(provider: str) -> None:
    if provider == "claude":
        if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
            return
        raise RuntimeError(
            "CLAUDE_CODE_OAUTH_TOKEN is required for Docker Claude provider "
            "verification."
        )
    if provider == "gemini":
        if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
            return
        if _resolve_gemini_host_cli_home() is not None:
            return
        raise RuntimeError(
            "Docker Gemini provider verification requires GEMINI_API_KEY, "
            "GOOGLE_API_KEY, or a local Gemini OAuth session under "
            "GEMINI_CLI_HOME/.gemini (defaulting to ~/.gemini)."
        )


def verify_prodlike_docker() -> int:
    """Run the prod-like Docker/Postgres verification flow end to end."""
    artifact_dir = _artifact_dir()
    start_ms = int(time.time() * 1000)
    health: dict[str, object] | None = None
    thread_id: str | None = None
    failure: str | None = None
    probe_history: list[dict[str, object]] = []
    try:
        _run_compose(
            _PRODLIKE_COMPOSE_FILES,
            "up",
            "-d",
            "--build",
            "postgres",
            "jaeger",
            "worker",
            "gateway",
        )
        health, probe_history = _wait_for_health()
        _verify_health(health)
        thread_id = _verify_thread_flow()
        trace_results = _wait_for_traces(services=_PRODLIKE_TRACE_SERVICES)
        _write_json(artifact_dir / "health.json", health)
        _write_json(artifact_dir / "readiness-probes.json", probe_history)
        _write_json(artifact_dir / "thread.json", {"thread_id": thread_id})
        trace_manifest = _capture_jaeger_diagnostics(
            artifact_dir,
            start_ms=start_ms,
            services=_PRODLIKE_TRACE_SERVICES,
            trace_results=trace_results,
        )
        _capture_compose_config(artifact_dir, compose_files=_PRODLIKE_COMPOSE_FILES)
        _capture_compose_logs(
            artifact_dir,
            compose_files=_PRODLIKE_COMPOSE_FILES,
            services=_LOG_SERVICES,
        )
        _capture_container_inspect(
            artifact_dir,
            compose_files=_PRODLIKE_COMPOSE_FILES,
            services=_LOG_SERVICES,
        )
        _write_evidence_manifest(
            artifact_dir,
            compose_files=_PRODLIKE_COMPOSE_FILES,
            services=_LOG_SERVICES,
            probe_history=probe_history,
            trace_manifest=trace_manifest,
            trace_services=_PRODLIKE_TRACE_SERVICES,
            run_context={
                "health": health,
                "thread_id": thread_id,
            },
        )
        sys.stdout.write(f"verify-prodlike-docker artifacts: {artifact_dir}\n")
    except Exception as exc:
        failure = str(exc)
        _write_json(artifact_dir / "readiness-probes.json", probe_history)
        _capture_compose_config(artifact_dir, compose_files=_PRODLIKE_COMPOSE_FILES)
        _capture_compose_logs(
            artifact_dir,
            compose_files=_PRODLIKE_COMPOSE_FILES,
            services=_LOG_SERVICES,
        )
        _capture_container_inspect(
            artifact_dir,
            compose_files=_PRODLIKE_COMPOSE_FILES,
            services=_LOG_SERVICES,
        )
        if health is not None:
            _write_json(artifact_dir / "health.json", health)
        if thread_id is not None:
            _write_json(artifact_dir / "thread.json", {"thread_id": thread_id})
        _write_json(artifact_dir / "failure.json", {"error": failure})
        trace_manifest = _capture_jaeger_diagnostics(
            artifact_dir,
            start_ms=start_ms,
            services=_PRODLIKE_TRACE_SERVICES,
        )
        _write_evidence_manifest(
            artifact_dir,
            compose_files=_PRODLIKE_COMPOSE_FILES,
            services=_LOG_SERVICES,
            probe_history=probe_history,
            trace_manifest=trace_manifest,
            trace_services=_PRODLIKE_TRACE_SERVICES,
            run_context={
                "health": health,
                "thread_id": thread_id,
                "failure": failure,
            },
        )
        sys.stderr.write(f"verify-prodlike-docker failure artifacts: {artifact_dir}\n")
        raise
    finally:
        subprocess.run(
            _compose_cmd(_PRODLIKE_COMPOSE_FILES, "down", "-v"),
            cwd=_ROOT,
            env=_compose_env(),
            check=False,
        )
    return 0


def verify_prodlike_docker_provider(provider: str) -> int:
    """Run a real provider probe inside the prod-like Docker worker."""
    if provider not in _SUPPORTED_PROVIDERS:
        supported = ", ".join(sorted(_SUPPORTED_PROVIDERS))
        raise RuntimeError(f"provider must be one of: {supported}")

    _require_provider_auth(provider)
    artifact_dir = _artifact_dir()
    start_ms = int(time.time() * 1000)
    health: dict[str, object] | None = None
    failure: str | None = None
    probe_history: list[dict[str, object]] = []
    provider_result: subprocess.CompletedProcess[str] | None = None
    try:
        _run_compose(
            _PROVIDER_COMPOSE_FILES,
            "up",
            "-d",
            "--build",
            "postgres",
            "jaeger",
            "worker",
            "gateway",
        )
        health, probe_history = _wait_for_health()
        _verify_health(health)
        provider_result = subprocess.run(
            _provider_probe_exec_cmd(provider),
            cwd=_ROOT,
            env=_compose_env(),
            check=False,
            text=True,
            capture_output=True,
        )
        provider_probe = _write_provider_probe_artifacts(
            artifact_dir,
            provider=provider,
            result=provider_result,
        )
        _write_json(artifact_dir / "health.json", health)
        _write_json(artifact_dir / "readiness-probes.json", probe_history)
        _capture_compose_config(artifact_dir, compose_files=_PROVIDER_COMPOSE_FILES)
        _capture_compose_logs(
            artifact_dir,
            compose_files=_PROVIDER_COMPOSE_FILES,
            services=_LOG_SERVICES,
        )
        _capture_container_inspect(
            artifact_dir,
            compose_files=_PROVIDER_COMPOSE_FILES,
            services=_LOG_SERVICES,
        )
        trace_manifest = _capture_jaeger_diagnostics(
            artifact_dir,
            start_ms=start_ms,
            services=_TRACE_SERVICES,
        )
        _write_evidence_manifest(
            artifact_dir,
            compose_files=_PROVIDER_COMPOSE_FILES,
            services=_LOG_SERVICES,
            probe_history=probe_history,
            trace_manifest=trace_manifest,
            trace_services=_TRACE_SERVICES,
            run_context={
                "health": health,
                "provider": provider,
                "provider_probe": provider_probe,
            },
        )
        if provider_result.returncode != 0:
            raise RuntimeError(
                f"{provider} provider probe failed with exit code "
                f"{provider_result.returncode}"
            )
        sys.stdout.write(
            f"verify-prodlike-provider ({provider}) artifacts: {artifact_dir}\n"
        )
    except Exception as exc:
        failure = str(exc)
        _write_json(artifact_dir / "readiness-probes.json", probe_history)
        if health is not None:
            _write_json(artifact_dir / "health.json", health)
        _capture_compose_config(artifact_dir, compose_files=_PROVIDER_COMPOSE_FILES)
        _capture_compose_logs(
            artifact_dir,
            compose_files=_PROVIDER_COMPOSE_FILES,
            services=_LOG_SERVICES,
        )
        _capture_container_inspect(
            artifact_dir,
            compose_files=_PROVIDER_COMPOSE_FILES,
            services=_LOG_SERVICES,
        )
        provider_probe = _write_provider_probe_artifacts(
            artifact_dir,
            provider=provider,
            result=provider_result,
            error=failure,
        )
        _write_json(artifact_dir / "failure.json", {"error": failure})
        trace_manifest = _capture_jaeger_diagnostics(
            artifact_dir,
            start_ms=start_ms,
            services=_TRACE_SERVICES,
        )
        _write_evidence_manifest(
            artifact_dir,
            compose_files=_PROVIDER_COMPOSE_FILES,
            services=_LOG_SERVICES,
            probe_history=probe_history,
            trace_manifest=trace_manifest,
            trace_services=_TRACE_SERVICES,
            run_context={
                "health": health,
                "failure": failure,
                "provider": provider,
                "provider_probe": provider_probe,
            },
        )
        sys.stderr.write(
            f"verify-prodlike-provider ({provider}) failure artifacts: {artifact_dir}\n"
        )
        raise
    finally:
        subprocess.run(
            _compose_cmd(_PROVIDER_COMPOSE_FILES, "down", "-v"),
            cwd=_ROOT,
            env=_compose_env(),
            check=False,
        )
    return 0
