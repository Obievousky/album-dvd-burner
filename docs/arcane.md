# Deploying with Arcane (remote Ubuntu VM)

Use the repository's primary `docker-compose.yml` on your Ubuntu VM, then open **http://\<vm-ip\>:8080**.

## Data layout

All files under one host path (`DATA_ROOT`, default `/opt/album-dvd-burner`):

```
/opt/album-dvd-burner/
├── Pink Floyd - Wish You Were Here/
│   ├── source/       ← uploads land here
│   └── output/       ← ISO after single-album burn
└── _jobs/
    └── R.P. No. 001 - RE/
        └── output/   ← ISO after multi-album burn
```

See [storage.md](storage.md) for retention options.

## Deploy

1. `sudo mkdir -p /opt/album-dvd-burner && sudo chown $USER /opt/album-dvd-burner`
2. Arcane → Stacks → `docker-compose.yml`
3. Set env: `POSTGRES_PASSWORD`, `DATA_ROOT=/opt/album-dvd-burner`, `DVD_PRIVILEGED=true`
4. Pass optical drive from Proxmox first → [proxmox.md](proxmox.md)

## Web UI workflow

1. Enter album name → upload folder or ZIP
2. Select one or more albums
3. Configure **File retention** (what to keep after job)
4. Start job → watch log → check burn history
