# Frontend

This directory contains the React + Vite single-page application for the ChatBot project.

## Environment variables

The application reads Vite environment variables at build and dev-server time. Variables must be prefixed with `VITE_` to be exposed to the browser.

| Variable | Default | Description |
| --- | --- | --- |
| `VITE_API_BASE_URL` | `/api` | Base URL used by Axios when issuing API calls. Set this when the frontend is served from a different origin than the backend. |

When the frontend and backend are deployed on the same origin (for example behind the production Caddy reverse proxy), you can rely on the default `/api` path. For local development where the Django API is served from `localhost:8000`, set `VITE_API_BASE_URL=http://localhost:8000/api` before starting Vite.

## Local development

```bash
npm install
VITE_API_BASE_URL=http://localhost:8000/api npm run dev
```

This starts the Vite dev server on [http://localhost:5173](http://localhost:5173). The environment variable can also be stored in a `.env.local` file if you prefer.

## Production build

```bash
npm install
VITE_API_BASE_URL=https://example.com/api npm run build
```

The resulting static assets in `dist/` can be served by any static web server. Remember that the value baked into the build cannot be changed at runtime, so set `VITE_API_BASE_URL` appropriately before building.

## Docker builds

Both `Dockerfile` (development) and `Dockerfile.prod` (production) accept a `VITE_API_BASE_URL` build argument. This allows Compose or other orchestrators to pass the correct API endpoint while keeping `/api` as the default fallback.
