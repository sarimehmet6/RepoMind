"""Orchestrates RepoMind audit workflows."""

import json
from pathlib import Path

from rich.box import ROUNDED
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from repomind.context_builder import (
    ContextBuilder,
    compute_final_coupling_risk_level,
    compute_growth_risk_score,
    compute_signal_confidence,
    get_project_size_class,
)
from repomind.scanners.repo_scanner import LONG_FILE_THRESHOLD, scan_repository

REPORT_DIR_NAME = "repomind_report"
SCAN_JSON_NAME = "scan.json"
MARKDOWN_REPORT_NAME = "repomind_report.md"

console = Console()


def _save_scan_result(path: str, result: dict) -> None:
    """Create repomind_report in the project root and write result as scan.json."""
    root = Path(path).resolve()
    report_dir = root / REPORT_DIR_NAME
    report_dir.mkdir(parents=True, exist_ok=True)
    scan_path = report_dir / SCAN_JSON_NAME
    with open(scan_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)


def _build_markdown_report(result: dict) -> str:
    """Build deterministic GitHub-friendly markdown report. No AI. Uses architecture_score only."""
    dep_stats = result.get("dependency_stats") or {}
    ratio_raw = dep_stats.get("cross_folder_dependency_ratio") or 0
    ratio_pct = 100.0 * (float(ratio_raw) if isinstance(ratio_raw, (int, float)) else 0)
    coupling_risk_level = compute_final_coupling_risk_level(dep_stats)
    growth_risk_score = compute_growth_risk_score(result)
    arch = result.get("architecture_score") or {}
    total_files = result.get("source_files", 0)
    total_lines = result.get("total_lines", 0)
    project_size = get_project_size_class(total_files)
    signal_conf = compute_signal_confidence(result)
    long_files = result.get("long_files", [])
    folder_coupling = dep_stats.get("folder_coupling") or {}

    lines = [
        "# RepoMind Architecture Report",
        "",
        "## Summary",
        f"- **Project size:** {project_size} ({total_files} source files)",
        f"- **Total lines:** {total_lines}",
        f"- **Total files:** {total_files}",
        f"- **Signal confidence:** {signal_conf}%",
        f"- **Architecture score (deterministic):** {arch.get('normalized_score', 'N/A')}",
        "",
        "## Growth Risks",
        f"- **Growth risk indicators:** {growth_risk_score}/4 triggered",
    ]
    if long_files:
        lines.append("- **Long files (>300 lines):**")
        for e in sorted(long_files, key=lambda x: (-x["lines"], x["path"]))[:15]:
            lines.append(f"  - `{e['path']}` ({e['lines']} lines)")
    else:
        lines.append("- **Long files:** None")
    lines.append("")
    lines.append("## Coupling Analysis")
    lines.append(f"- **Cross-folder dependency ratio:** {ratio_pct:.1f}%")
    lines.append(f"- **Coupling risk level:** {coupling_risk_level}")
    if folder_coupling and isinstance(folder_coupling, dict):
        items = []
        for folder, entry in folder_coupling.items():
            if isinstance(entry, dict):
                items.append((folder, int(entry.get("external_dependencies", 0))))
        items.sort(key=lambda x: (-x[1], x[0]))
        lines.append("- **Top coupled folders:**")
        for folder, ext in items[:10]:
            lines.append(f"  - `{folder}`: {ext} external folders")
    lines.append("")
    lines.append("## Key Issues")
    lines.append("- None reported.")
    lines.append("")
    return "\n".join(lines)


def run_audit(path: str, markdown_report: bool = False) -> None:
    """Run an audit on the repository at the given path."""
    console.print()
    console.print(Rule("[bold]RepoMind Structural Scan[/bold]", style="bold blue"))
    console.print(Text(path, style="dim"))
    console.print()

    result = scan_repository(path)
    _save_scan_result(path, result)

    context = ContextBuilder(path)
    summary = context.build_summary()

    table = Table(
        show_header=True,
        header_style="bold white on blue",
        border_style="blue",
        box=ROUNDED,
        padding=(0, 2),
        expand=False,
    )
    table.add_column("Metric", style="cyan bold", min_width=22)
    table.add_column("Value", style="green")

    if not result.get("valid", True):
        table.add_row("Status", "[red]Invalid[/red]")
        table.add_row("Error", result.get("error", "Unknown"))
    else:
        table.add_row("Path", result["path"])
        table.add_row("Source files (.py)", str(result["source_files"]))
        table.add_row("Total lines", str(result["total_lines"]))
        structural_class = result.get("structural_class")
        if structural_class:
            table.add_row("Structural class", structural_class)
        table.add_row("TODO", str(result["todo_count"]))
        table.add_row("FIXME", str(result["fixme_count"]))
        long_files = result.get("long_files", [])
        if long_files:
            long_list = ", ".join(f"{e['path']} ({e['lines']})" for e in long_files[:10])
            if len(long_files) > 10:
                long_list += f" [dim]… +{len(long_files) - 10} more[/dim]"
            table.add_row(f"Files > {LONG_FILE_THRESHOLD} lines", long_list)

    console.print(Panel(table, border_style="blue", padding=(0, 0)))
    console.print()
    console.print(Panel(summary, title="Repository summary", border_style="blue", padding=(1, 2)))
    console.print()

    arch = result.get("architecture_score") or {}
    raw_score = arch.get("raw_score", 0)
    normalized_score = arch.get("normalized_score", 0)
    breakdown = arch.get("risk_breakdown") or {}
    score_lines = [
        f"Raw score: {raw_score}",
        f"Normalized score: {normalized_score}",
        "",
        "Breakdown:",
        f"  Long file penalty: {breakdown.get('long_file_penalty', 0)}",
        f"  Circular dependency penalty: {breakdown.get('circular_dependency_penalty', 0)}",
        f"  Centralization penalty: {breakdown.get('centralization_penalty', 0)}",
        f"  Cross-folder penalty: {breakdown.get('cross_folder_penalty', 0)}",
    ]
    console.print(Rule("Deterministic Architecture Score", style="bold blue"))
    console.print("\n".join(score_lines))
    console.print(Rule(style="dim"))

    if markdown_report:
        report_dir = Path(path).resolve() / REPORT_DIR_NAME
        report_dir.mkdir(parents=True, exist_ok=True)
        md_path = report_dir / MARKDOWN_REPORT_NAME
        md_content = _build_markdown_report(result)
        md_path.write_text(md_content, encoding="utf-8")
        console.print(f"[dim]Markdown report written to {md_path}[/dim]")
    console.print()
