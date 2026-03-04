"""RepoMind CLI entrypoint."""

import typer

from repomind.benchmark_runner import run_benchmark
from repomind.orchestrator import run_audit

app = typer.Typer(
    name="repomind",
    help="RepoMind: repository audit and analysis.",
    no_args_is_help=True,
)


@app.command()
def audit(
    path: str = typer.Argument(..., help="Path to the repository to audit."),
    markdown_report: bool = typer.Option(False, "--markdown-report", help="Write repomind_report.md to repomind_report/."),
) -> None:
    """Run an audit on a repository."""
    run_audit(path, markdown_report=markdown_report)


@app.command()
def version() -> None:
    """Show the RepoMind version."""
    typer.echo("0.1.0")


@app.command()
def benchmark(
    paths: list[str] = typer.Argument(..., help="One or more repository paths to benchmark."),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Print benchmark results as JSON instead of a table.",
    ),
) -> None:
    """Run deterministic architecture benchmark across repositories."""
    if not paths:
        raise typer.BadParameter("At least one repository path is required.")
    run_benchmark(paths, json_output=json_output)


def main() -> None:
    """Entry point for the repomind CLI."""
    app()


if __name__ == "__main__":
    main()
