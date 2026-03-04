"""Builds structured context from scan data for downstream analysis."""

import json
from pathlib import Path

from repomind.scanners.repo_scanner import LONG_FILE_THRESHOLD

REPORT_DIR_NAME = "repomind_report"
SCAN_JSON_NAME = "scan.json"
PER_FILE_STATS = "per_file_stats"
DEPENDENCY_STATS = "dependency_stats"
IMPORT_MAP = "import_map"
IN_DEGREE = "in_degree"
CIRCULAR_DEPENDENCIES = "circular_dependencies"
FOLDER_COUPLING = "folder_coupling"
CROSS_FOLDER_DEPENDENCY_RATIO = "cross_folder_dependency_ratio"
TOP_LARGEST_COUNT = 3
HIGH_SHARE_THRESHOLD_PCT = 30.0  # for function share and dependency share
GROWTH_RISK_SHARE_PCT = 40.0  # function share or fan-in above this = growth risk indicator
DOMINATED_LINE_SHARE_PCT = 50.0  # one file has this share of lines = dominated (for Small+ projects)
GROWTH_RISK_INDICATOR_COUNT = 4
CONFIDENCE_PENALTY_SMALL_PROJECT = 25
CONFIDENCE_PENALTY_LOW_IMPORTS = 25
CONFIDENCE_PENALTY_TEST_ONLY = 25
CONFIDENCE_PENALTY_NO_CROSS_LARGE = 25

# Project size by source file count.
SIZE_MICRO = "Micro"   # <3 files
SIZE_SMALL = "Small"   # 3–10
SIZE_MEDIUM = "Medium" # 11–50
SIZE_LARGE = "Large"   # >50


def _project_size_class(file_count: int) -> str:
    """Return size classification from total source file count."""
    if file_count < 3:
        return SIZE_MICRO
    if file_count <= 10:
        return SIZE_SMALL
    if file_count <= 50:
        return SIZE_MEDIUM
    return SIZE_LARGE


def get_project_size_class(file_count: int) -> str:
    """Public helper: return size classification (Micro/Small/Medium/Large)."""
    return _project_size_class(file_count)


def compute_signal_confidence(data: dict) -> int:
    """Compute signal_confidence (0–100) from scan data. Same logic as in build_summary."""
    if not data.get("valid", True):
        return 0
    total_files = data.get("source_files", 0)
    dep = data.get(DEPENDENCY_STATS) or {}
    import_map = dep.get(IMPORT_MAP) or {}
    total_internal_imports = sum(len(d) for d in import_map.values()) if isinstance(import_map, dict) else 0
    folder_coupling = dep.get(FOLDER_COUPLING) or {}
    raw_ratio = dep.get(CROSS_FOLDER_DEPENDENCY_RATIO)
    cross_ratio = float(raw_ratio) if isinstance(raw_ratio, (int, float)) else 0.0
    confidence = 100
    if total_files < 5:
        confidence -= CONFIDENCE_PENALTY_SMALL_PROJECT
    if total_internal_imports < 5:
        confidence -= CONFIDENCE_PENALTY_LOW_IMPORTS
    if folder_coupling and isinstance(folder_coupling, dict):
        folder_names = [n.lower() for n in folder_coupling.keys()]
        if folder_names and all(n in {"tests", "test", "benchmark"} for n in folder_names):
            confidence -= CONFIDENCE_PENALTY_TEST_ONLY
    if total_files > 50 and cross_ratio == 0.0:
        confidence -= CONFIDENCE_PENALTY_NO_CROSS_LARGE
    return max(0, min(100, confidence))


def _top_largest_files(per_file_stats: dict) -> list[tuple[str, int]]:
    """Return top N (path, lines) by line count, tie-break by path for determinism."""
    items = [
        (path, stats.get("lines", 0))
        for path, stats in per_file_stats.items()
        if isinstance(stats, dict)
    ]
    items.sort(key=lambda x: (-x[1], x[0]))
    return items[:TOP_LARGEST_COUNT]


def _file_with_most(per_file_stats: dict, key: str) -> tuple[str, int] | None:
    """Return (path, value) for the file with max value at key; None if empty. Tie-break by path."""
    items = [
        (path, stats.get(key, 0))
        for path, stats in per_file_stats.items()
        if isinstance(stats, dict)
    ]
    if not items:
        return None
    items.sort(key=lambda x: (-x[1], x[0]))
    return items[0]


def _total_functions(per_file_stats: dict) -> int:
    """Sum function_count across all files. Deterministic (order does not affect sum)."""
    return sum(
        stats.get("function_count", 0)
        for stats in per_file_stats.values()
        if isinstance(stats, dict)
    )


def _most_depended_on(in_degree: dict[str, int]) -> tuple[str, int] | None:
    """Return (path, in_degree) for the file with highest in-degree; None if empty. Tie-break by path."""
    if not in_degree:
        return None
    items = [(path, count) for path, count in in_degree.items()]
    items.sort(key=lambda x: (-x[1], x[0]))
    return items[0]


def _total_internal_imports(in_degree: dict[str, int]) -> int:
    """Total number of internal import edges (sum of in-degrees)."""
    return sum(in_degree.values()) if in_degree else 0


def _bottleneck_files(
    per_file_stats: dict,
    in_degree: dict[str, int],
    total_functions: int,
    total_imports: int,
    threshold_pct: float,
) -> list[str]:
    """
    Return sorted list of file paths that have both function share and dependency share above threshold.
    """
    if total_functions <= 0 or total_imports <= 0:
        return []
    threshold = threshold_pct / 100.0
    bottlenecks: list[str] = []
    for path, stats in per_file_stats.items():
        if not isinstance(stats, dict):
            continue
        func_count = stats.get("function_count", 0)
        dep_count = in_degree.get(path, 0)
        func_share = func_count / total_functions
        dep_share = dep_count / total_imports
        if func_share >= threshold and dep_share >= threshold:
            bottlenecks.append(path)
    bottlenecks.sort()
    return bottlenecks


# Folders that trigger coupling risk downgrade (test/benchmark dominated).
_COUPLING_DOWNGRADE_FOLDERS = frozenset({"tests", "test", "benchmark"})


def compute_final_coupling_risk_level(dependency_stats: dict) -> str:
    """
    Return the authoritative coupling_risk_level ("low" | "moderate" | "high").
    Applies test/benchmark downgrade: if top most coupled folder is tests/test/benchmark,
    downgrade one level. Deterministic.
    """
    dep = dependency_stats or {}
    folder_coupling = dep.get(FOLDER_COUPLING) or {}
    raw_ratio = dep.get(CROSS_FOLDER_DEPENDENCY_RATIO)
    cross_ratio = float(raw_ratio) if isinstance(raw_ratio, (int, float)) else 0.0

    if cross_ratio > 0.4:
        base = "high"
    elif cross_ratio > 0.25:
        base = "moderate"
    else:
        base = "low"

    if not folder_coupling or not isinstance(folder_coupling, dict):
        return base

    items: list[tuple[str, int]] = []
    for folder, entry in folder_coupling.items():
        if isinstance(entry, dict):
            ext = int(entry.get("external_dependencies", 0))
            items.append((folder, ext))
    items.sort(key=lambda x: (-x[1], x[0]))

    if not items:
        return base
    top_folder = items[0][0].lower()
    if base == "high" and top_folder in _COUPLING_DOWNGRADE_FOLDERS:
        return "moderate"
    if base == "moderate" and top_folder in _COUPLING_DOWNGRADE_FOLDERS:
        return "low"
    return base


def compute_growth_risk_score(data: dict) -> int:
    """
    Compute growth_risk_score (0–4) from scan data.
    Same four indicators as in the summary: largest file >300 lines, function share >40%,
    fan-in share >40%, Small+ project dominated by one file.
    """
    if not data.get("valid", True):
        return 0
    per_file_stats = data.get(PER_FILE_STATS) or {}
    dependency_stats = data.get(DEPENDENCY_STATS) or {}
    in_degree = dependency_stats.get(IN_DEGREE) or {}
    total_files = data.get("source_files", 0)
    total_lines = data.get("total_lines", 0)
    total_functions = _total_functions(per_file_stats)
    total_imports = _total_internal_imports(in_degree)
    top_largest = _top_largest_files(per_file_stats)
    most_functions = _file_with_most(per_file_stats, "function_count")
    most_depended = _most_depended_on(in_degree)
    size_class = _project_size_class(total_files)

    single_file_over_300 = bool(top_largest and top_largest[0][1] > LONG_FILE_THRESHOLD)
    func_share_high = (
        total_functions > 0
        and most_functions
        and most_functions[1] > 0
        and 100.0 * most_functions[1] / total_functions > GROWTH_RISK_SHARE_PCT
    )
    fanin_high = (
        total_imports > 0
        and most_depended
        and most_depended[1] > 0
        and 100.0 * most_depended[1] / total_imports > GROWTH_RISK_SHARE_PCT
    )
    dominated_one_file = (
        size_class != SIZE_MICRO
        and total_lines > 0
        and top_largest
        and 100.0 * top_largest[0][1] / total_lines > DOMINATED_LINE_SHARE_PCT
    )
    return sum([single_file_over_300, func_share_high, fanin_high, dominated_one_file])


class ContextBuilder:
    """
    Loads scan data from repomind_report/scan.json and produces a
    deterministic textual summary suitable for an AI analyzer.
    """

    def __init__(self, root_path: str) -> None:
        self.root_path = Path(root_path).resolve()

    def load(self) -> dict:
        """Load scan data from repomind_report/scan.json. Raises FileNotFoundError if missing."""
        scan_path = self.root_path / REPORT_DIR_NAME / SCAN_JSON_NAME
        with open(scan_path, encoding="utf-8") as f:
            return json.load(f)

    def build_summary(self) -> str:
        """
        Load scan data and return a deterministic textual summary.
        Includes total files, total lines, todo/fixme counts, and number of long files.
        """
        try:
            data = self.load()
        except FileNotFoundError:
            return f"Scan data not found at {self.root_path / REPORT_DIR_NAME / SCAN_JSON_NAME}."
        except json.JSONDecodeError as e:
            return f"Invalid scan data: {e}."

        if not data.get("valid", True):
            return f"Invalid scan: {data.get('error', 'Unknown error')}."

        total_files = data.get("source_files", 0)
        total_lines = data.get("total_lines", 0)
        todo_count = data.get("todo_count", 0)
        fixme_count = data.get("fixme_count", 0)
        long_files = data.get("long_files", [])
        long_file_count = len(long_files)
        path = data.get("path", str(self.root_path))
        per_file_stats = data.get(PER_FILE_STATS) or {}
        dependency_stats = data.get(DEPENDENCY_STATS) or {}
        in_degree = dependency_stats.get(IN_DEGREE) or {}
        circular_dependencies = dependency_stats.get(CIRCULAR_DEPENDENCIES) or []
        total_functions = _total_functions(per_file_stats)
        total_imports = _total_internal_imports(in_degree)
        top_largest = _top_largest_files(per_file_stats)
        most_functions = _file_with_most(per_file_stats, "function_count")
        most_depended = _most_depended_on(in_degree)
        bottlenecks = _bottleneck_files(
            per_file_stats, in_degree, total_functions, total_imports, HIGH_SHARE_THRESHOLD_PCT
        )

        size_class = _project_size_class(total_files)

        # Confidence layer helpers.
        import_map = dependency_stats.get(IMPORT_MAP) or {}
        total_internal_imports = 0
        if isinstance(import_map, dict):
            for deps in import_map.values():
                if isinstance(deps, list):
                    total_internal_imports += len(deps)
        lines = [
            f"Repository: {path}",
            f"Project size: {size_class} ({total_files} source files)",
            f"Total files: {total_files}",
            f"Total lines: {total_lines}",
            f"Total functions: {total_functions}",
            f"TODO count: {todo_count}",
            f"FIXME count: {fixme_count}",
            f"Long files (>{LONG_FILE_THRESHOLD} lines): {long_file_count}",
        ]

        if total_lines > 0 and top_largest:
            pct_lines = round(100.0 * top_largest[0][1] / total_lines, 1)
            lines.append(f"Largest file share of total lines: {pct_lines}%")

        if total_functions > 0 and most_functions and most_functions[1] > 0:
            pct_funcs = round(100.0 * most_functions[1] / total_functions, 1)
            lines.append(f"Most function-heavy file share of total functions: {pct_funcs}%")

        if top_largest:
            lines.append("")
            lines.append("Top largest files:")
            for rel_path, line_count in top_largest:
                lines.append(f"  {rel_path}: {line_count} lines")

        if most_functions and most_functions[1] > 0:
            lines.append("")
            lines.append(f"Most functions: {most_functions[0]} ({most_functions[1]})")

        if most_depended and most_depended[1] > 0:
            pct_dep = round(100.0 * most_depended[1] / total_imports, 1) if total_imports > 0 else 0
            lines.append("")
            lines.append(
                f"Most depended-on file: {most_depended[0]} "
                f"(in-degree {most_depended[1]}, {pct_dep}% of internal imports)"
            )

        single_file_over_300 = bool(top_largest and top_largest[0][1] > LONG_FILE_THRESHOLD)
        func_share_high = (
            total_functions > 0
            and most_functions
            and most_functions[1] > 0
            and 100.0 * most_functions[1] / total_functions > GROWTH_RISK_SHARE_PCT
        )
        fanin_high = (
            total_imports > 0
            and most_depended
            and most_depended[1] > 0
            and 100.0 * most_depended[1] / total_imports > GROWTH_RISK_SHARE_PCT
        )
        dominated_one_file = (
            size_class != SIZE_MICRO
            and total_lines > 0
            and top_largest
            and 100.0 * top_largest[0][1] / total_lines > DOMINATED_LINE_SHARE_PCT
        )
        growth_risk_score = sum(
            [single_file_over_300, func_share_high, fanin_high, dominated_one_file]
        )
        lines.append("")
        lines.append(f"Growth risk indicators: {growth_risk_score}/{GROWTH_RISK_INDICATOR_COUNT} triggered")
        lines.append(f"  growth_risk_score: {growth_risk_score}")
        lines.append(f"  Largest file > {LONG_FILE_THRESHOLD} lines: {'Yes' if single_file_over_300 else 'No'}")
        lines.append(f"  Function share > {GROWTH_RISK_SHARE_PCT:.0f}%: {'Yes' if func_share_high else 'No'}")
        lines.append(f"  Dependency fan-in share > {GROWTH_RISK_SHARE_PCT:.0f}%: {'Yes' if fanin_high else 'No'}")
        lines.append(
            f"  Small+ project dominated by one file (>{DOMINATED_LINE_SHARE_PCT:.0f}% lines): "
            f"{'Yes' if dominated_one_file else 'No'}"
        )

        folder_coupling = dependency_stats.get(FOLDER_COUPLING) or {}
        cross_ratio_raw = dependency_stats.get(CROSS_FOLDER_DEPENDENCY_RATIO)
        cross_ratio = float(cross_ratio_raw) if isinstance(cross_ratio_raw, (int, float)) else 0.0
        cross_ratio_pct = 100.0 * cross_ratio

        # Compute signal confidence (0–100), deterministically.
        signal_confidence = 100
        if total_files < 5:
            signal_confidence -= CONFIDENCE_PENALTY_SMALL_PROJECT
        if total_internal_imports < 5:
            signal_confidence -= CONFIDENCE_PENALTY_LOW_IMPORTS
        # Only test/benchmark folders present in coupling data.
        if folder_coupling and isinstance(folder_coupling, dict):
            folder_names = [name.lower() for name in folder_coupling.keys()]
            if folder_names and all(
                n in {"tests", "test", "benchmark"} for n in folder_names
            ):
                signal_confidence -= CONFIDENCE_PENALTY_TEST_ONLY
        # Large project with no cross-folder deps may indicate incomplete signal.
        if total_files > 50 and cross_ratio == 0.0:
            signal_confidence -= CONFIDENCE_PENALTY_NO_CROSS_LARGE

        signal_confidence = max(0, min(100, signal_confidence))

        if folder_coupling and isinstance(folder_coupling, dict):
            coupling_risk_level = compute_final_coupling_risk_level(dependency_stats)
            base_from_ratio = "high" if cross_ratio > 0.4 else ("moderate" if cross_ratio > 0.25 else "low")
            downgraded = base_from_ratio != coupling_risk_level
            if coupling_risk_level == "high":
                coupling_label = "High coupling risk"
            elif coupling_risk_level == "moderate":
                coupling_label = "Moderate coupling"
            else:
                coupling_label = "Low coupling"
            if downgraded:
                coupling_label += " (dominated by tests/benchmarks)"

            items: list[tuple[str, int]] = []
            for folder, entry in folder_coupling.items():
                if isinstance(entry, dict):
                    ext = int(entry.get("external_dependencies", 0))
                    items.append((folder, ext))
            items.sort(key=lambda x: (-x[1], x[0]))

            lines.append("")
            lines.append("Folder-level coupling:")
            lines.append(f"- Cross-folder dependency ratio: {cross_ratio_pct:.1f}% ({coupling_label})")
            if items:
                top_folder, top_ext = items[0]
                lines.append(f"- Top most coupled folder: {top_folder} ({top_ext} external folders)")
                top_three = items[:3]
                lines.append("- Most externally dependent folders:")
                for folder, ext in top_three:
                    lines.append(f"  - {folder}: {ext} external folders")
            if downgraded and items:
                lines.append(
                    "High coupling driven primarily by test modules; production architecture impact likely limited."
                )
            lines.append(f"coupling_risk_level: {coupling_risk_level}")

        lines.append("")
        lines.append(f"Signal confidence: {signal_confidence}%")
        if signal_confidence < 50:
            lines.append("Architecture signal weak due to insufficient structural data.")

        if bottlenecks:
            lines.append("")
            lines.append("Potential architectural bottleneck(s) (high function share and high dependency share):")
            for p in bottlenecks:
                lines.append(f"  {p}")

        lines.append("")
        if circular_dependencies:
            lines.append("Circular dependencies detected:")
            for cycle in circular_dependencies:
                if isinstance(cycle, list) and cycle:
                    lines.append("  " + " -> ".join(str(f) for f in cycle))
        else:
            lines.append("No circular dependencies detected.")

        most_classes = _file_with_most(per_file_stats, "class_count")
        if most_classes and most_classes[1] > 0:
            lines.append("")
            lines.append(f"Most classes: {most_classes[0]} ({most_classes[1]})")

        return "\n".join(lines)
