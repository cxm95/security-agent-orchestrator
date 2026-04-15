# Development Guide

This guide covers setting up your development environment and running tests for the Security Agent Orchestrator (SecAgentNet) project.

## Prerequisites

- Python 3.10 or higher
- [uv](https://docs.astral.sh/uv/) — Fast Python package installer and resolver
- Git
- tmux 3.2+ (for running the orchestrator and integration tests)

## Getting Started

### 1. Clone the Repository

```bash
git clone <repository-url>
cd security-agent-orchestrator/
```

### 2. Install Dependencies

The project uses `uv` for package management. Install all dependencies including development packages:

```bash
uv sync
```

This command:
- Creates a virtual environment (if one doesn't exist)
- Installs all project dependencies
- Installs development dependencies (pytest, coverage tools, linters, etc.)

### 3. Verify Installation

```bash
# Check that the CLI is available
uv run cao --help

# Run the evolution tests as a quick smoke test
uv run pytest test/evolution/ -v --tb=short -q
```

## Running Tests

Test paths are configured in `pyproject.toml` (`testpaths = ["test"]`), so pytest discovers all tests automatically.

### Test Directory Structure

```
test/
├── api/                    API endpoint tests
├── cli/                    CLI command tests
├── clients/                Client tests (database, tmux)
├── e2e/                    E2E tests (require running Hub server + authenticated providers)
├── evolution/              Evolution & co-evolution tests (255 tests)
│   ├── test_evolution.py           Core types, attempts, checkpoint
│   ├── test_evolution_api.py       Evolution API endpoints
│   ├── test_evolution_grader_mcp.py MCP tools + grader
│   ├── test_heartbeat.py           Heartbeat trigger + prompt rendering
│   ├── test_skill_evolution.py     Skill evolution integration
│   ├── test_skill_sync.py          Skill synchronization
│   ├── test_bridge_evolution.py    Bridge protocol
│   ├── test_claude_code_bridge.py  Claude Code bridge files
│   ├── test_e2e_evolution.py       E2E evolution (requires running server)
│   ├── test_hermes_plugin.py       Hermes plugin
│   ├── test_remote.py              Remote provider
│   └── test_reports.py             Report generation
├── mcp_server/             MCP server tests
├── models/                 Model tests
├── providers/              Provider tests (⚠ some broken — see note below)
├── services/               Service tests
└── utils/                  Utility tests
```

### ⚠ Broken Provider Tests

Eight test files in `test/providers/` reference upstream provider modules that have been removed from this fork. They will fail with import errors:

- `test_gemini_cli_unit.py`
- `test_kimi_cli_unit.py`
- `test_kiro_cli_unit.py`
- `test_kiro_cli_integration.py`
- `test_q_cli_unit.py`
- `test_q_cli_integration.py`
- `test_script_provider_unit.py`
- `test_permission_prompt_detection.py`

These are kept for reference. Exclude them when running the full suite (see below).

### Evolution Tests (Recommended Starting Point)

The `test/evolution/` directory contains 255 tests covering the evolution and co-evolution system. These are self-contained, fast, and the most actively developed:

```bash
# Run all evolution tests
python3 -m pytest test/evolution/ -v

# Run a specific evolution test file
python3 -m pytest test/evolution/test_heartbeat.py -v

# Run with keyword filter
python3 -m pytest test/evolution/ -v -k "grader"
```

### All Working Tests

Run the full suite while excluding the broken upstream provider tests:

```bash
python3 -m pytest test/ \
  --ignore=test/providers/test_gemini_cli_unit.py \
  --ignore=test/providers/test_kimi_cli_unit.py \
  --ignore=test/providers/test_kiro_cli_unit.py \
  --ignore=test/providers/test_kiro_cli_integration.py \
  --ignore=test/providers/test_q_cli_unit.py \
  --ignore=test/providers/test_q_cli_integration.py \
  --ignore=test/providers/test_script_provider_unit.py \
  --ignore=test/providers/test_permission_prompt_detection.py \
  -v
```

### E2E Tests

E2E tests require a running Hub server, authenticated CLI tools, and tmux:

```bash
# Standard E2E tests
python3 -m pytest test/e2e/ -v

# Evolution E2E tests (requires running Hub — see below)
python3 -m pytest test/evolution/test_e2e_evolution.py -v
```

### Coverage

```bash
# Coverage for evolution tests
python3 -m pytest test/evolution/ --cov=src --cov-report=term-missing -v

# HTML coverage report (open htmlcov/index.html)
python3 -m pytest test/evolution/ --cov=src --cov-report=html
```

## Hub Server for Development

The Hub server (`cao-server`) exposes the REST API on port 9889. You need it running for E2E tests and Web UI development.

```bash
# Start the Hub server
cao-server                    # Starts on http://127.0.0.1:9889

# Or with uvicorn directly (useful for auto-reload during development)
uvicorn cli_agent_orchestrator.api.main:app --host 0.0.0.0 --port 9889 --reload
```

To run E2E evolution tests against a live server:

```bash
cao-server &                  # Start Hub in the background
python3 -m pytest test/evolution/test_e2e_evolution.py -v
kill %1                       # Stop the Hub when done
```

## Web UI Development

The web UI is a React + Vite + Tailwind app in `web/`.

```bash
# Install frontend dependencies
cd web/
npm install

# Start dev server (hot-reloads on file changes)
npm run dev        # http://localhost:5173

# Build for production
npm run build      # Outputs to web/dist/
```

The Vite dev server proxies API calls to the backend at `localhost:9889`. Make sure `cao-server` is running before starting the frontend.

## Code Quality

### Formatting

```bash
# Format all Python files
uv run black src/ test/

# Check formatting without making changes
uv run black --check src/ test/
```

### Import Sorting

```bash
# Sort imports
uv run isort src/ test/

# Check import sorting without making changes
uv run isort --check-only src/ test/
```

### Type Checking

```bash
uv run mypy src/
```

### Run All Quality Checks

```bash
uv run black src/ test/
uv run isort src/ test/
uv run mypy src/
python3 -m pytest test/evolution/ -v
```

## Development Workflow

1. Create a feature branch: `git checkout -b feature/your-feature-name`
2. Make changes in `src/cli_agent_orchestrator/`
3. Add or update tests in `test/` (prefer `test/evolution/` for evolution work)
4. Run tests: `python3 -m pytest test/evolution/ -v`
5. Check code quality: `uv run black src/ test/ && uv run isort src/ test/`
6. Commit and push

## Troubleshooting

### Import Errors

```bash
# Re-sync dependencies
uv sync

# If that doesn't work, remove the virtual environment and start fresh
rm -rf .venv
uv sync
```

### Test Failures

```bash
# Run with verbose output
python3 -m pytest -vv

# Run a specific failing test
python3 -m pytest test/path/to/test.py::test_name -vv

# Show print statements
python3 -m pytest -s
```

### Hub Server Won't Start

```bash
# Check if port 9889 is already in use
lsof -i :9889

# Start with debug logging
uvicorn cli_agent_orchestrator.api.main:app --host 0.0.0.0 --port 9889 --log-level debug
```

## Adding Dependencies

```bash
uv add package-name              # Runtime dependency
uv add "package-name>=1.0.0"     # With version constraint
uv add --dev package-name        # Development dependency
```

## Project Structure

```
security-agent-orchestrator/
├── src/
│   └── cli_agent_orchestrator/     # Main source code
│       ├── api/                    # FastAPI server (Hub)
│       ├── cli/                    # CLI commands
│       ├── clients/                # Database and tmux clients
│       ├── mcp_server/             # MCP server implementation
│       ├── models/                 # Data models
│       ├── providers/              # Agent providers
│       ├── services/               # Business logic services
│       └── utils/                  # Utility functions
├── test/                           # Unified test suite
│   ├── evolution/                 # Evolution & co-evolution tests (255 tests)
│   ├── api/                       # API endpoint tests
│   ├── cli/                       # CLI command tests
│   ├── clients/                   # Client tests
│   ├── e2e/                       # End-to-end tests
│   ├── mcp_server/                # MCP server tests
│   ├── models/                    # Data model tests
│   ├── providers/                 # Provider tests (some broken — see note)
│   ├── services/                  # Service layer tests
│   └── utils/                     # Utility tests
├── web/                            # React + Vite + Tailwind frontend
├── pyproject.toml                  # Project configuration
└── uv.lock                         # Locked dependencies
```

## Resources

- [Project README](README.md)
- [uv Documentation](https://docs.astral.sh/uv/)
- [pytest Documentation](https://docs.pytest.org/)
