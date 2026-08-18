# Album DVD Burner

Dockerized pipeline that turns album folders into **Lplex-style audio DVDs**, logs burns to PostgreSQL, and optionally burns discs. Includes a **web UI** with per-album workspaces and configurable file retention.

## Folder layout

Each album/artist gets its own workspace under `DATA_ROOT`:

```
DATA_ROOT/Artist - Album/
├── source/              # your FLAC, WAV, cover.jpg
├── 16-48/               # converted audio (labelled 16/48 in UI)
├── artwork_720x480.jpg  # processed artwork (auto)
└── output/              # disc.iso (single-album jobs)
```

Multi-album burns output to `DATA_ROOT/_jobs/R.P. No. XXX - RE/output/`.

Hidden runtime folders (auto-managed): `.jobs/`, `.retention-queue/`, `.staging-*`.

## Quick start

```bash
cp .env.example .env
./docker/provision.sh
docker compose up -d --build
```

The provisioning script creates and assigns the data directory to the non-root app
account. Set `DVD_GID` in `.env` to the numeric group of your optical device before
burning. Open **http://localhost:8080**.

If `WEB_API_KEY` is set in `.env`, append `?key=YOUR_KEY` to the URL (all API routes except `/api/health` require it).

## Web UI

- Upload albums into named workspaces (`source/` subfolder)
- Select multiple albums → multiple DVD titles on one disc
- Delete albums you no longer need
- **File retention** controls what stays on disk after each job:
  - Keep source, converted WAV, artwork, ISO, VIDEO_TS
  - Or uncheck "Keep files after job" to delete everything (DB record stays)
  - Unchecked files are deleted after a **grace period** (default 3h; see `RETENTION_DELAY_HOURS`)
- Live job log, downloads, and burn history
- Safe page refresh — active jobs restore from session + disk

## CLI

```bash
album-dvd-burner process "/data/Artist - Album" --burn
album-dvd-burner list-albums
album-dvd-burner serve --port 8080
album-dvd-burner init-db
```

Retention options are configured in the web UI; CLI `process` uses default retention settings.

## Remote VM (Proxmox)

1. [docs/setup.md](docs/setup.md) — first-time deploy with the primary Compose file
2. [docs/storage.md](docs/storage.md) — folder layout & retention
3. [docs/proxmox.md](docs/proxmox.md) — optical drive passthrough

## Environment

| Variable | Default | Purpose |
|----------|---------|---------|
| `DATA_ROOT` | `./data` (local) / `/opt/album-dvd-burner` (server) | All album workspaces |
| `POSTGRES_HOST` | `localhost` | Postgres host |
| `POSTGRES_PORT` | `5432` | Postgres port |
| `POSTGRES_DB` | `album_dvd` | Database name |
| `POSTGRES_USER` | `album_dvd` | Database user |
| `POSTGRES_PASSWORD` | `album_dvd` | PostgreSQL password |
| `DVD_DEVICE` | `/dev/sr0` | Burner device |
| `DVD_STANDARD` | `ntsc` | `ntsc` or `pal` |
| `APP_UID` / `APP_GID` | `10001` | Dedicated non-root account that owns application data |
| `DVD_GID` | `24` | Optical-drive group; set it from `stat -c '%g' /dev/sr0` |
| `BURN_ID_PREFIX` | `R.P. No.` | Burn code prefix (`R.P. No. 001 - RE`) |
| `WEB_PORT` | `8080` | Web UI port |
| `WEB_API_KEY` | _(empty)_ | Protects all `/api/*` routes except `/api/health`; use `?key=` in the URL |
| `RETENTION_DELAY_HOURS` | `3` | Grace period before deleting unchecked files (`0` = immediate) |

Local `docker-compose.yml` exposes Postgres on port 5432 for development only.

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```
