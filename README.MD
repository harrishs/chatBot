# ChatBot

## Production configuration

`docker-compose.prod.yml` and the production `Caddyfile` rely on a small set of
environment variables so the stack can be reconfigured without editing source
files. Define these in an `.env` file (automatically picked up by
`docker-compose`) or export them in your shell before running the compose
commands:

| Variable | Example | Purpose |
| --- | --- | --- |
| `FRONTEND_DOMAIN` | `example.com` | Primary hostname served by Caddy and allowed by the backend. |
| `FRONTEND_WWW_DOMAIN` | `www.example.com` | Secondary hostname (set to the same value as `FRONTEND_DOMAIN` if not using a second host). |
| `API_BASE_URL` | `https://example.com/api` | Public URL where the API is exposed; used for the frontend build arg and runtime CORS settings. |

These variables drive the configuration for:

* Frontend build arguments (`VITE_API_BASE_URL`) so the SPA points to the
  correct API endpoint.
* Backend host, CSRF, and CORS allow-lists for Django.
* Caddy virtual hosts via environment placeholders in `deploy/Caddyfile`.

When deploying, ensure the environment variables are populated before running
`docker compose -f docker-compose.prod.yml up -d` so every service receives the
correct values.

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
