# First-time setup (Ubuntu VM)

## 1. Host data directory

Set `DATA_ROOT` below, then run `./docker/provision.sh`. It creates the directory and
assigns it to the app's non-root account. No separate `input/` or `dvd/` folders are
needed.

## 2. Environment file

```bash
cp .env.example .env
```

Minimum required:

```env
DATA_ROOT=/opt/album-dvd-burner
POSTGRES_PASSWORD=pick-a-strong-password-here
DVD_DEVICE=/dev/sr0
```

## 3. Start the stack

```bash
./docker/provision.sh
docker compose up -d
```

`compose.yml` pulls the prebuilt image (set `APP_VERSION` to pin a release, or leave it `latest`). It automatically creates Postgres database `album_dvd` and the `burns` table on first boot.

Verify:

```bash
docker compose exec postgres \
  psql -U album_dvd -d album_dvd -c '\dt'
```

## 4. Open the UI

http://\<vm-ip\>:8080

Upload a folder or ZIP — the workspace name is auto-detected from audio tags (optional override in the UI). Select albums, configure retention, start job.

If `WEB_API_KEY` is set, open the UI with `http://<vm-ip>:8080/?key=YOUR_KEY`.

## If the DB is missing

```bash
docker compose exec web album-dvd-burner init-db
```

Or reset Postgres entirely:

```bash
docker compose down -v
docker compose up -d
```

Album files in `/opt/album-dvd-burner/` are not affected by a Postgres reset.
