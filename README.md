# ☀️ Summer — Chore Tracker & Rewards

A lightweight, self-hosted web app for tracking summer chores and rewarding
kids with points they can spend on a catalog of rewards. Mobile-friendly and
designed to be opened on a phone from anywhere on the home Wi-Fi.

- **Track chores** with adjustable point values
- **Award points** when a chore is marked complete (locked in at the time)
- **Deduct points** when kids redeem rewards from a configurable catalog
- **Lightweight** — single SQLite file, FastAPI + Jinja2, no JS framework
- **Fun** — leaderboard, achievement badges, day streaks
- **Printable** weekly summary for the fridge
- **PWA** — "Add to Home Screen" on iOS feels like a native app
- **Parented** — admin actions are PIN-gated; kids see a read-only view

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

### Streak
A kid's "day streak" is the length of the run of consecutive days with at
least one chore completed, ending today or yesterday. They have until end
of day to extend an active streak; missing a full day resets it to 0. See
[app/achievements.py](app/achievements.py).

### Achievements
Computed lazily from existing data — no scheduled job, no separate table.
The badge is "earned" the moment the underlying condition is met. See
`compute_badges` in [app/achievements.py](app/achievements.py).

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
│   └── templates/         # 10 Jinja2 pages
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

## Development tips

- `uvicorn app.main:app --reload` gives you hot reload on Python file changes.
- Templates and static files reload automatically — no build step.
- The DB file lives at `data/summer.db` by default. Delete it to start fresh.
- To re-seed: `rm data/summer.db && uvicorn app.main:app` (or just delete via
  the Parent UI).

---

## License

MIT — do whatever you want with it.
