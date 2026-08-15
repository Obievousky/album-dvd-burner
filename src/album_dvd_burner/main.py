from __future__ import annotations

from pathlib import Path

import click

from .config import Settings
from .pipeline import run_pipeline
from .workspaces import RetentionOptions, album_workspace, list_album_workspaces


def _settings_with_overrides(
    settings: Settings,
    *,
    device: str | None,
    standard: str | None,
) -> Settings:
    if not any([device, standard]):
        return settings
    return Settings(
        postgres_host=settings.postgres_host,
        postgres_port=settings.postgres_port,
        postgres_db=settings.postgres_db,
        postgres_user=settings.postgres_user,
        postgres_password=settings.postgres_password,
        dvd_device=device or settings.dvd_device,
        dvd_standard=(standard or settings.dvd_standard).lower(),
        data_root=settings.data_root,
        burn_id_prefix=settings.burn_id_prefix,
        web_api_key=settings.web_api_key,
        retention_delay_hours=settings.retention_delay_hours,
    )


@click.group()
@click.version_option()
def cli() -> None:
    """Convert albums to Lplex-style audio DVDs, catalog burns, and optionally burn discs."""


@cli.command("process")
@click.argument("album_folders", nargs=-1, required=True, type=click.Path(exists=True, file_okay=False))
@click.option("--burn/--no-burn", default=True, show_default=True, help="Burn the ISO to DVD_DEVICE after authoring")
@click.option("--device", default=None, help="DVD burner device path (overrides DVD_DEVICE)")
@click.option("--standard", type=click.Choice(["ntsc", "pal"]), default=None, help="DVD video standard")
@click.option("--burn-code", default=None, help="Override burn ID (default: next R.P. No. XXX - RE from DB)")
def process(
    album_folders: tuple[str, ...],
    burn: bool,
    device: str | None,
    standard: str | None,
    burn_code: str | None,
) -> None:
    """Process one or more album folders into a single multi-title DVD."""
    settings = _settings_with_overrides(Settings.from_env(), device=device, standard=standard)
    folders = [Path(path).resolve() for path in album_folders]

    def on_progress(stage: str, message: str) -> None:
        click.echo(message)

    result = run_pipeline(
        folders,
        settings,
        burn=burn,
        burn_code=burn_code,
        on_progress=on_progress,
    )
    click.echo(f"Done: {result.burn_code} → {result.output_dir}")


@cli.command("list-albums")
def list_albums() -> None:
    """List album workspaces under DATA_ROOT."""
    settings = Settings.from_env()
    for workspace in list_album_workspaces(settings.data_root):
        click.echo(workspace.name)


@cli.command("init-db")
def init_db() -> None:
    """Create PostgreSQL tables if they do not exist."""
    from .database import ensure_schema

    ensure_schema(Settings.from_env())
    click.echo("Database schema ready.")


@cli.command("serve")
@click.option("--host", default="0.0.0.0", show_default=True)
@click.option("--port", default=8080, show_default=True)
def serve(host: str, port: int) -> None:
    """Start the web UI."""
    import uvicorn

    from .web.app import create_app

    uvicorn.run(create_app(), host=host, port=port)


if __name__ == "__main__":
    cli()
