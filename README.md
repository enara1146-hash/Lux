# Lux v0.3 — Railway mode

Lux is a personal software factory built around the OpenHands Software Agent SDK. v0.3 adds a server mode suitable for Railway: prompt submission, persistent job/project storage, live job polling, OpenHands approval gates, artifact discovery/downloads, and a minimal browser UI.

## Local

```powershell
cd D:\Lux
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
$env:LLM_API_KEY="your-key"
$env:LLM_MODEL="your-model"
lux doctor
```

## Railway

Lux is packaged with a `Dockerfile`. Railway detects a root `Dockerfile` automatically and builds it as the service image.

### Required variables

```text
LLM_API_KEY=...
LLM_MODEL=...
LLM_BASE_URL=https://.../v1     # optional, for OpenAI-compatible providers
LUX_API_KEY=...                 # strongly recommended for a public Railway service
LUX_MAX_CONCURRENT_JOBS=1
LUX_APPROVAL_TIMEOUT=1800
LUX_MAX_ITERATIONS=30
LUX_JOB_TIMEOUT=1800
LUX_FAST_MODE=false
LUX_FAST_MODEL=...       # optional faster model for routine tasks
```

Generate a strong `LUX_API_KEY` and keep it private. The browser UI has a field for the key and sends it as `X-Lux-Key`.

### Persistent storage

Create a Railway Volume and mount it at:

```text
/data
```

Lux stores generated projects, conversations, job state and results under `/data`. Without a Volume, these files are not a durable storage layer for the service.

### Deploy

1. Put this repository in GitHub.
2. In Railway, create a project and add a service from the GitHub repository.
3. Railway will detect the root `Dockerfile`.
4. Add the variables above.
5. Add a Volume mounted at `/data`.
6. Generate a public domain for the service.
7. Open the domain and enter your `LUX_API_KEY` when the UI asks for it.

The health endpoint is:

```text
/health
```

API docs are at:

```text
/docs
```

## API

Create a job:

```http
POST /api/jobs
X-Lux-Key: <key>
Content-Type: application/json

{"prompt":"Build a FastAPI todo API with PostgreSQL","project_name":"todo-api"}
```

Poll:

```http
GET /api/jobs/<job-id>
X-Lux-Key: <key>
```

When OpenHands requests a risky action, Lux pauses the job and exposes the pending action through the approval endpoint. Approve or reject with:

```http
POST /api/jobs/<job-id>/approval
X-Lux-Key: <key>
Content-Type: application/json

{"approve":true}
```

Artifacts:

```http
GET /api/jobs/<job-id>/artifacts
X-Lux-Key: <key>
```

and download an individual artifact with:

```http
GET /api/jobs/<job-id>/artifact?path=<relative-path>
X-Lux-Key: <key>
```

## Important Railway limitation

This v0.3 server executes the OpenHands SDK directly inside the Lux container. It is suitable for a first personal Railway deployment for web/backend projects, but it does not yet provide a dedicated Docker-in-Docker sandbox or Android emulator. Android APK builds therefore require an additional build service/CI runner in a later version.

For a persistent multi-user deployment, move job/session state from local JSON files to a database and isolate each job in a dedicated execution environment.

## Railway deployment note

The Docker image intentionally does not COPY the `tests/` directory. Tests are for local/CI validation and are not required at runtime. This allows Railway deployments to work even when the deploy context excludes tests.


### Railway build image

Lux v0.3.3 pins the runtime base to `python:3.12-slim-bookworm` and installs `openjdk-17-jdk-headless`. This avoids Debian Trixie package resolution issues and provides a full JDK for future Android/Gradle builds.


### Performance controls

Lux emits a heartbeat every 10 seconds while OpenHands is working. The UI shows the current phase, repair attempt, iteration count, and elapsed seconds, so a long provider response is visible instead of appearing frozen.

- `LUX_MAX_ITERATIONS` limits OpenHands iterations per run (default `30`).
- `LUX_JOB_TIMEOUT` bounds each implementation/repair conversation in seconds (default `1800`, minimum `60`). Lux requests a cooperative interruption when the limit is reached.
- The default model remains `nvidia/nemotron-3-ultra-550b-a55b:free`. Set `LUX_FAST_MODE=true` and `LUX_FAST_MODEL` to use a faster OpenAI-compatible model for routine tasks.
