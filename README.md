# voxcode — Van Oord OpenCode Launcher

`voxcode` is a thin CLI launcher that wraps [OpenCode](https://opencode.ai) and routes all LLM traffic through the Databricks AI Gateway on your workspace. No vendor API keys required — authentication is handled via Databricks OAuth or PAT.

---

## What voxcode DOES

### Core function
- **Launches OpenCode CLI** (`opencode` binary) pre-configured to use Databricks AI Gateway as the LLM backend
- **Manages OAuth tokens** — authenticates via `databricks auth login`, refreshes tokens automatically in a background thread every 30 minutes while OpenCode runs
- **Discovers available models** — queries the AI Gateway for Claude (Anthropic) and Gemini (Google) foundation model endpoints
- **Enforces a platform-team allowlist** — only models listed in `src/voxcode/allowed_models.py` are discoverable and launchable. Users cannot bypass this.
- **Writes OpenCode config** — generates `~/.voxcode/opencode-xdg/opencode/opencode.json` with provider URLs, tokens, and model selections before each launch

### Authentication
- **OAuth (default)** — runs `databricks auth login` interactively, caches session in Databricks CLI profiles (`~/.databrickscfg`)
- **PAT (opt-in)** — `voxcode configure --profiles <name> --use-pat` reads a personal access token from `~/.databrickscfg` for headless/CI environments
- **Token refresh** — background thread calls `databricks auth token --force-refresh` every 30 minutes, rewrites the OpenCode config with the fresh token so long-running sessions never expire

### Multi-workspace support
- Supports multiple Databricks workspaces via `--workspaces` or `--profiles` flags
- State is persisted per-workspace in `~/.voxcode/state.json`
- Switching workspaces auto-cleans MCP entries from the previous workspace

### MCP (Model Context Protocol) server management
- `voxcode configure mcp` — interactive picker to register Databricks-hosted MCP servers with OpenCode:
  - **Databricks SQL** — query warehouse via MCP
  - **External HTTP connections** — UC-registered MCP-compatible HTTP connections
  - **Genie spaces** — natural-language-to-SQL via Genie
  - **Databricks Apps** — apps prefixed with `mcp-` exposed as MCP servers
  - **system.ai.* MCP services** — curated Databricks-managed MCP services
- Registers/removes servers directly in OpenCode's config
- `voxcode mcp web-search` — built-in MCP server providing web search to OpenCode

### MLflow tracing (optional)
- `voxcode configure tracing` — connects OpenCode sessions to a pre-provisioned `ucode-traces` MLflow experiment backed by Unity Catalog
- Sets `MLFLOW_TRACING_SQL_WAREHOUSE_ID` so traces land in a UC table
- Requires an admin to have created the experiment first (voxcode does NOT create it)

### Usage reporting
- `voxcode usage` — queries `system.ai_gateway.usage` via SQL warehouse to show token consumption, cost, and model breakdown

### Auto-install / bootstrap
- Installs the Databricks CLI if missing (via brew/curl/powershell depending on OS)
- Installs OpenCode CLI if missing (via `npm install -g opencode-ai`)
- Checks minimum versions, offers optional upgrades, and handles too-new-version downgrades

### Telemetry
- Injects a `User-Agent` header on all AI Gateway requests: `voxcode/<version> opencode/<opencode_version>`
- No external telemetry — the UA header is visible only to the Databricks AI Gateway logs

### Configuration state
- All state stored in `~/.voxcode/state.json` (workspace, profile, models, MCP servers, available tools)
- OpenCode config at `~/.voxcode/opencode-xdg/opencode/opencode.json`
- Existing configs backed up before overwrite; `voxcode revert` restores them
- `voxcode configure --dry-run` previews changes without writing

---

## What voxcode does NOT do

- **Does NOT provide LLM models** — it only routes to models already provisioned on the Databricks AI Gateway by an admin
- **Does NOT manage AI Gateway endpoints** — if no Claude/Gemini endpoints exist on the workspace, voxcode cannot create them
- **Does NOT create MLflow experiments** — tracing requires an admin-provisioned UC-backed experiment named `ucode-traces`
- **Does NOT store or transmit API keys** — all auth goes through Databricks CLI's OAuth flow or a locally-stored PAT; no keys are sent to third parties
- **Does NOT run code itself** — it launches OpenCode as a subprocess; all code execution happens inside OpenCode
- **Does NOT support agents other than OpenCode** — Claude Code, Codex CLI, Gemini CLI, Copilot CLI, and Pi have been stripped
- **Does NOT bypass the model allowlist** — even if a model endpoint exists on the gateway, it must be in `allowed_models.py` to be used
- **Does NOT require a Databricks cluster** — it runs purely on the user's local machine and talks to the workspace REST APIs
- **Does NOT phone home** — no analytics, no crash reporting, no external network calls beyond the configured Databricks workspace
- **Does NOT manage workspace permissions** — if a user lacks AI Gateway access, voxcode surfaces the error but cannot grant access

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│  User's machine                                          │
│                                                          │
│  voxcode CLI                                             │
│    ├─ authenticate (databricks auth login / PAT)         │
│    ├─ discover models (AI Gateway REST API)              │
│    ├─ filter models (allowed_models.py)                  │
│    ├─ write opencode.json (providers, token, model)      │
│    ├─ launch `opencode` subprocess                       │
│    └─ background token refresh (every 30 min)            │
│                                                          │
│  OpenCode CLI (subprocess)                               │
│    ├─ reads opencode.json for provider config            │
│    ├─ sends LLM requests to AI Gateway endpoints         │
│    └─ optionally talks to MCP servers (SQL, Genie, etc.) │
│                                                          │
└────────────────────────────┬─────────────────────────────┘
                             │ HTTPS (OAuth Bearer)
                             ▼
┌──────────────────────────────────────────────────────────┐
│  Databricks Workspace (AI Gateway v2)                    │
│    ├─ /ai-gateway/anthropic/v1/messages  (Claude)        │
│    ├─ /ai-gateway/gemini/v1beta/...      (Gemini)       │
│    ├─ /api/2.0/mcp/...                   (MCP servers)  │
│    └─ system.ai_gateway.usage            (usage logs)   │
└──────────────────────────────────────────────────────────┘
```

---

## CLI Commands

| Command | Description |
|---------|-------------|
| `voxcode opencode` | Launch OpenCode (auto-configures on first run) |
| `voxcode launch` | Alias for `voxcode opencode` |
| `voxcode configure` | Interactive workspace setup + model discovery |
| `voxcode configure mcp` | Add/remove Databricks MCP servers |
| `voxcode configure tracing` | Enable MLflow tracing to UC |
| `voxcode status` | Show current config, workspace, models |
| `voxcode usage` | AI Gateway token/cost usage report |
| `voxcode revert` | Undo all config changes, restore backups |
| `voxcode upgrade` | Self-upgrade via `uv` |
| `voxcode mcp web-search` | Run the built-in web-search MCP server |

---

## Local files managed

| Path | Purpose |
|------|---------|
| `~/.voxcode/state.json` | Workspace state (workspace URL, profile, models, MCP servers) |
| `~/.voxcode/opencode-xdg/opencode/opencode.json` | OpenCode provider config (generated each launch) |
| `~/.voxcode/debug.log` | Debug log (only when `UCODE_DEBUG=1`) |
| `~/.databrickscfg` | Databricks CLI profiles (read, not owned) |

---

## Model allowlist

The platform team controls which models are available by editing `src/voxcode/allowed_models.py`. This file contains:

- `ALLOWED_ANTHROPIC_MODELS` — list of permitted Claude model IDs (as returned by the AI Gateway)
- `ALLOWED_GEMINI_MODELS` — list of permitted Gemini model IDs

Models discovered on the workspace but not in these lists are silently filtered out. To add a model, edit the file and release a new voxcode version.

---

## Requirements

- Python 3.12+
- `uv` (for installation)
- `npm` (for OpenCode CLI auto-install)
- A Databricks workspace with AI Gateway v2 enabled and foundation model endpoints provisioned

## Installation

```bash
uv tool install git+https://github.com/faustvo/voxcode
```

## Development

```bash
git clone https://github.com/faustvo/voxcode
cd voxcode
uv sync --all-groups
uv run pytest -v
uv run ruff check .
```

## License

See [LICENSE.md](./LICENSE.md) and [NOTICE.md](./NOTICE.md).
