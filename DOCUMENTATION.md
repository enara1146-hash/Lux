# Lux Documentation

Lux is an OpenHands-powered coding agent that accepts software tasks, edits an isolated workspace, streams safe progress to a browser chat, runs verification, and returns generated files as artifacts.

## Capabilities

- OpenAI-compatible LLM providers and OpenRouter routing.
- ChatGPT-style browser interface.
- SQLite-backed jobs, project memory, settings, users, sessions, events, and verification.
- Optional multi-user authentication.
- Live SSE status, activity, token, message, and error events.
- Optional HTTPS GitHub repository cloning per job.
- OpenHands terminal, file editor, and task tracker tools.
- Python syntax checks and pytest execution.
- Bounded automatic repair attempts after failed checks.
- Persisted Mission Control task graph with acceptance criteria and live progress.
- Artifact listing and secure downloads.
- Admin configuration and operations dashboard.
- Railway deployment with persistent storage.
- Optional durable external worker mode for separate Railway worker services.

Lux currently performs bounded application smoke tests through the agent. It does not yet provide a general interactive browser preview for every generated application.

## Architecture

Main modules:

| File | Responsibility |
|---|---|
| lux/server/app.py | FastAPI routes, browser UI, auth, jobs, SSE, artifacts, admin |
| lux/server/worker.py | OpenHands execution, repository clone, activity, verification, repairs |
| lux/server/jobs.py | SQLite job store and event history |
| lux/server/settings.py | Editable settings and environment fallback |
| lux/server/auth.py | Users, sessions, and password hashing |
| lux/server/artifacts.py | Workspace validation and artifact downloads |
| lux/server/index.html | Browser chat, streaming, activity thread, verification display |
| lux/cli/main.py | lux doctor configuration check |

Request flow:

~~~text
Browser -> POST /api/jobs -> SQLite job
       -> daemon worker -> OpenHands conversation
       -> workspace changes and events
       -> verification and repair loop
       -> SQLite result -> SSE/polling browser updates
~~~

The default worker runs in the web process as a daemon thread. For durable worker mode, the web service only writes queued jobs to SQLite and a separate `lux worker` process atomically claims and executes them. Both modes log startup and failures. On startup, queued jobs are dispatched again and jobs that were running during a prior service stop are marked failed instead of remaining stuck.

## Job lifecycle

Typical statuses:

- queued — job created, worker not started.
- running — workspace and agent are active.
- waiting_for_approval — reserved for approval-gated operations.
- succeeded — agent and verification completed.
- failed — provider, worker, clone, or verification failure.
- cancelled — user requested cancellation.

Each job may contain:

- id, prompt, project_name, owner_id
- status, created_at, updated_at
- workspace and repository_url
- events, verification, and error

Workspaces are created at:

~~~text
/data/projects/<project_name>/<job_id>/
~~~

## Autonomous execution

Lux asks the agent to:

1. Create a persisted task graph with inspection, implementation, verification, and reporting stages.
2. Plan the implementation.
2. Modify the workspace.
3. Run relevant tests.
4. Perform a bounded smoke test when an application is created or changed.
5. Report output and failures.
6. Stop long-running processes after the smoke test.

After the first run, Lux verifies the workspace. If checks fail, it sends the failure output back to the same conversation and asks for a repair. This repeats up to LUX_MAX_REPAIRS times. A cancellation request also interrupts the active OpenHands conversation, so the worker stops cleanly instead of only changing the database status.

The activity thread shows safe operational progress and task-graph transitions. Each project also retains recent verification context and feeds it into later jobs so repeated work becomes more consistent:

- planning
- terminal and file-editing actions
- task tracker updates
- completed tool observations
- verification
- repair attempts
- response preparation

It intentionally does not expose private hidden chain-of-thought. Action details are sanitized and shortened.

## Configuration

The worker checks LLM_* variables first and then OPENAI_* variables.

| Variable | Default | Purpose |
|---|---|---|
| LLM_API_KEY | none | Provider API key |
| OPENAI_API_KEY | none | OpenAI-compatible provider key |
| LLM_MODEL | none | Model override |
| OPENAI_MODEL | nvidia/nemotron-3-ultra-550b-a55b:free | Default model |
| LLM_BASE_URL | none | Endpoint override |
| OPENAI_BASE_URL | https://openrouter.ai/api/v1 | Default endpoint |
| LUX_DATA_DIR | /data | Database and project storage |
| LUX_LOG_LEVEL | INFO | Log level |
| LUX_AUTH_ENABLED | false | Enables sessions and service-key enforcement |
| LUX_API_KEY | none | Service key when auth is enabled |
| LUX_ADMIN_KEY | source fallback exists; set explicitly | Admin dashboard key |
| LUX_MAX_ITERATIONS | 80 | OpenHands iterations per run |
| LUX_MAX_REPAIRS | 2 | Automatic repair attempts |
| LUX_TEST_TIMEOUT | 300 | Verification timeout in seconds |
| LUX_EXTERNAL_WORKER | false | Web service enqueues jobs for a separate `lux worker` service |
| LUX_WORKER_POLL_SECONDS | 2 | External worker polling interval |
| LUX_MAX_ARTIFACT_BYTES | 10485760 | Artifact size limit |
| PORT | 8080 | Railway web port |

OpenRouter example:

~~~text
OPENAI_API_KEY=<OpenRouter key>
OPENAI_MODEL=nvidia/nemotron-3-ultra-550b-a55b:free
OPENAI_BASE_URL=https://openrouter.ai/api/v1
~~~

When the base URL contains openrouter.ai, Lux adds the openrouter/ LiteLLM provider prefix when needed.

For production, set strong values explicitly:

~~~text
LUX_AUTH_ENABLED=true
LUX_API_KEY=<long-random-service-key>
LUX_ADMIN_KEY=<long-random-admin-key>
LUX_MAX_ITERATIONS=30
LUX_MAX_REPAIRS=1
~~~

The large free 550B model can be slow or rate-limited. A smaller/faster model and lower iteration limits improve response time.

## Railway deployment

The Docker image:

- Uses Python 3.12 slim Bookworm.
- Installs Git, curl, Node.js/npm, and OpenJDK 17.
- Installs Lux with pip install ..
- Uses LUX_DATA_DIR=/data.
- Starts Uvicorn on Railway's PORT.
- Exposes /health.

Deployment:

1. Create a Railway project.
2. Add a service from this repository.
3. Add a persistent Volume mounted at /data.
4. Add provider and security variables.
5. Generate a public domain.
6. Deploy from main.
7. Verify /health.
8. Open /admin and load configuration.

The service must be redeployed after GitHub changes. A volume is required to preserve the SQLite database and workspaces across restarts. For durable worker mode, deploy a second worker process from the same image with start command `lux worker`; set `LUX_EXTERNAL_WORKER=true` only on the web service. Both processes must share the same `/data` filesystem. On platforms where services have isolated volumes, do not enable this mode until you replace SQLite with a shared database or queue adapter.

Health endpoint:

~~~http
GET /health
~~~

Successful response:

~~~json
{"status":"ok"}
~~~

## Browser interface

Open:

~~~text
https://<your-domain>/
~~~

The interface includes:

- New task.
- Prompt composer.
- Optional GitHub repository URL.
- Live status.
- Activity thread.
- Streaming response.
- Verification summary.
- Artifact links.
- Admin settings link.

Enter submits a task. Shift+Enter creates a new line.

The default single-user mode has authentication disabled. The browser login/register experience is still minimal, so add a proper login flow before enabling multi-user mode for general users.

## HTTP API

### Create a job

~~~http
POST /api/jobs
Content-Type: application/json
X-Lux-Key: <service-key>
~~~

~~~json
{
  "prompt": "Build a FastAPI todo API",
  "project_name": "todo-api",
  "repository_url": "https://github.com/example/repository"
}
~~~

repository_url is optional and must be an HTTPS GitHub URL.

### Read, stream, cancel

~~~http
GET /api/jobs/<job-id>
X-Lux-Key: <service-key>
~~~

~~~http
GET /api/jobs/<job-id>/stream
X-Lux-Key: <service-key>
~~~

~~~http
POST /api/jobs/<job-id>/cancel
X-Lux-Key: <service-key>
~~~

SSE event types:

- job — status and verification snapshot.
- activity — sanitized operational progress.
- token — streamed response text.
- message — final response fallback.
- error — worker or stream error.

The browser uses authenticated fetch streaming rather than headerless EventSource.

### Approval

~~~http
POST /api/jobs/<job-id>/approval
Content-Type: application/json
X-Lux-Key: <service-key>

{"approve": true, "reason": "Approved for this task"}
~~~

### Artifacts

~~~http
GET /api/jobs/<job-id>/artifacts
X-Lux-Key: <service-key>
~~~

~~~http
GET /api/jobs/<job-id>/artifact?path=relative/path.txt
X-Lux-Key: <service-key>
~~~

### User authentication

~~~http
POST /api/auth/register
Content-Type: application/json

{"email": "user@example.com", "password": "at-least-12-characters"}
~~~

~~~http
POST /api/auth/login
Content-Type: application/json

{"email": "user@example.com", "password": "at-least-12-characters"}
~~~

Login returns a bearer token:

~~~json
{"token": "<session-token>"}
~~~

Send it with Authorization: Bearer <session-token>.

### Admin

~~~http
GET /admin/config
X-Lux-Admin-Key: <admin-key>
~~~

~~~http
POST /admin/config
Content-Type: application/json
X-Lux-Admin-Key: <admin-key>
~~~

Example:

~~~json
{
  "model": "provider/model-name",
  "base_url": "https://openrouter.ai/api/v1",
  "api_key": "<provider-key>",
  "max_repairs": 1
}
~~~

Secrets are not returned. The response only reports whether keys are configured.

Recent operations:

~~~http
GET /admin/operations
X-Lux-Admin-Key: <admin-key>
~~~

## Authentication

Service and admin credentials are separate.

### Service key

- LUX_API_KEY.
- X-Lux-Key or Authorization: Bearer.
- Enforced when LUX_AUTH_ENABLED=true.
- Protects jobs, streams, artifacts, and approvals.

### Admin key

- LUX_ADMIN_KEY.
- X-Lux-Admin-Key.
- Protects configuration and operations.
- The source contains a weak compatibility fallback because of the original setup request. Always set a strong Railway value before public deployment.

### User sessions

When enabled:

- users register with email and password;
- passwords use salted PBKDF2-HMAC-SHA256;
- login creates a bearer session;
- jobs store owner_id;
- owners are restricted to their jobs.

Session expiry and logout are not implemented yet.

## Admin dashboard

Open /admin or /admin/.

The dashboard can:

- show model and base URL;
- report whether a provider key is configured;
- edit model and base URL;
- replace the provider key;
- edit automatic repair attempts;
- load recent operations.

Some environment settings are read when the process starts. Restart or redeploy after changing authentication-related environment variables.

## Persistence

SQLite is stored at:

~~~text
/data/lux.db
~~~

Current tables:

- jobs
- settings
- users
- sessions
- project_memory

SQLite uses WAL journaling.

Generated workspaces are under /data/projects/. A Railway Volume is required for persistence. Without one, jobs, settings, users, sessions, and generated files can disappear when the container is replaced.

## Testing and verification

Repository CI runs:

~~~text
pip install ".[dev]"
ruff check .
pytest
~~~

Regression tests cover the health endpoint and valid SSE framing.

Job verification:

1. Detect Python files.
2. Run python -m compileall -q ..
3. Run python -m pytest -q when tests exist.
4. Start the application and probe LUX_HEALTH_URL when both are configured.\n5. Run LUX_ACCEPTANCE_COMMAND when configured.
6. Store command results in verification.
5. Show checks and output in the chat.

Verification statuses are passed, failed, timed_out, error, and skipped. Acceptance commands are split without a shell and use the same timeout as other checks. HTTP smoke processes are terminated after the probe.

The agent is also instructed to run relevant application checks and bounded smoke tests.

## Performance tuning

The main latency source is normally the provider model, not the browser.

Use a smaller/faster model and reduce autonomous work:

~~~text
LUX_MAX_ITERATIONS=20
LUX_MAX_REPAIRS=0
~~~

Other latency sources:

- large repository clones;
- many sequential OpenHands tool calls;
- dependency installation;
- long test suites;
- provider queues and rate limits;
- repair attempts;
- large prompts and repository context.

Token persistence is batched before SQLite writes so each streamed token does not require its own database transaction.

## Troubleshooting

### Job stays queued

Check Railway logs for:

~~~text
Started worker thread
Starting worker for job
Worker crashed for job
~~~

Likely causes:

- /data permission or filesystem failure;
- service restart during startup;
- database lock or unavailable volume;
- worker import/startup failure.

### Provider failure

Check API key, base URL, model name, OpenRouter rate limits, and provider routing. For OpenRouter use the example configuration above.

### 401 Unauthorized

Usually means authentication is enabled and no valid service key or user token was sent.

### 403 Forbidden

Usually means the service key or admin key is wrong. They are different credentials.

### No response

Check the job status, Railway logs, stream endpoint, provider configuration, deployed commit, and Railway rebuild status. The browser stream falls back to polling when it disconnects.

### Admin page missing

Use /admin or /admin/. Redeploy if the running service predates the dashboard commits.

## Local development

### Windows PowerShell

~~~powershell
python -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
python -m pip install -e ".[dev]"

$env:OPENAI_API_KEY="your-provider-key"
$env:OPENAI_MODEL="your-model"
$env:OPENAI_BASE_URL="https://openrouter.ai/api/v1"

uvicorn lux.server.app:app --host 127.0.0.1 --port 8080
~~~

Install Python 3.12 and Git for Windows if those commands are unavailable.

### Linux/macOS

~~~bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'

export OPENAI_API_KEY='your-provider-key'
export OPENAI_MODEL='your-model'
export OPENAI_BASE_URL='https://openrouter.ai/api/v1'

uvicorn lux.server.app:app --host 127.0.0.1 --port 8080
~~~

Run checks:

~~~bash
ruff check .
pytest
~~~

Configuration check:

~~~bash
lux doctor
~~~

## Security and limitations

Before production:

- replace the weak admin fallback with a strong secret;
- enable service authentication for public deployments;
- use a persistent volume;
- do not expose provider keys in prompts or logs;
- do not run untrusted repositories on a shared production container;
- use a dedicated sandbox for untrusted or multi-tenant workloads;
- review generated files before deployment.

Current limitations:

- worker execution is a daemon thread in the web process;
- queued jobs are recovered on startup and interrupted running jobs are marked failed;
- cancellation is cooperative and depends on the OpenHands conversation interrupting cleanly;
- SQLite is the durable queue in external worker mode; a shared Railway Volume is required;
- there is no per-job container or VM sandbox;
- a restart can interrupt active jobs;
- browser login/register UX is minimal;
- general live application preview is not implemented;
- Android builds need a dedicated environment;
- session expiry and logout are not implemented;
- admin operations are polled, not streamed;
- SQLite is intended for personal/small deployments.

## Roadmap

Recommended next improvements:

1. Durable queue with a separate worker service.
2. Per-job container isolation.
3. Full login/register UI and session expiry.
4. Live application preview proxy.
5. Branch and pull-request workflows.
6. Streaming admin operations.
7. Provider health checks and model fallback.
8. Structured tool logs and downloadable run reports.
9. Time, token, and cost budgets.
10. Scheduled autonomous maintenance tasks.
