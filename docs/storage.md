# File storage & lifecycle

## Folder layout

Everything lives under a single **`DATA_ROOT`** on the host (bind-mounted as `/data` in Docker).

```
DATA_ROOT/
├── Artist - Album One/
│   ├── source/              # uploads: FLAC, WAV, cover.jpg
│   ├── 16-48/             # converted WAV (shown as 16/48 in UI)
│   ├── artwork_720x480.jpg  # processed DVD artwork
│   └── output/              # single-album job: disc.iso + VIDEO_TS
├── Artist - Album Two/
│   └── source/
│       └── ...
└── _jobs/
    └── R.P. No. 001 - RE/
        └── output/          # multi-album job output
            ├── disc.iso
            └── VIDEO_TS/
```

| Job type | Output location |
|----------|-----------------|
| **1 album** | `DATA_ROOT/<album-name>/output/` |
| **2+ albums** | `DATA_ROOT/_jobs/<burn-code>/output/` |

Postgres catalog (`burns` table) is stored in the Docker `pgdata` volume — not in `DATA_ROOT`.

## Uploads

Web UI reads **album** and **artist** tags from your audio files (via ffprobe) and names the workspace:

```
Artist - Album   →   DATA_ROOT/Artist - Album/source/
```

| Priority | Tag fields used |
|----------|-----------------|
| Artist | `album_artist`, `albumartist`, `band`, `artist` |
| Album | `album` |

If tags are missing, fallbacks are: ZIP filename, uploaded folder name, or an optional override in the UI.

Duplicate names get a suffix: `Artist - Album (2)`.

## Retention options (Web UI)

After each successful job, cleanup runs based on your choices:

| Option | Default | What it controls |
|--------|---------|------------------|
| **Keep files after job** | On | Master toggle — off deletes everything generated |
| Source audio & cover | On | `source/` folder |
| Converted WAV (16/48) | Off | `16-48/` folder |
| Processed artwork | On | `artwork_720x480.jpg` |
| ISO image | On | `disc.iso` |
| VIDEO_TS folder | Off | `VIDEO_TS/` (ISO is usually enough) |

When **Keep files after job** is unchecked, all generated files are removed regardless of the sub-checkboxes. The Postgres burn record is always kept.

### Grace period before deletion

Unchecked file types are **not deleted immediately**. They are scheduled for deletion after a grace period (default **3 hours**, configurable via `RETENTION_DELAY_HOURS`).

This gives you time to download the ISO or log after the job finishes. The UI shows a countdown for each scheduled deletion.

Set `RETENTION_DELAY_HOURS=0` to delete immediately (old behavior).

## Hidden runtime folders

These are created automatically under `DATA_ROOT`:

| Folder | Purpose |
|--------|---------|
| `.jobs/` | Persisted job state (survives refresh/restart) |
| `.retention-queue/` | Scheduled deletions with grace-period timers |
| `.staging-*` | Temporary upload staging (removed after finalize) |

## What happens after a burn

1. Pipeline converts, authors DVD, optionally burns disc
2. DB row created: `R.P. No. XXX - RE`
3. Retention schedules or removes files per your UI choices
4. Job log shows what was scheduled or removed
5. Background worker deletes scheduled files when the timer expires

**Typical workflow** (defaults):

- Source albums stay in `source/`
- Converted WAV removed (re-created next run)
- ISO kept in `output/`
- VIDEO_TS removed (large, redundant with ISO)

**Minimal disk usage**: uncheck "Keep files after job" — only the Postgres record remains.

## Docker mount

```yaml
volumes:
  - ${DATA_ROOT:-/opt/album-dvd-burner}:/data
environment:
  DATA_ROOT: /data
```

One mount, one env var. No separate `input/` and `dvd/` folders.
