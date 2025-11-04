# ChatBot

## Production configuration

`docker-compose.prod.yml` and the production `Caddyfile` rely on a small set of
environment variables so the stack can be reconfigured without editing source
files. Start by copying the provided templates and adjusting the values for
your deployment:

```bash
cp backend/.env.production.example backend/.env.production
cp .env.prod.example .env
```

The backend `.env.production` file is loaded by the `backend`, `worker`, and
`db` services, while the root `.env` file seeds the compose variables used by
Caddy and the frontend build.

Populate the copied files (or export them in your shell) before running the
production compose commands. The following variables are required:

| Variable | Example | Purpose |
| --- | --- | --- |
| `FRONTEND_DOMAIN` | `example.com` | Primary hostname served by Caddy and allowed by the backend. |
| `FRONTEND_WWW_DOMAIN` | `www.example.com` | Optional secondary hostname. If omitted, the compose file, Caddy config, and Django settings all fall back to using only `FRONTEND_DOMAIN`. |
| `API_BASE_URL` | `https://example.com/api` | Public URL where the API is exposed; used for the frontend build arg and runtime CORS settings. |
| `OPENAI_API_KEY` | `sk-live-...` | Required for all demo or production deployments; without it the backend refuses to start. |
| `ENCRYPTION_KEY` | `8wfsecdopt6Fz6ZRlo6RLWF2zOWITlzv9uVSXnscJFA=` | Secret key used by the backend and worker services for Fernet encryption; must be provided at runtime (e.g. via `.env.production`). |
| `DJANGO_SECRET_KEY` | `django-insecure-<random>` | Required when `ENV=production` or `DEBUG` is `False`; secret key used by Django for cryptographic signing. |

These variables drive the configuration for:

* Frontend build arguments (`VITE_API_BASE_URL`) so the SPA points to the
  correct API endpoint.
* Backend host, CSRF, and CORS allow-lists for Django.
* Caddy virtual hosts via environment placeholders in `deploy/Caddyfile`.

### OpenAI completion model selection

The backend defaults to the lightweight `gpt-4o-mini` model for chat
completions so responses remain fast and affordable. Operators who need more
capable models can set the optional `OPENAI_COMPLETION_MODEL` environment
variable (for example, `gpt-4o`). The value is read at runtime, so deployments
can scale up or down without code changes.

> **Important:** Ensure your proxy forwards the `X-Forwarded-Proto` header with
> the value `https` for secure requests. Caddy does this by default and Django's
> `SECURE_PROXY_SSL_HEADER` setting is configured to trust it so generated
> absolute URLs use `https://` and cookies remain marked as secure when served
> through the proxy.

When deploying, ensure the environment variables are populated before running
`docker compose -f docker-compose.prod.yml up -d` so every service receives the
correct values.

### Database migrations

The backend entrypoint automatically runs `python manage.py migrate --noinput`
before collecting static files so both the web and worker containers apply
pending database migrations on startup. Set `SKIP_MIGRATE=1` in environments
where you need to bypass migrations (for example, in CI pipelines that use a
pre-migrated database snapshot).

## Background sync workers

Jira, Confluence, and Git repository synchronisation now run asynchronously
through a background worker so that API requests return immediately with a job
ID.

### Local development

Run the stack with the worker service processing queued sync jobs:

```bash
docker compose up backend worker
```

The backend will enqueue sync jobs in the database and the worker will process
them in the background.

### Production / EC2 deployments

The production compose file already defines the `worker` service. Start or
update the stack with:

```bash
docker compose -f docker-compose.prod.yml up -d backend worker
```

The worker polls the shared database for new sync jobs. Restart the worker after
deploying new code so the latest task definitions are loaded.

### Jira completion metadata backfill

Jira issue documents now include additional completion metadata (resolution,
resolution timestamps, assignee, and status category changes). Apply the
database migrations and then trigger a fresh Jira sync so existing bots
re-ingest issues with the richer content.

1. Deploy the code and run `python manage.py migrate`.
2. Queue a manual Jira sync for each integration (for example, via the
   `POST /api/chatBots/<bot_id>/jiraSyncs/<sync_id>/sync_now/` endpoint or the
   Django admin).
3. Allow the background worker (`python manage.py process_sync_jobs --once` in
   development) to process the queued jobs so documents are regenerated with the
   new metadata.

No additional cleanup is required; rerunning the sync updates both the stored
issues and their embeddings.

### Rerank fallback behaviour

If `OPENAI_RERANK_MODEL` and `OPENAI_RERANK_EMBEDDING_MODEL` are both left
blank, the backend now falls back to the primary embedding model defined by
`OPENAI_EMBEDDING_MODEL` when re-ranking search results. This ensures the query
and the configured top-N documents are embedded and receive deterministic
`rerank_score` values even without a specialised cross-encoder or high-fidelity
rerank embedding model.
