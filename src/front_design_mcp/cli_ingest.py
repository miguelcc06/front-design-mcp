"""Ingest CLI — run offline/online catalog ingest into the configured store."""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Annotated, Literal

import typer

from front_design_mcp import __version__
from front_design_mcp.adapters import ADAPTER_SOURCE_IDS
from front_design_mcp.config import get_settings
from front_design_mcp.ingest.pipeline import run_ingest
from front_design_mcp.logging_utils import configure_logging, get_logger
from front_design_mcp.store.base import SyncOutcome

app = typer.Typer(
    name="front-design-ingest",
    help=(
        "Ingest frontend catalogs into the configured store (SQLite or PostgreSQL). "
        "Exit codes: 0=success, 1=failed, 2=partial "
        "(some sources/items failed while others succeeded)."
    ),
    add_completion=False,
)


class SourceChoice(StrEnum):
    all = "all"
    motion = "motion"
    magicui = "magicui"
    shadcn = "shadcn"
    radix = "radix"
    gsap = "gsap"
    curated = "curated"


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
    prune: Annotated[
        bool,
        typer.Option(
            "--prune/--no-prune",
            help="Delete store rows that disappeared from a source (default: prune).",
        ),
    ] = True,
    embed: Annotated[
        bool,
        typer.Option(
            "--embed/--no-embed",
            help=(
                "Generate embeddings for changed chunks (default: embed). "
                "No-op when FRONT_DESIGN_EMBEDDING_PROVIDER=none."
            ),
        ),
    ] = True,
    backend: Annotated[
        Literal["sqlite", "postgres"] | None,
        typer.Option(
            "--backend",
            help="Override FRONT_DESIGN_STORE_BACKEND for this run (sqlite|postgres).",
        ),
    ] = None,
) -> None:
    """Ingest catalog(s) from fixtures (default) or network registries.

    Exit codes: 0 on SUCCESS, 1 on FAILED, 2 on PARTIAL.
    """
    settings = get_settings()
    if backend is not None:
        settings = settings.model_copy(update={"store_backend": backend})
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
    if settings.store_backend == "postgres":
        db_log = settings.redacted_database_url() or "postgres"
    else:
        db_log = str(settings.resolve_db_path())
    log.info(
        "ingest_start",
        version=__version__,
        sources=targets,
        mode=mode,
        backend=settings.store_backend,
        db_path=db_log,
        prune=prune,
        embed=embed,
    )

    try:
        report = run_ingest(
            sources=targets,
            online=not offline,
            settings=settings,
            prune=prune,
            embed=embed,
        )
    except Exception as exc:  # noqa: BLE001
        log.error("ingest_failed", error=str(exc))
        typer.echo(f"Ingest failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if json_out:
        typer.echo(json.dumps(report.to_dict(), indent=2))
    else:
        typer.echo(
            f"front-design-ingest v{__version__} — "
            f"mode={report.mode} backend={report.backend} "
            f"outcome={report.outcome.value} ok={report.ok} "
            f"resources={report.total_resources} "
            f"written={report.resources_written}/{report.chunks_written} "
            f"unchanged={report.chunks_unchanged} "
            f"deleted={report.resources_deleted}/{report.chunks_deleted} "
            f"embeddings={report.embeddings_written}+{report.embeddings_reused}r"
        )
        for s in report.sources:
            err = f" ERROR={s.error}" if s.error else ""
            typer.echo(
                f"  {s.source_id}: resources={s.resources} "
                f"(w={s.resources_written}/d={s.resources_deleted}) "
                f"chunks={s.chunks} "
                f"(w={s.chunks_written}/u={s.chunks_unchanged}/d={s.chunks_deleted}) "
                f"emb={s.embeddings_written}+{s.embeddings_reused}r "
                f"pruned={s.pruned}{err}"
            )
        typer.echo(f"db={report.db_path}")

    if report.outcome == SyncOutcome.FAILED:
        raise typer.Exit(code=1)
    if report.outcome == SyncOutcome.PARTIAL:
        raise typer.Exit(code=2)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
