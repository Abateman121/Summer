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

## Deferred features (not yet built, revisit when ready)

These are real requirements that the user has explicitly asked for, but
have been deferred because they're not the next thing to ship. They are
intentionally **not** in the code yet. Pick one up when the time comes
and treat it as its own design exercise — the design notes below are
hints, not a finished spec.

### Feature A — Multi-tenant family switching

The user is letting friends use the app for their own families. Needs:

- A new family signup: a parent arrives, the app prompts them to set up
  a parent PIN, then drops them into the kid-facing dashboard as if
  they were a kid. They have to enter the PIN to access parental
  controls.
- Multiple parents per family: parent A can invite parent B; both
  emails share the same family/data.
- Strict data isolation: Family A cannot see Family B and vice versa.
  Every query needs a `family_id` scope.

Every existing table (`kids`, `chores`, `chore_completions`, `rewards`,
`reward_redemptions`, `categories`) needs a `family_id` foreign key;
every route needs to scope queries to the current family from the
session. The schema migration is non-trivial — likely needs a one-time
data backfill. The `parent_pin` becomes per-family, not global.

The kid-facing pages stay PIN-less (kids pick themselves by
avatar/name, no auth needed). Auth becomes a thin layer (email +
password or magic link) on top of the PIN.

### Feature B — OAuth with Authentik

Add OIDC/OAuth login against a self-hosted Authentik instance.
Authentik is the identity provider; users sign in with their email or
username. This is the auth layer that plugs into Feature A — each
Authentik user maps to a family and a role within that family.

Use `authlib` (already a transitive dep of FastAPI ecosystem) or
`python-oauth2`. Configure the OIDC client via env vars:
`AUTHENTIK_ISSUER`, `AUTHENTIK_CLIENT_ID`, `AUTHENTIK_CLIENT_SECRET`.
Default provider config: "Email or username" (the `preferred_username`
and `email` claims). Keep the local PIN as a second factor or as a
kid-mode escape hatch. Add a `/login/oauth` redirect endpoint and a
`/oauth/callback` handler. Store the OIDC `sub` claim on a future
`family_member` row so we can re-link accounts after a family
migration.

### Feature C — SMTP for Gmail

Add outbound email via Gmail SMTP. The user has already set up a
Gmail app password.

Wire `aiosmtplib` (async, fits the FastAPI model) or fall back to
`smtplib` in a thread. Add to `requirements.txt`. Add these env vars
to `.env` and `docker-compose.yml`:

- `SMTP_HOST=smtp.gmail.com`
- `SMTP_PORT=587`
- `SMTP_USERNAME=<gmail-address>`
- `SMTP_PASSWORD=<app-password>` (mark as Docker secret / .env only,
  never in git)
- `SMTP_FROM=<gmail-address>`
- `SMTP_USE_TLS=true`

Use STARTTLS on port 587. No bulk send needs — just transactional.
Add a tiny `send_email(to, subject, body)` helper in `app/email.py`
and unit-test it can be no-op'd in dev when `SMTP_HOST` is unset (log
instead of send).

This is needed for several use cases, **all** of which must be
covered before the helper is "done":

- **Parent invite email** (Feature A — when parent A invites parent B
  to their family).
- **Password reset email** (Feature A basic-auth path — when a
  non-Authentik parent clicks "forgot password" on `/login`; the
  reset link contains a one-time token that expires in an hour or
  so. **Authentik users do not flow through this path** — their
  password reset is handled by Authentik itself, per Feature B).
- **Chore-completion alerts** — when a kid marks a chore as complete
  (the pending-approval flow from v0.0.7), the parent(s) in that
  family receive an email so they don't have to babysit the
  `/parent` queue. Almost certainly opt-in per family (and probably
  per parent within a family) rather than a global default — most
  parents don't want an email per tooth-brushing. Digest mode
  (daily summary) is probably a better default than per-event
  email; expose a toggle on the family settings page.
- **Test-fire email** (Feature E — the admin account has a "send
  test email" button to confirm the SMTP wiring is working
  end-to-end).
- **General notifications** (weekly summaries, etc. — lower
  priority, build when there's a concrete need).

The helper should accept a `recipient`, `subject`, `body`, and
optional `category` for log filtering (e.g. `"invite"`, `"reset"`,
`"alert"`, `"test"`). The category is what makes the admin's
"recent sent emails" log useful.

### Feature D — Negative points / point adjustments

Two related capabilities, both not yet built:

1. **Adjust previously approved points.** Today a parent can only
   "undo" an approved chore completion (which zeros it and marks it
   denied) or add a new completion. The user wants to be able to
   *change* the point value of an existing approved row in place —
   e.g. "I awarded 25 but it should have been 20." Keep the
   denormalized point value as the source of truth (don't
   recalculate from the chore's current `points`), and update the
   balance / streak / lifetime recompute automatically because they
   sum the stored value.

2. **A parent-driven deduction flow for negative behaviors.** Examples
   the user gave: fighting, arguing, not doing daily chores.
   Conceptually a "negative chore" or "deduction" that subtracts
   points from a kid's balance. Options to consider:
   - A new `Chore` row with `points` allowed to be negative (or a
     separate `is_deduction` flag), or
   - A new entity entirely (e.g. `Deduction` with `points` always
     negative, `reason` text, optionally a category like "behavior"
     or "missed routine"), or
   - Just letting the existing `parent_complete_chore` accept a
     negative `points_override` so the same form handles both
     directions.

   The user mentioned wanting a "category" the parent fills out,
   which suggests a small taxonomy ("behavior", "missed routine",
   "attitude") taggable onto a deduction. The existing `Category`
   table is chore-scoped; a new lightweight category model for
   deductions would be cleaner than overloading it.

The balance math already sums the `points_earned` / `points_spent`
columns, so negative values flow through naturally — the work is in
the UI (a "−" button or a deduction form on `/parent`, an "adjust
points" button on `/parent/history` for approved completions) and
the schema (either extending `ChoreCompletion` to allow negative
`points_earned`, or a new `Deduction` model with its own list). The
existing `points_override` parameter on `parent_complete_chore` /
`parent_approve_completion` is the natural place to start — accept
a signed integer and skip the `max(0, ...)` clamp.

The kid view would benefit from a timeline that shows deductions
distinctly from earnings (different color, "−" instead of "+").

### Feature E — Platform-level admin account

Once we have any kind of auth (Feature A basic auth, Feature B
Authentik) and any kind of outbound email (Feature C), we need a
**platform-level** admin account that sits above the family level.
The parent PIN and the family-scoped users in Feature A are
*family* concerns; this admin is the *app* concern.

**What the admin can do:**

- **Reset passwords for any user.** Both basic-auth users
  (Feature A) and any future auth method. For Authentik users
  (Feature B) the admin can *trigger* a reset through the
  Authentik API but can't see the actual password. For basic-auth
  users the admin can issue a one-time reset link emailed to the
  user, or set a temporary password directly.
- **Fire test emails.** A "send test email to <address>" form on
  the admin panel — uses the Feature C `send_email` helper to
  confirm the SMTP wiring is working end-to-end.
- **See the recent email log.** Filtered by category
  (`invite` / `reset` / `alert` / `test`) and timestamp. This is
  the "did the password reset email actually go out?" tool.
- **Manage global settings.** Open-ended — anything that's
  app-wide rather than per-family lives here. Examples that have
  come up: feature flags, default reward catalog, SMTP credentials
  UI (so the admin doesn't have to ssh in to change the Gmail
  app password), per-family feature overrides, kill switches
  (e.g. disable all chore-completion alerts globally during a
  weekend trip).

**Auth model for the admin themselves.** Two reasonable options:

- Email + password (same shape as Feature A basic auth, but
  stored in a separate `admin_users` table so a family-scoped
  data export can't include admin credentials by accident).
- A separate `ADMIN_PIN` env var, like the existing
  `PARENT_PIN` but platform-level. Simpler, no password reset
  loop needed, but a worse fit if the admin ever needs to
  delegate (multiple admins). Pick one when implementing;
  don't try to do both.

**Setup flows — this is the load-bearing part.** Since the
admin is a *new* concept, the project has to gracefully
transition from "no admin exists" to "admin exists" in two
different contexts:

1. **New installs.** On first start, the app detects
   `admin_users` is empty and refuses to serve normal traffic
   until an admin is created. Most natural shape: a
   `/setup-admin` route that the startup logic redirects all
   requests to, presents a one-screen form (email, password /
   PIN, confirm), and on submit creates the first admin row
   and starts serving the normal app. No env-var seeding
   needed; the form is the source of truth.
2. **Upgrades from pre-admin versions** (i.e. anything shipped
   before this feature lands). The existing single-tenant
   install at `\\10.40.2.11\appdata\summer\summer.db` and any
   other pre-existing instance needs an explicit path. Options:
   - A CLI command (e.g. `python -m app create-admin`) the
     operator runs once after pulling the new image. This is
     the cleanest for Docker deployments because the upgrade
     is two steps: pull, then run a one-off command.
   - An "admin setup required" banner on `/parent` (and any
     other authenticated route) with a link to `/setup-admin`,
     visible only while `admin_users` is empty. Simpler for
     non-CLI users but pollutes the parent UI with a
     permanent-until-resolved warning.

   The CLI command is preferred for production (Docker);
   the banner is the fallback for bare-metal installs. Pick
   at least one when implementing — *do not* ship the feature
   without a defined upgrade path, otherwise existing
   installs silently skip admin setup and the password-reset
   features (Feature C) become useless.

**Schema hints.** `admin_users` table with `id`, `email`,
`password_hash` (or null if using the PIN option), `created_at`,
`last_login_at`. A `password_reset_tokens` table (or columns on
`admin_users`) for the admin's own password reset, separate
from the family-user reset tokens. A `global_settings` key/value
table (or a single-row `settings` table) for the
open-ended "manage global settings" admin surface — don't
prematurely add columns for settings we haven't thought of
yet; a key/value table is easier to extend.

**Relationship to other features.** The admin **uses** Feature
C (SMTP) for test emails and as the transport for password
reset emails to family users. The admin **manages** Feature A
(basic auth) and Feature B (Authentik) users but doesn't
*replace* them — the admin is platform-level, families are
tenants. The admin's password reset is *also* a Feature C
consumer (the admin themselves can have a "forgot admin
password" flow, but that one needs a break-glass recovery
mechanism since there's no higher authority to email — write
that down in the spec when you get there).
