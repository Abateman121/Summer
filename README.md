# ☀️ Summer — Chore Tracker & Rewards

A lightweight, self-hosted web app for tracking summer chores and rewarding
kids with points they can spend on a catalog of rewards. Mobile-friendly and
designed to be opened on a phone from anywhere on the home Wi-Fi.

## Features

### Chore & reward tracking
- **Configurable chore catalog** — name, description, points, category,
  active/inactive flag.
- **Configurable reward catalog** — name, description, cost, icon,
  active/inactive flag.
- **Categories CRUD** — group chores by room / area / type.
- **Point value locked at event time** — editing a chore or reward later
  doesn't rewrite history.
- **Per-completion points override** — the parent can award a different
  value at approval time without editing the chore.
- **Per-redemption cost override** — the parent can discount a reward at
  approval time.

### Kid-driven flow (parent-approved)
- **Kid-initiated chore submissions** — kid picks a chore, adds an
  optional note, sends to the parent for approval.
- **Kid-initiated reward redemptions** — kid picks a reward from the
  catalog, adds an optional note, sends to the parent for approval.
- **Click-to-redeem on `/rewards`** — tapping a reward card takes the kid
  straight to a redemption form for that reward.
- **Parent approval queue** on `/parent` with inline Approve / Deny
  buttons for both chores and redemptions.
- **Deny with a reason** — the reason shows back to the kid on their
  timeline.
- **Insufficient-balance guard** — the parent can't accidentally
  over-spend a kid's balance when approving a redemption.

### Engagement
- **Leaderboard** with medals (gold / silver / bronze) on the home page.
- **7 achievement badges** — First Steps, Half Century, Century Club,
  Superstar, Week Warrior, Chore Champion, Big Spender. Computed
  lazily from existing data, no separate table.
- **Day streak** — consecutive days with at least one chore completed.

### Admin / parent
- **Parent PIN** gates all admin pages.
- **Undo for chores and rewards** — works for both pending and approved
  rows. Pending → marked denied; approved → removed from balance.
- **Kids, chores, rewards, categories CRUD** under the parent area.
- **Active / inactive flag** on chores and rewards — hide without
  deleting, so the kid's history stays intact.
- **Emoji / icon picker** for kid avatars, category icons, and reward
  icons.
- **Version chip** in the header so you can see what's deployed at a
  glance.

### Print & mobile
- **Per-page print button** on home, chores, and rewards pages.
- **Weekly summary** for the fridge (and a printable rewards page).
- **PWA** — "Add to Home Screen" on iOS feels like a native app.
- **Mobile-friendly responsive design** — works on a phone from the
  home Wi-Fi.
- **Dark mode** with a persisted toggle.

### Technical
- **Single SQLite file** — no external DB to run.
- **FastAPI + Jinja2**, server-rendered HTML, no JS framework.
- **Docker** deployment via `Dockerfile` + `docker-compose.yml`, with a
  prebuilt image on GitHub Container Registry.
- **Idempotent schema migrations** — safe to roll forward through
  versions without losing data.

---

## Quick start (Docker)

```bash
# 1. Configure your PIN
cp .env.example .env
# edit .env: set PARENT_PIN and SESSION_SECRET

# 2. Build and start
docker compose up -d --build

# 3. Open the app
#    http://localhost:8000        (or http://<host-ip>:8000 from a phone)
```

The first start seeds the database with two example kids, six categories, a
dozen chores, and a handful of rewards. Edit them from the Parent area
(default PIN is `1234`).

To stop: `docker compose down`. To wipe data: `docker compose down -v`.

### Use the prebuilt image (faster startup, no build step)

Every push to `main` builds and publishes a Docker image to
[GitHub Container Registry](https://github.com/Abateman121/Summer/pkgs/container/summer).
To skip the local `docker build` step:

```bash
docker compose pull        # fetch the latest image from ghcr.io
docker compose up -d        # start (uses the pulled image)
```

`docker compose up` will pull `ghcr.io/abateman121/summer:latest` and only
fall back to a local `build: .` if the pull fails — so the fast path is
taken on the happy case, and `docker compose build` always builds locally
for development.

> **If your GitHub repo is private**, authenticate docker to ghcr.io first:
> `docker login ghcr.io` with a [Personal Access Token](https://github.com/settings/tokens?type=beta)
> that has `read:packages` scope. Public repos work anonymously.

---

## Run without Docker (for development)

```bash
python -m venv .venv && source .venv/bin/activate     # optional
pip install -r requirements.txt
cp .env.example .env                                  # then edit

uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

The SQLite database is created at `./data/summer.db` by default. Override
with `DATABASE_URL=sqlite:///some/other/path.db`.

---

## Using it from an iPhone

1. Make sure your phone is on the same Wi-Fi as the host running Docker.
2. Find the host's LAN IP (e.g. `192.168.1.42`).
3. Open Safari and go to `http://192.168.1.42:8000`.
4. Tap the **Share** button → **Add to Home Screen**.
5. It'll now launch as a full-screen app with the ☀️ icon.

> Want to reach it when away from home? Put it behind a Cloudflare Tunnel,
> Tailscale, or a Wireguard VPN — the app has no built-in auth beyond the
> parent PIN, so don't expose it directly to the public internet.

---

## How it works

### Point value locking
The point value for a chore (or cost of a reward) is **denormalized** into
the completion / redemption record at the time of the event. If you change
"Tidy room" from 15 → 20 points next month, the kid's history still shows
the 15 they earned. This is the whole point of the "earn at completion"
behavior — see [app/models.py](app/models.py).

For kid-initiated requests the value is captured at **approval time**, not
request time, so an admin edit between request and approval doesn't shift
the value the kid sees.

### Streak
A kid's "day streak" is the length of the run of consecutive days with at
least one chore completed, ending today or yesterday. They have until end
of day to extend an active streak; missing a full day resets it to 0. See
[app/achievements.py](app/achievements.py).

### Achievements
Computed lazily from existing data — no scheduled job, no separate table.
The badge is "earned" the moment the underlying condition is met. See
`compute_badges` in [app/achievements.py](app/achievements.py).

### Kid-initiated requests
Kids can submit completed chores or redemption requests directly from
their profile (or by clicking a reward on `/rewards`). The request lands
in the parent's "Pending approvals" queue on `/parent` with `status =
'pending'` and the point value unset. The parent can then:

- **Approve** — captures the chore's points (or the reward's cost) into
  the row at approval time, so edits in between don't change the value
  the kid sees, and flips the status to `approved`.
- **Deny with a reason** — the row stays in the audit trail with
  `status = 'denied'`; the reason is shown back to the kid on their
  timeline.
- **Approve without enough points** — blocked; the parent sees a clear
  error so they can't accidentally over-spend a kid's balance.

Only `status = 'approved'` rows count toward balance, streak, badges,
and the weekly summary. Pending rows are not counted anywhere until a
parent decides their fate.

### Print view
`/print` is a stand-alone layout with no nav, no bottom bar, no buttons
other than Print. It uses `@media print` rules in
[app/static/print.css](app/static/print.css). Open it in any browser, hit
Print, check the preview, and send to your printer.

---

## Project layout

```
Summer/
├── app/
│   ├── main.py            # FastAPI app + all routes
│   ├── database.py        # engine, session, init
│   ├── models.py          # SQLAlchemy ORM
│   ├── auth.py            # PIN login + session
│   ├── achievements.py    # streak, balance, badge math (pure functions)
│   ├── seed.py            # first-start example data
│   ├── static/            # CSS, JS, icons
│   └── templates/         # 11 Jinja2 pages
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
├── .gitignore
├── CLAUDE.md
└── README.md
```

---

## Configuration (env vars)

| Var | Default | Purpose |
|---|---|---|
| `PARENT_PIN` | `1234` | PIN required to access admin pages |
| `SESSION_SECRET` | dev-only string | Secret used to sign session cookies — **set this in production** |
| `TZ` | `UTC` | IANA timezone for streak/date math (e.g. `America/New_York`) |
| `DATABASE_URL` | `sqlite:///<project>/data/summer.db` | Override SQLite location |
| `HOST` / `PORT` | `0.0.0.0` / `8000` | Bind address for uvicorn |

---

## Future

The full design notes for these are in [CLAUDE.md](CLAUDE.md) under
"Deferred features" — what's below is the at-a-glance summary. None of
these are built yet; pick one up when the time comes.

- **Feature A — Multi-tenant family switching.** Let friends use the
  app for their own families, with strict data isolation per family,
  per-family parent PINs, and a parent-invite flow.
- **Feature B — OAuth with Authentik.** OIDC / OAuth login against a
  self-hosted Authentik instance (email or username). Composes with
  Feature A so each Authentik user maps to a family and a role.
- **Feature C — SMTP for Gmail.** Transactional email for parent
  invites, basic-auth password resets, chore-completion alerts to
  parents, and an admin "test fire" button. Authentik users bypass
  the password-reset path — Authentik handles that itself.
- **Feature D — Negative points / point adjustments.** Adjust
  already-approved chore completions in place, plus a parent-driven
  deduction flow for negative behaviors (fighting, missed routines,
  etc.) with a "category" tag the parent fills out.
- **Feature E — Platform-level admin account.** A new platform-level
  admin (above the family level) that can reset passwords for any
  user, fire test emails, see the recent email log, and manage
  global settings. Includes a `/setup-admin` first-run wizard for
  new installs and a defined upgrade path for existing installs.

---

## Development tips

- `uvicorn app.main:app --reload` gives you hot reload on Python file changes.
- Templates and static files reload automatically — no build step.
- The DB file lives at `data/summer.db` by default. Delete it to start fresh.
- To re-seed: `rm data/summer.db && uvicorn app.main:app` (or just delete via
  the Parent UI).

---

## License

MIT — do whatever you want with it.
