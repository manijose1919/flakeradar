# Contributing to FlakeRadar

## Dev setup

```bash
# Backend
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # Windows (.venv/bin on macOS/Linux)
.venv/Scripts/python -m uvicorn app.main:app --port 8000

# Frontend
cd frontend
npm install
npm run dev
```

## Test gate

Both must pass before a PR is merged:

```bash
cd backend && .venv/Scripts/python -m pytest   # backend unit/API/migration tests
cd frontend && npm run build                   # strict TypeScript build
```

## Database migrations

Schema changes go through Alembic. After editing `backend/app/models.py`:

```bash
cd backend
.venv/Scripts/python -m alembic revision --autogenerate -m "describe change"
# review the generated file; SQLite constraint changes must use batch mode
```

Migrations run automatically on app startup.
