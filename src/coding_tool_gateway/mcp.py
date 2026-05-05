"""MCP (Model Context Protocol) server registration for Claude Code."""

from __future__ import annotations

import json
import os
import shutil
import subprocess

from coding_tool_gateway.databricks import ensure_databricks_auth
from coding_tool_gateway.state import load_state, save_state
from coding_tool_gateway.ui import (
    console,
    label,
    muted,
    print_err,
    print_heading,
    print_note,
    print_section,
    print_success,
    prompt_for_choice,
    prompt_for_client_id,
    prompt_for_client_secret,
)


def build_mcp_http_entry(url: str, client_id: str, callback_port: int = 8080) -> dict:
    return {
        "type": "http",
        "url": url,
        "oauth": {
            "clientId": client_id,
            "callbackPort": callback_port,
        },
    }


def add_claude_mcp_server(name: str, entry: dict, client_secret: str) -> None:
    env = os.environ.copy()
    env["MCP_CLIENT_SECRET"] = client_secret
    try:
        subprocess.run(
            [
                "claude",
                "mcp",
                "add-json",
                name,
                json.dumps(entry),
                "--client-secret",
            ],
            check=True,
            env=env,
            timeout=30,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"Failed to add MCP server '{name}' via claude CLI.") from exc


def configure_mcp_command() -> int:
    state = load_state()
    workspace = state.get("workspace")
    if not workspace:
        raise RuntimeError("Workspace is not configured. Run `coding-gateway configure` first.")

    if not shutil.which("claude"):
        raise RuntimeError(
            "`claude` CLI is not installed. Install it with: npm install -g @anthropic-ai/claude-code"
        )

    ensure_databricks_auth(workspace)

    print_section("MCP Server Configuration")
    print_note("Configure Claude Code to connect to Databricks MCP servers.")
    print_note(f"Workspace: {workspace}")

    print_heading("OAuth Credentials")
    print_note("These will be used for all MCP servers added in this session.")
    client_id = prompt_for_client_id()
    client_secret = prompt_for_client_secret()

    state["mcp_oauth"] = {"client_id": client_id, "client_secret": client_secret}
    mcp_servers: list[dict] = list(state.get("mcp_servers") or [])

    added: list[str] = []

    print_section("Add MCP Server")
    while True:
        selection = prompt_for_choice(
            "Select server type",
            [
                ("external", "External MCP server (e.g. confluence-mcp, jira-mcp)"),
                ("uc-functions", "UC Functions (Unity Catalog AI functions)"),
                ("genie", "Genie (AI/BI dashboard)"),
                ("custom", "Custom MCP server URL"),
                ("done", "Done — exit"),
            ],
        )

        if selection == "done":
            break

        if selection == "external":
            server_name = console.input(
                f"  {label('MCP server name')} {muted('(e.g. confluence-mcp, jira-mcp)')} {muted('›')} "
            ).strip()
            if not server_name:
                print_err("Server name cannot be empty.")
                continue
            url = f"{workspace}/api/2.0/mcp/external/{server_name}"
            entry_name = server_name

        elif selection == "uc-functions":
            catalog = console.input(f"  {label('Catalog name')} {muted('›')} ").strip()
            schema = console.input(f"  {label('Schema name')} {muted('›')} ").strip()
            if not catalog or not schema:
                print_err("Catalog and schema cannot be empty.")
                continue
            url = f"{workspace}/api/2.0/mcp/functions/{catalog}/{schema}"
            entry_name = f"databricks-uc-{catalog}-{schema}"

        elif selection == "genie":
            space_id = console.input(f"  {label('Genie space ID')} {muted('›')} ").strip()
            if not space_id:
                print_err("Space ID cannot be empty.")
                continue
            url = f"{workspace}/api/2.0/mcp/genie/{space_id}"
            entry_name = f"databricks-genie-{space_id}"

        elif selection == "custom":
            url = console.input(f"  {label('Full MCP server URL')} {muted('›')} ").strip()
            if not url:
                print_err("URL cannot be empty.")
                continue
            entry_name = console.input(f"  {label('Server name')} {muted('›')} ").strip()
            if not entry_name:
                print_err("Server name cannot be empty.")
                continue

        else:
            continue

        entry = build_mcp_http_entry(url, client_id)
        add_claude_mcp_server(entry_name, entry, client_secret)
        added.append(entry_name)
        mcp_servers.append(
            {
                "name": entry_name,
                "url": url,
                "client_id": client_id,
                "client_secret": client_secret,
            }
        )
        state["mcp_servers"] = mcp_servers
        save_state(state)
        print_success(f"Added {entry_name}")

    if not added:
        print_note("No MCP servers added.")
        return 0

    print_heading("MCP Configured")
    for name in added:
        console.print(f"  [bold green]●[/bold green] [cyan]{name}[/cyan]")
    print_success("MCP servers registered via `claude mcp add-json`")
    print_note("Run `claude mcp list` to see all configured servers.")
    return 0
