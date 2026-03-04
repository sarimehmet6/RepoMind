"""External benchmarking harness for RepoMind.

Modes:
1) Clone + audit: set REPO_URLS, run script → clones into ./benchmarks/, runs audit, appends to results.csv.
2) Local only: run with --local → uses LOCAL_REPO_NAMES under REPOS_BASE; runs audit on existing dirs, writes results.

Local repos: put requests, flask, fastapi, ... under one folder (e.g. benchmarks/) and run:
  python benchmark_repos.py --local
  REPOMIND_REPOS_BASE=/path/to/parent python benchmark_repos.py --local

RepoMind internals are not modified; this is a standalone harness.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List


# GitHub URLs for clone mode (optional).
REPO_URLS: List[str] = []

# Local repo names (directories under REPOS_BASE). Used when running with --local.
LOCAL_REPO_NAMES: List[str] = [
    "requests",
    "flask",
    "fastapi",
    "click",
    "celery",
    "django",
    "pydantic",
    "sqlalchemy",
    "numpy",
    "pandas",
]

# Base directory for local repos (e.g. benchmarks/requests or /home/mehmetsari/requests).
# Override with env REPOMIND_REPOS_BASE or --repos-base.
REPOS_BASE = Path(os.environ.get("REPOMIND_REPOS_BASE", "benchmarks"))

BENCHMARK_ROOT = Path("benchmarks")
RESULTS_CSV = BENCHMARK_ROOT / "results.csv"
SUMMARY_JSON = BENCHMARK_ROOT / "summary.json"
REPORT_DIR_NAME = "repomind_report"
SCAN_JSON_NAME = "scan.json"


def _run_command(args: List[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Run a subprocess command safely, returning the CompletedProcess."""
    return subprocess.run(
        args,
        cwd=str(cwd) if cwd is not None else None,
        check=False,
        capture_output=True,
        text=True,
    )


def _clone_repo(url: str, dest_dir: Path) -> None:
    """Clone the repo into dest_dir if not already present."""
    if dest_dir.is_dir():
        print(f"[skip] Repo already cloned: {dest_dir}")
        return
    dest_dir.parent.mkdir(parents=True, exist_ok=True)
    print(f"[clone] {url} -> {dest_dir}")
    result = _run_command(["git", "clone", url, str(dest_dir)])
    if result.returncode != 0:
        print(f"[error] git clone failed for {url}: {result.stderr.strip()}")


def _run_repomind_audit(repo_path: Path, markdown_report: bool = False) -> None:
    """Run `repomind audit` on the given repo path."""
    print(f"[audit] Running RepoMind on {repo_path}")
    args = ["repomind", "audit", str(repo_path)]
    if markdown_report:
        args.append("--markdown-report")
    result = _run_command(args)
    if result.returncode != 0:
        print(f"[error] repomind audit failed for {repo_path}: {result.stderr.strip()}")


def _load_scan_json(repo_path: Path) -> Dict[str, Any] | None:
    """Load scan.json from a repo, returning None on failure."""
    scan_path = repo_path / REPORT_DIR_NAME / SCAN_JSON_NAME
    if not scan_path.is_file():
        print(f"[warn] scan.json not found for {repo_path}")
        return None
    try:
        with scan_path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[error] Failed to read scan.json for {repo_path}: {exc}")
        return None


def _extract_metrics(scan: Dict[str, Any]) -> Dict[str, Any]:
    """Extract benchmark metrics from a scan.json dict."""
    total_files = scan.get("total_files", scan.get("source_files", 0))
    total_lines = scan.get("total_lines", 0)

    arch = scan.get("architecture_score") or {}
    health = arch.get("architecture_health_percentage", arch.get("normalized_score", 0))
    raw_score = arch.get("raw_score", 0)
    breakdown = arch.get("risk_breakdown") or {}

    long_penalty = breakdown.get("long_file_penalty", 0)
    cycle_penalty = breakdown.get("circular_dependency_penalty", 0)
    central_penalty = breakdown.get("centralization_penalty", 0)
    folder_penalty = breakdown.get("cross_folder_penalty", 0)

    structural = arch.get("structural_profile") or {}
    long_ratio = structural.get("long_file_ratio", "")
    cycle_ratio = structural.get("cycle_ratio", "")

    return {
        "total_files": total_files,
        "total_lines": total_lines,
        "architecture_health_percentage": health,
        "raw_score": raw_score,
        "long_file_penalty": long_penalty,
        "circular_dependency_penalty": cycle_penalty,
        "centralization_penalty": central_penalty,
        "cross_folder_penalty": folder_penalty,
        "long_file_ratio": long_ratio,
        "cycle_ratio": cycle_ratio,
    }


CSV_FIELDNAMES = [
    "repo",
    "url",
    "total_files",
    "total_lines",
    "architecture_health_percentage",
    "raw_score",
    "long_file_penalty",
    "circular_dependency_penalty",
    "centralization_penalty",
    "cross_folder_penalty",
    "long_file_ratio",
    "cycle_ratio",
]


def _write_results_csv(rows: List[Dict[str, Any]], append: bool = False) -> None:
    """Write rows to benchmarks/results.csv. append=True: add to file; else overwrite."""
    if not rows:
        return
    BENCHMARK_ROOT.mkdir(parents=True, exist_ok=True)
    file_exists = RESULTS_CSV.is_file()
    with RESULTS_CSV.open("a" if append and file_exists else "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
        if not (append and file_exists):
            writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in CSV_FIELDNAMES})
    print(f"[ok] Results written to {RESULTS_CSV}")


def _append_results_csv(rows: List[Dict[str, Any]]) -> None:
    """Append rows to benchmarks/results.csv, creating it with header if needed."""
    _write_results_csv(rows, append=True)


def run_local(repos_base: Path | None = None, markdown_report: bool = True) -> None:
    """Run RepoMind on already-downloaded local repos. Writes results.csv and summary.json."""
    base = repos_base or REPOS_BASE
    names = sorted(LOCAL_REPO_NAMES)
    all_rows: List[Dict[str, Any]] = []
    summary: List[Dict[str, Any]] = []

    for repo_name in names:
        repo_path = base / repo_name
        if not repo_path.is_dir():
            print(f"[skip] Not a directory: {repo_path}")
            continue

        print(f"\n=== {repo_name} ===")
        _run_repomind_audit(repo_path, markdown_report=markdown_report)
        scan = _load_scan_json(repo_path)
        if scan is None:
            print(f"[skip] No scan data for {repo_name}.")
            continue
        metrics = _extract_metrics(scan)
        row = {
            "repo": repo_name,
            "url": "",
            **metrics,
        }
        all_rows.append(row)
        summary.append({"repo": repo_name, "path": str(repo_path), **metrics})
        print(
            f"[ok] {repo_name}: files={metrics['total_files']}, "
            f"lines={metrics['total_lines']}, "
            f"health={metrics['architecture_health_percentage']}"
        )

    if not all_rows:
        print("\nNo results. Ensure repo directories exist under:", base.resolve())
        return

    BENCHMARK_ROOT.mkdir(parents=True, exist_ok=True)
    _write_results_csv(all_rows, append=False)
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"[ok] Summary written to {SUMMARY_JSON}")
    print(f"\nDone. {len(all_rows)} repos. Results: {RESULTS_CSV}, summary: {SUMMARY_JSON}")


def main() -> None:
    """Entry point: --local = run on local repos under REPOS_BASE; else clone from REPO_URLS."""
    parser = argparse.ArgumentParser(description="Run RepoMind on repos and collect results.")
    parser.add_argument(
        "--local",
        action="store_true",
        help="Use local repo names under REPOS_BASE (no clone).",
    )
    parser.add_argument(
        "--repos-base",
        type=Path,
        default=None,
        help="Base directory for local repos (default: benchmarks or REPOMIND_REPOS_BASE).",
    )
    parser.add_argument(
        "--no-markdown",
        action="store_true",
        help="Do not generate markdown report per repo (only for --local).",
    )
    args = parser.parse_args()

    if args.local:
        run_local(repos_base=args.repos_base, markdown_report=not args.no_markdown)
        return

    if not REPO_URLS:
        print(
            "No REPO_URLS configured. Use --local to run on existing dirs under REPOS_BASE, "
            f"e.g. {REPOS_BASE}/requests, {REPOS_BASE}/flask, ..."
        )
        return

    urls = sorted(REPO_URLS)
    all_rows: List[Dict[str, Any]] = []

    for url in urls:
        repo_name = url.rstrip("/").split("/")[-1]
        if repo_name.endswith(".git"):
            repo_name = repo_name[:-4]
        dest_dir = BENCHMARK_ROOT / repo_name

        print(f"\n=== Benchmarking {repo_name} ===")
        _clone_repo(url, dest_dir)
        _run_repomind_audit(dest_dir, markdown_report=True)
        scan = _load_scan_json(dest_dir)
        if scan is None:
            print(f"[skip] No scan data for {repo_name}, skipping metrics.")
            continue
        metrics = _extract_metrics(scan)
        row = {"repo": repo_name, "url": url, **metrics}
        all_rows.append(row)
        print(
            f"[ok] {repo_name}: files={metrics['total_files']}, "
            f"lines={metrics['total_lines']}, "
            f"health={metrics['architecture_health_percentage']}"
        )

    _append_results_csv(all_rows)
    print(f"\nBenchmark complete. Results appended to {RESULTS_CSV}")


if __name__ == "__main__":
    main()

