# First-time setup (Arcane / Ubuntu VM)

## 1. Host data directory

```bash
sudo mkdir -p /opt/album-dvd-burner
sudo chown -R "$USER:$USER" /opt/album-dvd-burner
```

Album workspaces are created automatically on upload. No need for separate `input/` or `dvd/` folders.

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
docker compose -f docker-compose.arcane.yml up -d --build
```

This automatically creates Postgres database `album_dvd` and the `burns` table on first boot.

Verify:

```bash
docker compose -f docker-compose.arcane.yml exec postgres \
  psql -U album_dvd -d album_dvd -c '\dt'
```

## 4. Open the UI

http://\<vm-ip\>:8080

Upload a folder or ZIP — the workspace name is auto-detected from audio tags (optional override in the UI). Select albums, configure retention, start job.

If `WEB_API_KEY` is set, open the UI with `http://<vm-ip>:8080/?key=YOUR_KEY`.

## If the DB is missing

```bash
docker compose -f docker-compose.arcane.yml exec web album-dvd-burner init-db
```

Or reset Postgres entirely:

```bash
docker compose -f docker-compose.arcane.yml down -v
docker compose -f docker-compose.arcane.yml up -d --build
```

Album files in `/opt/album-dvd-burner/` are not affected by a Postgres reset.
