import re
from dataclasses import dataclass
from datetime import datetime, timezone

from .config import Settings
from .dvd_author import AlbumTitle


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS burns (
    id SERIAL PRIMARY KEY,
    burn_code VARCHAR(32) NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    iso_path TEXT NOT NULL,
    dvd_device TEXT,
    dvd_standard VARCHAR(8) NOT NULL,
    albums JSONB NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    burned_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS burns_created_at_idx ON burns (created_at DESC);
"""


@dataclass
class BurnRecord:
    burn_code: str
    iso_path: str
    dvd_standard: str
    albums: list[dict]
    metadata: dict
    dvd_device: str | None = None
    burned_at: datetime | None = None


def connect(settings: Settings):
    try:
        import psycopg2
    except ImportError as exc:
        raise RuntimeError(
            "PostgreSQL support is not installed. Install the project dependencies first."
        ) from exc
    return psycopg2.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        dbname=settings.postgres_db,
        user=settings.postgres_user,
        password=settings.postgres_password,
    )


def ensure_schema(settings: Settings) -> None:
    with connect(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(SCHEMA_SQL)
        conn.commit()


def burn_code_pattern(prefix: str) -> str:
    escaped = re.escape(prefix.strip())
    return rf"^{escaped} [0-9]{{3}} - RE$"


def parse_burn_number(burn_code: str) -> int | None:
    match = re.search(r" ([0-9]{3}) - RE$", burn_code)
    if match is None:
        return None
    return int(match.group(1))


def next_burn_code(settings: Settings) -> str:
    pattern = burn_code_pattern(settings.burn_id_prefix)
    with connect(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT burn_code
                FROM burns
                WHERE burn_code ~ %s
                ORDER BY burn_code DESC
                LIMIT 1
                """,
                (pattern,),
            )
            row = cur.fetchone()

    if row is None:
        number = 1
    else:
        previous = parse_burn_number(row[0])
        number = (previous or 0) + 1

    return f"{settings.burn_id_prefix} {number:03d} - RE"


def album_metadata(album: AlbumTitle) -> dict:
    return {
        "name": album.name,
        "source_folder": str(album.source_folder),
        "work_dir": str(album.work_dir),
        "track_count": len(album.tracks),
        "tracks": [track.name for track in album.tracks],
        "sample_rate": album.audio_info.sample_rate,
        "bit_depth": album.audio_info.bit_depth,
        "channels": album.audio_info.channels,
        "artwork": str(album.artwork),
    }


def insert_burn(settings: Settings, record: BurnRecord) -> str:
    try:
        from psycopg2.extras import Json
    except ImportError as exc:
        raise RuntimeError(
            "PostgreSQL support is not installed. Install the project dependencies first."
        ) from exc
    ensure_schema(settings)
    with connect(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO burns (
                    burn_code, iso_path, dvd_device, dvd_standard, albums, metadata, burned_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING burn_code
                """,
                (
                    record.burn_code,
                    record.iso_path,
                    record.dvd_device,
                    record.dvd_standard,
                    Json(record.albums),
                    Json(record.metadata),
                    record.burned_at,
                ),
            )
            burn_code = cur.fetchone()[0]
        conn.commit()
    return burn_code


def mark_burned(settings: Settings, burn_code: str) -> None:
    with connect(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE burns
                SET burned_at = %s, dvd_device = COALESCE(dvd_device, %s)
                WHERE burn_code = %s
                """,
                (datetime.now(timezone.utc), settings.dvd_device, burn_code),
            )
        conn.commit()


def list_burns(settings: Settings, limit: int = 50) -> list[dict]:
    ensure_schema(settings)
    with connect(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT burn_code, created_at, iso_path, dvd_device, dvd_standard,
                       albums, metadata, burned_at
                FROM burns
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()

    return [
        {
            "burn_code": row[0],
            "created_at": row[1].isoformat() if row[1] else None,
            "iso_path": row[2],
            "dvd_device": row[3],
            "dvd_standard": row[4],
            "albums": row[5],
            "metadata": row[6],
            "burned_at": row[7].isoformat() if row[7] else None,
        }
        for row in rows
    ]
