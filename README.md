# Patchline

Patchline is a local AI code review agent. Paste a unified Git diff or point it at a GitHub pull request. The backend sends that change to an OpenAI-compatible model, validates the JSON it returns, and stores the summary and findings in SQLite. The Angular app is the dashboard, review form, results page, and history.

This MVP is for a local or otherwise controlled development machine. It has no authentication and is not a multi-user production service. Do not expose it to the internet.

Submitted code is untrusted data. Patchline does not execute it, apply suggested patches, or open pull requests.

## Architecture

The backend is a single FastAPI process. A review is a synchronous request: validate the input, create a `processing` row, call the model, then store `completed` or `failed`. The orchestration lives in `ReviewService`, so a background worker can call the same service later without rewriting the review rules.

| Path | Responsibility |
| --- | --- |
| `backend/app/main.py` | App startup, CORS, body-size limit, error handlers |
| `backend/app/api/` | HTTP routes and dependency wiring |
| `backend/app/core/` | Settings, logging, redaction, request-size middleware |
| `backend/app/schemas/` | Pydantic request and response models |
| `backend/app/models/` | SQLite row entities |
| `backend/app/repositories/` | SQLite persistence |
| `backend/app/services/` | Diff parsing, GitHub fetch, review orchestration, export |
| `backend/app/providers/` | Replaceable LLM provider interface and OpenAI-compatible client |
| `backend/app/prompts/review_v1.py` | Versioned review prompt (`review-v1`) |
| `frontend/src/app/` | Standalone Angular pages, API client, and Tailwind UI |

The LLM provider is an interface (`LLMProvider`). The current implementation posts to `{LLM_BASE_URL}/chat/completions`. Business logic does not know whether that URL is OpenAI, Ollama, LM Studio, or another compatible server.

The full diff is not kept after analysis. Review rows store the title, source, status, summary, context limitations, model metadata, file stats, and findings (including short snippets). API keys and GitHub tokens are never written to the database.

Findings cite line numbers only when those lines exist in the parsed diff. A path or line the model invents is kept only as an uncertain reference: the line is cleared and the finding is marked as limited context.

If the model returns malformed JSON, Patchline makes one repair request that is instructed not to invent findings. If that also fails, the review is stored as `failed` and the error is returned. Results are never filled in locally.

## Requirements

- Python 3.12 or newer
- Node.js 22 or newer (developed with npm 10)
- A model behind an OpenAI-compatible chat completions API

Verified with Python 3.12, FastAPI 0.162, Angular 22.2, and Tailwind CSS 4.

## Configure the model

Copy the example environment file from the repository root:

```powershell
Copy-Item .env.example .env
```

Edit `.env`. For OpenAI:

```text
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-your-key
LLM_MODEL=gpt-4o-mini
```

For a local server such as Ollama, point the base URL at that server and leave the key empty. The URL must include the `/v1` prefix used by its OpenAI-compatible endpoint:

```text
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=http://127.0.0.1:11434/v1
LLM_API_KEY=
LLM_MODEL=llama3.1
```

`LLM_API_KEY` is required only when `LLM_BASE_URL` is the official `api.openai.com` host. The key stays in the backend process. Restart the API after changing `.env`.

## Optional GitHub access

Public pull requests work without a token, subject to GitHub's unauthenticated rate limit. Set `GITHUB_TOKEN` in `.env` for private repositories and a higher limit. Use a token that can read pull requests. Classic tokens need the `repo` scope for private repositories; fine-grained tokens need pull request read access on that repository.

The browser never receives the token. Pull request URLs are accepted only for the host in `GITHUB_WEB_HOST` (default `github.com`), so the server cannot be aimed at an arbitrary address. GitHub Enterprise is outside this MVP.

## Run on Windows (PowerShell)

Use two terminals. Commands assume the repository root is the current directory unless a step changes it.

Terminal 1, backend:

```powershell
Copy-Item .env.example .env
notepad .env
cd backend
py -3.12 -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

If `py -3.12` is not available, create the virtual environment with `python -m venv .venv` instead. The API is at http://127.0.0.1:8000 and the interactive docs are at http://127.0.0.1:8000/docs.

Terminal 2, frontend:

```powershell
cd frontend
npm install
npm start
```

Open http://localhost:4200. The dev server proxies `/api` to http://127.0.0.1:8000.

## Run on macOS or Linux

Terminal 1, backend:

```bash
cp .env.example .env
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Terminal 2, frontend:

```bash
cd frontend
npm install
npm start
```

## Using Patchline

1. Open the dashboard. Totals are counted from SQLite. A new install shows zeros and an empty history.
2. Choose **New review**.
3. Paste a unified diff (`git diff`, `git diff main...HEAD`, or `git show <commit>`), or enter a GitHub pull request URL such as `https://github.com/owner/repo/pull/123`.
4. Start the review and wait. The model call is synchronous and can take a couple of minutes.
5. Read the summary, context limitations, and findings. Filter by severity, category, or file. Group by severity or category. Copy a finding, or export the review as Markdown or JSON.
6. Open **History** to page through stored reviews or delete one.

A completed review with no findings does not mean the change is safe, correct, or ready to ship. A failed review stores the error and does not invent findings.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | Health, model name, and whether a key or GitHub token is configured. No secrets. |
| `POST` | `/api/reviews/diff` | Review a unified diff. Body: `title`, `diff`. |
| `POST` | `/api/reviews/github` | Review a pull request. Body: `repository_url`, optional `pull_request_number`, optional `title`. |
| `GET` | `/api/reviews/stats` | Counts derived from stored reviews. |
| `GET` | `/api/reviews?limit=20&offset=0` | Review history. `limit` is at most 100. |
| `GET` | `/api/reviews/{review_id}` | One review and its findings. |
| `GET` | `/api/reviews/{review_id}/export?format=json` | Download JSON. `format=markdown` downloads Markdown. |
| `DELETE` | `/api/reviews/{review_id}` | Delete a review and its findings. |

OpenAPI is served at `/docs`.

Provider failures return `502` with `detail`, `code`, and `review_id` when a row was saved. Validation problems return `422`. Diffs over the configured limit return `413`. GitHub rate limits return `429`. An unknown pull request returns `404`.

## Configuration reference

| Variable | Default | Purpose |
| --- | --- | --- |
| `LLM_PROVIDER` | `openai_compatible` | Provider id. Only `openai_compatible` is implemented. |
| `LLM_BASE_URL` | `https://api.openai.com/v1` | Chat completions base URL. |
| `LLM_API_KEY` | empty | Bearer token. Required for `api.openai.com`. |
| `LLM_MODEL` | `gpt-4o-mini` | Model name sent to the provider. |
| `LLM_TIMEOUT_SECONDS` | `120` | HTTP timeout for one model call. |
| `LLM_TEMPERATURE` | `0.1` | Sampling temperature. Omitted on retry if a model rejects it. |
| `LLM_MAX_OUTPUT_TOKENS` | `8192` | Maximum completion tokens. |
| `GITHUB_TOKEN` | empty | Optional GitHub token. |
| `GITHUB_API_BASE_URL` | `https://api.github.com` | GitHub API origin. |
| `GITHUB_WEB_HOST` | `github.com` | Only this host is accepted in user-supplied URLs. |
| `GITHUB_TIMEOUT_SECONDS` | `30` | Timeout for each GitHub request. |
| `DATABASE_PATH` | `data/reviews.db` | SQLite file. Relative paths resolve from `backend/`. |
| `CORS_ORIGINS` | localhost ports `4200` | Comma-separated browser origins. |
| `MAX_DIFF_BYTES` | `100000` | Maximum diff size. |
| `MAX_DIFF_FILES` | `80` | Maximum files in one diff. |
| `MAX_FINDINGS` | `30` | Maximum findings kept from a model response. |
| `MAX_REQUEST_BYTES` | `150000` | Maximum HTTP body. Must exceed `MAX_DIFF_BYTES` by at least 1024. |
| `LOG_LEVEL` | `INFO` | Python log level. |
| `HOST` / `PORT` | `127.0.0.1` / `8000` | Used by `python -m app.main`. The uvicorn command above sets the bind address itself. |

Logs record review ids, status codes, and durations. They do not record diffs, authorization headers, or API keys. Upstream error text is redacted before it is stored.

## Security

- Secrets are read from the environment. `.env.example` contains placeholders only.
- Request bodies are limited before JSON parsing.
- CORS origins come from `CORS_ORIGINS`.
- Reviewed source, comments, and pull request text are wrapped as untrusted data. The prompt tells the model to ignore instructions inside that data.
- The model is not given tools, and Patchline does not run generated patches.
- Snippets are rendered as text in the browser.
- GitHub credentials in a user-supplied URL are rejected. Requests to GitHub do not follow redirects, so the token is not sent to another host.

## Troubleshooting

**The page says it cannot reach the API.** Start the backend on port 8000, then use `npm start` so the Angular proxy is applied. Opening the built files directly does not proxy `/api`.

**`LLM_API_KEY is not set`.** The base URL still points at `api.openai.com`. Set the key, or change `LLM_BASE_URL` to your local server and restart the API.

**The model request times out or the JSON is truncated.** Lower `MAX_FINDINGS`, raise `LLM_TIMEOUT_SECONDS` or `LLM_MAX_OUTPUT_TOKENS`, or review a smaller diff. A failed review stays in History with the provider error.

**Ollama returns 404.** The base URL needs the `/v1` suffix, for example `http://127.0.0.1:11434/v1`.

**GitHub says the pull request was not found.** Check the URL and number. Private repositories need `GITHUB_TOKEN`. A `429` means the rate limit was hit; add a token or wait.

**The diff is rejected.** It must be a unified diff with hunk headers, and it must stay under `MAX_DIFF_BYTES` and `MAX_DIFF_FILES`. Binary-only diffs are rejected because there is no text to review.

**CORS errors.** Add the browser origin to `CORS_ORIGINS`. `http://localhost:4200` and `http://127.0.0.1:4200` are different origins.

**PowerShell will not activate the virtual environment.** Run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` in that terminal, then activate again.

**Port 8000 or 4200 is already in use.** Stop the other process or pass a different `--port` to uvicorn. If you change the API port, update `frontend/proxy.conf.json` to match.
