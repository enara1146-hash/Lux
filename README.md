# Lux

Lux is an OpenHands-powered coding agent delivered as a FastAPI service. A user submits a coding task, Lux creates an isolated workspace, lets an LLM inspect and modify it with terminal/file tools, runs verification checks, streams progress to the browser, and returns the result and generated artifacts.

## What Lux does

- Accepts coding tasks through a browser UI or REST API.
- Supports an optional GitHub repository URL as the project input.
- Uses an OpenAI-compatible LLM provider, including OpenRouter.
- Runs OpenHands with terminal, file-editor, and task-tracker tools.
- Persists jobs, events, settings, users, sessions, and project memory in SQLite.
- Streams safe activity events and generated response tokens with Server-Sent Events.
- Runs automatic syntax checks, tests, acceptance commands, and optional HTTP smoke tests.
- Performs bounded automatic repair attempts when verification fails.
- Supports web, EXE, and APK export targets where the build environment provides the required toolchain.
- Includes an admin configuration page and an operations view.
- Shows task history, phases, repair attempts, iteration count, elapsed time, artifacts, and failures.

## Mental model for an AI agent

Treat every request as an acceptance-driven software task:

1. Inspect the workspace and understand the existing architecture.
2. Convert the user request into a concise implementation plan.
3. Make the smallest complete change that satisfies the request.
4. Run relevant checks and tests.
5. Repair failures when possible.
6. Report changed files, verification results, and remaining limitations.

Lux stores this lifecycle as four visible phases:

| Phase | Meaning |
| --- | --- |
| Inspect | Understand files, dependencies, and existing tests. |
| Implement | Change the application in the isolated job workspace. |
| Verify | Run compile checks, tests, smoke checks, and acceptance commands. |
| Report | Summarize the implementation, evidence, and artifacts. |

The UI activity feed is intentionally not chain-of-thought. It shows safe operational events such as tool use, phase changes, test results, elapsed time, and iteration progress.

## Repository map

```text
lux/
  cli.py                 Command-line entry point and diagnostics.
  server/
    app.py               FastAPI routes, SSE streaming, admin routes, browser UI delivery.
    auth.py              Optional multi-user registration, login, and sessions.
    artifacts.py         Safe artifact discovery and path resolution.
    exporter.py          Web, EXE, and APK export orchestration.
    index.html            ChatGPT-style browser interface.
    jobs.py              SQLite-backed jobs, events, queue claims, and project memory.
    settings.py          Environment/database configuration resolution.
    supervisor.py        Execution plan and bounded runtime configuration.
    worker.py             OpenHands execution, streaming, verification, repair, and timeout logic.
tests/                    Automated tests.
Dockerfile                Railway/container image definition.
```

## Local development

PowerShell:

```powershell
python -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
pip install -e ".[dev]"
$env:LLM_API_KEY="your-provider-key"
$env:LLM_MODEL="your-model"
lux doctor
uvicorn lux.server.app:app --host 127.0.0.1 --port 8080
```

Open `http://127.0.0.1:8080`.

If Git is unavailable on Windows, install Git for Windows or use the repository's GitHub web integration. If Python is unavailable, install Python 3.12 or run Lux with Docker/Railway.

## Railway deployment

Lux is packaged with a root `Dockerfile`.

1. Create a Railway service from this repository.
2. Add a persistent volume mounted at `/data`.
3. Configure the variables below.
4. Deploy and open the generated domain.
5. Check `/health` and `/docs`.

A volume is important: without it, SQLite state and generated workspaces disappear when the container is replaced.

## Configuration

### Required

```text
LLM_API_KEY=...
```

Use `OPENAI_API_KEY` instead if preferred. The provider key is also the key Lux uses for LLM requests; `LUX_API_KEY` is a separate optional request-protection key.

### Common

```text
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_MODEL=nvidia/nemotron-3-ultra-550b-a55b:free
LUX_DATA_DIR=/data
LUX_API_KEY=choose-a-private-request-key
LUX_MAX_CONCURRENT_JOBS=1
LUX_MAX_ITERATIONS=30
LUX_MAX_REPAIRS=2
LUX_TEST_TIMEOUT=300
LUX_JOB_TIMEOUT=1800
```

### Performance controls

Lux emits a heartbeat every 10 seconds while an implementation is running. The browser displays the current phase, attempt, iteration count, and elapsed seconds.

- `LUX_MAX_ITERATIONS`: maximum OpenHands iterations per conversation.
- `LUX_JOB_TIMEOUT`: maximum seconds for one implementation or repair conversation.
- `LUX_FAST_MODE=true`: enable an alternate model for routine tasks.
- `LUX_FAST_MODEL=<model>`: model used when fast mode is enabled.
- Fast mode is opt-in. The Nemotron model above remains the default otherwise.

### Authentication and administration

```text
LUX_AUTH_ENABLED=false
LUX_ADMIN_KEY=123456789
LUX_DEFAULT_ADMIN_EMAIL=admin@admin.com
LUX_DEFAULT_ADMIN_PASSWORD=choose-a-private-password
```

`LUX_API_KEY` protects API requests. `LUX_ADMIN_KEY` protects `/admin/config` and `/admin/operations). Do not expose default or development secrets on a public deployment.

## API examples

Create a task:

```http
POST /api/jobs
X-Lux-Key: your-request-key
Content-Type: application/json

{"prompt":"Build a FastAPI todo API with tests","project_name":"todo-api"}
```

Optional repository and exports:

```json
{
  "prompt": "Add authentication and tests",
  "project_name": "my-project",
  "repository_url": "https://github.com/example/project",
  "export_targets": ["web"]
}
```

Read a task:

```http
GET /api/jobs/<job-id>
X-Lux-Key: your-request-key
```

Stream progress:

```http
GET /api/jobs/<job-id>/stream
X-Lux-Key: your-request-key
```

Stop a task:

```http
POST /api/jobs/<job-id>/cancel
X-Lux-Key: your-request-key
```

Artifacts:

```http
GET /api/jobs/<job-id>/artifacts
GET /api/jobs/<job-id>/artifact?path=<relative-path>
X-Lux-Key: your-request-key
```

Full interactive API documentation is available at `/docs`.

## Conversation versus coding mode

Every task has an explicit mode:

- `code`: Lux may inspect the workspace, edit files, run tools, verify the result, repair failures, and create requested exports.
- `conversation`: Lux answers as a coding advisor. It should explain concepts, suggest designs, review pasted information, and provide examples without modifying the workspace or claiming that code was changed.

The browser composer lets you choose the mode before sending a task. REST clients can send `"mode":"conversation"` or `"mode":"code"`; coding mode is the default for compatibility.

## Prompt-writing guide

Good prompts state the outcome and how it will be verified:

```text
Build a responsive React inventory dashboard. Add product CRUD, search, low-stock alerts,
SQLite persistence, loading/error states, and automated tests. Run the tests and report the
exact results. Do not leave a development server running after verification.
```

For an existing repository, state:

- what to inspect;
- the behavior to add or fix;
- constraints such as framework or database;
- tests or acceptance criteria;
- deployment/export requirements.

Avoid asking Lux to expose secrets, bypass authorization, or leave unbounded processes running.

## Verification behavior

Lux may run:

- Python bytecode compilation;
- `pytest` when tests are detected;
- `npm test` when a package test script exists;
- `LUX_ACCEPTANCE_COMMAND`, if configured;
- an HTTP smoke test using `LUX_START_COMMAND` and `LUX_HEALTH_URL`;
- export builds requested by the user.

Each check is bounded by `LUX_TEST_TIMEOUT`. Failed checks trigger repair prompts up to `LUX_MAX_REPAIRS`.

## Troubleshooting

### Job remains queued

Check that the worker process is running and that `LUX_MAX_CONCURRENT_JOBS` is not exhausted. For Railway, verify the service has enough memory and that the persistent volume is mounted.

### Job fails immediately

Inspect the job error and Railway logs. Common causes are a missing LLM key, an invalid OpenAI-compatible base URL, an unsupported model/provider prefix, or a Python import/syntax error during worker startup.

### No response appears

Open the task history and check the job phase. The SSE stream is only for live updates; polling `GET /api/jobs/<id>` remains available. Verify the browser has the correct `X-Lux-Key` if request protection is enabled.

### Agent is slow

Use a smaller/faster model with `LUX_FAST_MODE=true`, lower `LUX_MAX_ITERATIONS`, reduce repair attempts, and make the task acceptance criteria specific. Heartbeats and elapsed time indicate whether the worker is active.

### OpenRouter provider error

Use an OpenAI-compatible base URL such as `https://openrouter.ai/api/v1`. Lux adds the `openrouter/` provider prefix when needed.

## Security boundaries

- Never commit API keys, passwords, or tokens.
- Keep `LUX_API_KEY` and `LUX_ADMIN_KEY` private on public deployments.
- Treat repository code, generated code, and LLM output as untrusted.
- Use isolated job workspaces and bounded commands.
- Validate artifact paths through Lux's artifact resolver.
- Use authentication and a persistent volume for multi-user deployments.

## License and status

Lux is an actively developed personal coding-agent service. See the repository history for the current implementation status and changes.
