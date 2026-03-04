"""Structural classification for repositories.

This module is intentionally pure and independent from scanners/scoring.
It classifies a repository into coarse structural classes based on size
and simple heuristics so that scoring can be context-aware.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

# Size bands for classification (can be tuned, but must remain constants).
SMALL_MAX_FILES = 50
MID_MAX_FILES = 300

SMALL_MAX_LINES = 50_000
MID_MAX_LINES = 200_000

# Minimum average lines per file to consider a dense \"core\" codebase.
CORE_ENGINE_MIN_AVG_LINES = 250.0

STRUCTURAL_CLASS_SMALL = "small_project"
STRUCTURAL_CLASS_MID = "mid_project"
STRUCTURAL_CLASS_LARGE = "large_framework"
STRUCTURAL_CLASS_CORE = "core_engine"


def _get_size(scan_data: Dict[str, Any]) -> Tuple[int, int]:
    """Return (total_files, total_lines) from scan_data in a robust way."""
    per_file_stats = scan_data.get("per_file_stats") or {}
    total_files = scan_data.get("total_files")
    if not isinstance(total_files, int):
        total_files = len(per_file_stats)
    total_lines = scan_data.get("total_lines", 0)
    return int(total_files), int(total_lines)


def classify_repo(scan_data: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """Classify repository into a structural class and return (class, meta).

    Current heuristic (v1):
    - small_project:    very small file + line count
    - mid_project:      medium band
    - large_framework:  large codebase by size
    - core_engine:      large + high average LOC per file (dense core)
    """
    total_files, total_lines = _get_size(scan_data)
    avg_lines = float(total_lines) / float(total_files) if total_files > 0 else 0.0

    if total_files <= SMALL_MAX_FILES and total_lines <= SMALL_MAX_LINES:
        base_class = STRUCTURAL_CLASS_SMALL
        rule = "size_small"
    elif total_files <= MID_MAX_FILES and total_lines <= MID_MAX_LINES:
        base_class = STRUCTURAL_CLASS_MID
        rule = "size_mid"
    else:
        base_class = STRUCTURAL_CLASS_LARGE
        rule = "size_large"

    structural_class = base_class
    # Promote to core_engine if it is both large and dense.
    if base_class == STRUCTURAL_CLASS_LARGE and avg_lines >= CORE_ENGINE_MIN_AVG_LINES:
        structural_class = STRUCTURAL_CLASS_CORE
        rule = "core_engine_dense_large"

    meta: Dict[str, Any] = {
        "total_files": total_files,
        "total_lines": total_lines,
        "average_lines_per_file": avg_lines,
        "base_class": base_class,
        "rule": rule,
        "thresholds": {
            "SMALL_MAX_FILES": SMALL_MAX_FILES,
            "MID_MAX_FILES": MID_MAX_FILES,
            "SMALL_MAX_LINES": SMALL_MAX_LINES,
            "MID_MAX_LINES": MID_MAX_LINES,
            "CORE_ENGINE_MIN_AVG_LINES": CORE_ENGINE_MIN_AVG_LINES,
        },
    }
    return structural_class, meta

