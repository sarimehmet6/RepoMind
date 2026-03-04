"""Benchmark runner for RepoMind's deterministic Architecture Risk Engine."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from rich.box import ROUNDED
from rich.console import Console
from rich.table import Table

from repomind.scanners.repo_scanner import scan_repository

console = Console()


def _extract_benchmark_row(scan_result: Dict[str, Any]) -> Dict[str, Any]:
    """Extract benchmark metrics from a single scan result."""
    path = scan_result.get("path", "")
    repo_name = Path(path).name or path

    arch = scan_result.get("architecture_score") or {}
    score = arch.get("architecture_health_percentage", arch.get("normalized_score", 0))

    total_files = scan_result.get("total_files", scan_result.get("source_files", 0))
    long_files = scan_result.get("total_long_files", 0)
    cycles = scan_result.get("total_cycles", 0)

    dep_stats = scan_result.get("dependency_stats") or {}
    ratio_raw = dep_stats.get("cross_folder_dependency_ratio")
    cross_ratio = float(ratio_raw) if isinstance(ratio_raw, (int, float)) else 0.0
    cross_ratio_pct = 100.0 * cross_ratio

    return {
        "repo": repo_name,
        "path": path,
        "total_files": total_files,
        "long_file_count": long_files,
        "cycle_count": cycles,
        "cross_folder_ratio": cross_ratio,
        "cross_folder_ratio_pct": cross_ratio_pct,
        "architecture_health_percentage": score,
    }


def run_benchmark(paths: List[str], json_output: bool = False) -> None:
    """Run benchmark across one or more repositories."""
    results: List[Dict[str, Any]] = []
    for raw_path in paths:
        root = Path(raw_path).resolve()
        scan = scan_repository(str(root))
        if not scan.get("valid", True):
            row = {
                "repo": root.name or str(root),
                "path": str(root),
                "error": scan.get("error", "Invalid repository"),
            }
            results.append(row)
            continue
        row = _extract_benchmark_row(scan)
        results.append(row)

    # Deterministic ordering by repo name, then path.
    results.sort(key=lambda r: (r.get("repo", ""), r.get("path", "")))

    if json_output:
        console.print(json.dumps(results, indent=2))
        return

    table = Table(
        show_header=True,
        header_style="bold white on blue",
        border_style="blue",
        box=ROUNDED,
        padding=(0, 2),
        expand=False,
        title="RepoMind Architecture Benchmark",
    )
    table.add_column("Repo", style="cyan bold")
    table.add_column("Files", justify="right")
    table.add_column("LongFiles", justify="right")
    table.add_column("Cycles", justify="right")
    table.add_column("CrossFolder%", justify="right")
    table.add_column("Score", justify="right")

    for row in results:
        if "error" in row:
            table.add_row(
                row.get("repo", ""),
                "-",
                "-",
                "-",
                "-",
                f"[red]{row['error']}[/red]",
            )
            continue

        table.add_row(
            row["repo"],
            str(row["total_files"]),
            str(row["long_file_count"]),
            str(row["cycle_count"]),
            f"{row['cross_folder_ratio_pct']:.1f}",
            str(row["architecture_health_percentage"]),
        )

    console.print(table)

