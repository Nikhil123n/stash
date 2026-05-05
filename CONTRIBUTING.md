# Contributing

## Local Setup

1. Copy `backend/.env.example` to `backend/.env`.
2. Copy `frontend/.env.example` to `frontend/.env`.
3. Fill in local credentials only in `.env` files. Do not commit real secrets.
4. Run `docker compose up --build` for local services.

## Checks

Run backend tests from `backend`:

```bash
pytest tests/
```

Run frontend checks from `frontend`:

```bash
npm run lint
npm run build
```

## Pull Requests

Keep changes focused, update `.env.example` when configuration changes, and avoid committing generated files such as logs, build output, dependency folders, or local database data.
