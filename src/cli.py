"""CLI entry point. `python -m src.cli --help`."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from src.kb.ingestion import ingest_path
from src.kb.store import KBStore

app = typer.Typer(
    help="ISO 26262 validation tool — Claude-powered V-model right-side checks.",
    no_args_is_help=True,
)
console = Console()


@app.command()
def ingest(path: Path = typer.Argument(..., exists=True, help="File or directory")) -> None:
    """Ingest CSV / Excel / Cradle XML artefacts into the KB."""
    console.print(f"[bold]Ingesting[/bold] {path}")
    summary = ingest_path(path)

    table = Table(title="Ingestion summary")
    table.add_column("Artefact")
    table.add_column("Rows", justify="right")
    table.add_row("Requirements", str(summary.requirements))
    table.add_row("Test cases", str(summary.test_cases))
    table.add_row("Defects", str(summary.defects))
    table.add_row("Trace links (auto)", str(summary.trace_links))
    console.print(table)

    if summary.errors:
        console.print("[red]Errors:[/red]")
        for e in summary.errors:
            console.print(f"  - {e}")


@app.command()
def stats() -> None:
    """Show current KB row counts."""
    store = KBStore()
    s = store.stats()
    table = Table(title="KB stats")
    table.add_column("Collection")
    table.add_column("Rows", justify="right")
    for k, v in s.items():
        table.add_row(k, str(v))
    console.print(table)


@app.command()
def search(query: str, k: int = 5) -> None:
    """Semantic search over ingested requirements."""
    store = KBStore()
    hits = store.find_similar_requirements(query, k=k)
    table = Table(title=f"Top {k} similar requirements")
    table.add_column("ID")
    table.add_column("Distance", justify="right")
    table.add_column("Preview")
    for h in hits:
        preview = h["document"].replace("\n", " ")[:100]
        table.add_row(h["id"], f"{h['distance']:.3f}", preview)
    console.print(table)


@app.command()
def validate() -> None:
    """Run validation (coverage / testability / traceability). [Phase 2 — coming soon]"""
    console.print(
        "[yellow]Phase 2 not yet implemented.[/yellow] "
        "The Claude client, prompts, and structured output schemas are scaffolded "
        "in src/engine/; wire up the orchestrator next."
    )


@app.command()
def generate_tests() -> None:
    """Generate test cases for requirements lacking coverage. [Phase 4 — coming soon]"""
    console.print(
        "[yellow]Phase 4 not yet implemented.[/yellow] "
        "See src/engine/claude_client.py::ClaudeClient.generate_test_case "
        "for the signature and grounding contract."
    )


if __name__ == "__main__":
    app()
