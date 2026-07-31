"""Ingest CLI stub — full implementation in Package B."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

import typer

from front_design_mcp import __version__
from front_design_mcp.adapters import ADAPTER_SOURCE_IDS
from front_design_mcp.config import get_settings
from front_design_mcp.logging_utils import configure_logging, get_logger

app = typer.Typer(
    name="front-design-ingest",
    help="Ingest frontend catalogs into the local store (Package B implements adapters).",
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
) -> None:
    """Ingest catalog(s) into SQLite. Stub for Package A — adapters land in Package B."""
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
        "ingest_stub",
        version=__version__,
        sources=targets,
        mode=mode,
        msg="Package B will implement real ingest; adapters currently raise NotImplementedError.",
    )
    typer.echo(
        f"front-design-ingest v{__version__} — stub OK "
        f"(sources={','.join(targets)}, mode={mode}). "
        "Implement adapters in Package B."
    )


def main() -> None:
    app()


if __name__ == "__main__":
    main()
