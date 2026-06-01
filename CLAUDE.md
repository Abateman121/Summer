# CLAUDE.md

Guidance for Claude Code when working on this repo.

## What this is

A self-hosted FastAPI + SQLite web app for tracking summer chores and
awarding points that kids can redeem for rewards. Greenfield project; the
working directory started empty on 2026-06-01.

## Stack

- **FastAPI** (async web framework)
- **SQLAlchemy 2.x** ORM with **SQLite** (file at `data/summer.db`)
- **Jinja2** templates (server-rendered HTML, no JS framework)
- **SessionMiddleware** (Starlette) for the parent PIN session
- **Docker** for deployment (`Dockerfile` + `docker-compose.yml`)

## Project layout

```
app/
  main.py          # ALL routes live here
  database.py      # engine, SessionLocal, get_db, init_db
  models.py        # 6 SQLAlchemy tables
  auth.py          # PARENT_PIN check, session helpers
  achievements.py  # PURE FUNCTIONS for streaks/balances/badges
  seed.py          # example data on empty DB
  static/          # style.css, print.css, app.js, icons/
  templates/       # 10 Jinja2 pages
```

## Key conventions

1. **Single-file routing.** All FastAPI routes are in `app/main.py` to keep
   the surface small. Split out per-resource routers if/when this gets big.

2. **Pure-function business logic.** Streak, balance, and badge math lives in
   `app/achievements.py` and takes plain data (no DB, no FastAPI imports).
   This makes it trivially unit-testable and means a single source of truth
   for "what is the current streak?".

3. **Denormalized point values.** `ChoreCompletion.points_earned` and
   `RewardRedemption.points_spent` capture the value at event time, NOT a
   foreign key. This is load-bearing — see the README "How it works" section.
   If you ever consider "normalizing" this, read that section first.

4. **Balance = `SUM(earned) - SUM(spent)`.** There is no separate `balance`
   column on `Kid`. Computed on read in `main.py` helpers `_kid_balances`,
   `_kid_weekly_earned`, `_kid_weekly_spent`.

5. **Auth is one PIN, one session flag.** `parent_pin()` reads
   `PARENT_PIN` from env. `is_authenticated(request)` checks
   `request.session["parent_authenticated"]`. Routes use
   `_require_parent_or_redirect` as a dependency.

6. **Flash messages via query params.** No session-based flash store.
   `_redirect(path, msg=..., error=...)` adds `?msg=...&error=...` and
   templates render the flash strip from those.

7. **Time math is timezone-aware.** `achievements._local_tz()` resolves
   `TZ` env var. Streaks are calculated in local days. UTC is the storage
   format; conversion happens at the boundary.

## How to run

- Docker: `docker compose up -d --build` then http://localhost:8000
- Local: `pip install -r requirements.txt && uvicorn app.main:app --reload`
- First start auto-creates `data/summer.db` and seeds 2 kids, 6 categories,
  12 chores, 6 rewards.
- Default parent PIN is `1234` — change in `.env` (`PARENT_PIN`).

## Things NOT to do

- Do NOT add a JS framework. The app is server-rendered; keep `app.js` tiny.
- Do NOT split the routes into per-resource files just because the file is
  long. ~600 lines in `main.py` is fine for this surface area.
- Do NOT add new top-level dependencies without a strong reason. Current
  `requirements.txt` is the minimal FastAPI surface.
- Do NOT store point values on `Chore` or `Reward` and rely on a join at
  history time. The denormalization in completion/redemption rows is the
  whole "earn at completion time" contract.
- Do NOT add a real password system / JWT / OAuth. The PIN is fine for a
  home-network app. If the user wants real auth later, that's a separate
  feature, not a refactor.
