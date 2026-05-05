"""OpenCode agent: writes opencode.json with two Databricks-backed providers."""

from __future__ import annotations

import signal
import subprocess
import threading
from pathlib import Path

from coding_tool_gateway.config_io import (
    APP_DIR,
    ToolSpec,
    backup_existing_file,
    deep_merge_dict,
    read_json_safe,
    write_json_file,
)
from coding_tool_gateway.databricks import (
    TOKEN_REFRESH_INTERVAL_SECONDS,
    build_opencode_base_urls,
    get_databricks_token,
)
from coding_tool_gateway.state import mark_tool_managed, save_state

OPENCODE_CONFIG_DIR = Path.home() / ".config" / "opencode"
OPENCODE_CONFIG_PATH = OPENCODE_CONFIG_DIR / "opencode.json"
OPENCODE_BACKUP_PATH = APP_DIR / "opencode-config.backup.json"

SPEC: ToolSpec = {
    "binary": "opencode",
    "package": "opencode-ai",
    "display": "OpenCode",
    "config_path": OPENCODE_CONFIG_PATH,
    "backup_path": OPENCODE_BACKUP_PATH,
}

PROVIDER_KEYS: list[list[str]] = [
    ["provider", "databricks-anthropic"],
    ["provider", "databricks-google"],
]


def render_overlay(
    model: str,
    token: str,
    opencode_base_urls: dict[str, str],
    opencode_models: dict[str, list[str]],
) -> tuple[dict, list[list[str]]]:
    """Return (overlay, managed_key_paths) for opencode.json."""
    auth_headers = {"Authorization": f"Bearer {token}"}

    anthropic_models = opencode_models.get("anthropic") or []
    gemini_models = opencode_models.get("gemini") or []

    providers: dict = {}
    keys: list[list[str]] = [["model"]]
    if anthropic_models:
        providers["databricks-anthropic"] = {
            "npm": "@ai-sdk/anthropic",
            "options": {
                "baseURL": opencode_base_urls["anthropic"],
                "apiKey": token,
                "headers": auth_headers,
            },
            "models": {m: {} for m in anthropic_models},
        }
        keys.append(["provider", "databricks-anthropic"])
    if gemini_models:
        providers["databricks-google"] = {
            "npm": "@ai-sdk/google",
            "options": {
                "baseURL": opencode_base_urls["gemini"],
                "apiKey": token,
                "headers": auth_headers,
            },
            "models": {m: {} for m in gemini_models},
        }
        keys.append(["provider", "databricks-google"])

    overlay: dict = {"model": model}
    if providers:
        overlay["provider"] = providers
    return overlay, keys


def write_tool_config(
    state: dict,
    model: str,
    token: str | None = None,
) -> tuple[dict, str]:
    backup_existing_file(OPENCODE_CONFIG_PATH, OPENCODE_BACKUP_PATH)
    if token is None:
        token = get_databricks_token(state["workspace"])
    opencode_base_urls = state.get("base_urls", {}).get("opencode") or build_opencode_base_urls(
        state["workspace"]
    )
    overlay, managed_keys = render_overlay(
        model,
        token,
        opencode_base_urls,
        state.get("opencode_models") or {},
    )
    existing = read_json_safe(OPENCODE_CONFIG_PATH)
    providers = existing.get("provider")
    if isinstance(providers, dict):
        for stale in ("databricks-anthropic", "databricks-google"):
            providers.pop(stale, None)
    merged = deep_merge_dict(existing, overlay)
    write_json_file(OPENCODE_CONFIG_PATH, merged)
    state = mark_tool_managed(state, "opencode", managed_keys)
    save_state(state)
    return state, token


def default_model(state: dict) -> str | None:
    opencode_models = state.get("opencode_models") or {}
    anthropic = opencode_models.get("anthropic") or []
    if anthropic:
        return anthropic[0]
    gemini = opencode_models.get("gemini") or []
    return gemini[0] if gemini else None


def _refresh_token_once(state: dict) -> str:
    model = default_model(state)
    if not model:
        raise RuntimeError("No OpenCode model is configured.")
    _, token = write_tool_config(state, model)
    return token


def _refresh_forever(state: dict, stop_event: threading.Event) -> None:
    while not stop_event.wait(TOKEN_REFRESH_INTERVAL_SECONDS):
        try:
            _refresh_token_once(state)
        except RuntimeError:
            continue


def launch(state: dict, tool_args: list[str]) -> None:
    """Launch opencode with background token refresh (same pattern as Gemini)."""
    _refresh_token_once(state)

    stop_event = threading.Event()
    refresher = threading.Thread(
        target=_refresh_forever,
        args=(state, stop_event),
        daemon=True,
    )
    refresher.start()

    proc = subprocess.Popen([SPEC["binary"], *tool_args])
    try:
        returncode = proc.wait()
    except KeyboardInterrupt:
        proc.send_signal(signal.SIGINT)
        returncode = proc.wait()
    finally:
        stop_event.set()
        refresher.join(timeout=1)

    raise SystemExit(returncode)


def validate_cmd(binary: str) -> list[str]:
    return [binary, "run", "say hi in 5 words or less"]
