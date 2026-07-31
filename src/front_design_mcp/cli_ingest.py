"""Ingest CLI — run offline/online catalog ingest into SQLite."""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Annotated

import typer

from front_design_mcp import __version__
from front_design_mcp.adapters import ADAPTER_SOURCE_IDS
from front_design_mcp.config import get_settings
from front_design_mcp.ingest.pipeline import run_ingest
from front_design_mcp.logging_utils import configure_logging, get_logger

app = typer.Typer(
    name="front-design-ingest",
    help="Ingest frontend catalogs into the local SQLite store.",
    add_completion=False,
)


class SourceChoice(StrEnum):
    all = "all"
    motion = "motion"
    magicui = "magicui"
    shadcn = "shadcn"
    radix = "radix"
    gsap = "gsap"


@app.callback(invoke_without_command=True)
def ingest(
    source: Annotated[
        SourceChoice,
        typer.Option("--source", help="Source adapter id or 'all'."),
    ] = SourceChoice.all,
    offline: Annotated[
        bool,
        typer.Option("--offline/--online", help="Use fixtures vs network ingest."),
    ] = True,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Print full IngestReport as JSON."),
    ] = False,
) -> None:
    """Ingest catalog(s) into SQLite from fixtures (default) or network registries."""
    settings = get_settings()
    configure_logging(settings.log_level)
    log = get_logger("cli_ingest")

    if not offline and not settings.enable_network_ingest:
        typer.echo(
            "Network ingest is disabled "
            "(FRONT_DESIGN_ENABLE_NETWORK_INGEST=false). Use --offline or enable it.",
            err=True,
        )
        raise typer.Exit(code=2)

    targets = list(ADAPTER_SOURCE_IDS) if source == SourceChoice.all else [source.value]
    mode = "offline" if offline else "online"
    log.info(
        "ingest_start",
        version=__version__,
        sources=targets,
        mode=mode,
        db_path=str(settings.resolve_db_path()),
    )

    try:
        report = run_ingest(sources=targets, online=not offline, settings=settings)
    except Exception as exc:  # noqa: BLE001
        log.error("ingest_failed", error=str(exc))
        typer.echo(f"Ingest failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if json_out:
        typer.echo(json.dumps(report.to_dict(), indent=2))
    else:
        typer.echo(
            f"front-design-ingest v{__version__} — "
            f"mode={report.mode} ok={report.ok} "
            f"resources={report.total_resources} chunks={report.total_chunks}"
        )
        for s in report.sources:
            err = f" ERROR={s.error}" if s.error else ""
            typer.echo(f"  {s.source_id}: resources={s.resources} chunks={s.chunks}{err}")
        typer.echo(f"db={report.db_path}")

    if not report.ok:
        raise typer.Exit(code=1)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
