"""
Deterministic Architecture Risk Engine.
No randomness. No AI. All thresholds and weights defined as constants.
"""

import math

from repomind.classification.structural_class import (
    STRUCTURAL_CLASS_CORE,
    STRUCTURAL_CLASS_LARGE,
    STRUCTURAL_CLASS_MID,
    STRUCTURAL_CLASS_SMALL,
    classify_repo,
)

# =============================
# Threshold Constants
# =============================

LONG_FILE_THRESHOLD_LOW = 500
LONG_FILE_THRESHOLD_HIGH = 800

LONG_FILE_PENALTY_LOW = 2
LONG_FILE_PENALTY_HIGH = 5

CYCLE_PENALTY_2_NODE = 10
CYCLE_PENALTY_3_TO_5 = 5
CYCLE_PENALTY_GT_5 = 15

CENTRALIZATION_THRESHOLD_RATIO = 0.05
CENTRALIZATION_PENALTY = 10

CROSS_FOLDER_THRESHOLD_LOW = 0.2
CROSS_FOLDER_THRESHOLD_HIGH = 0.4
CROSS_FOLDER_PENALTY_LOW = 10
CROSS_FOLDER_PENALTY_HIGH = 20

MAX_SCORE = 100
HEALTH_SCORE_FLOOR = 15

# Scoring version for traceability.
SCORING_VERSION = "2.0"

# Default profile name: immutable reference metric. Override = conscious deviation.
DEFAULT_SCORING_PROFILE = "v2_default"

# Context-aware baseline: per-structural-class penalty scales and floors.
STRUCTURAL_CLASS_PENALTY_SCALE = {
    STRUCTURAL_CLASS_SMALL: 1.0,
    STRUCTURAL_CLASS_MID: 1.0,
    STRUCTURAL_CLASS_LARGE: 0.7,
    STRUCTURAL_CLASS_CORE: 0.6,
}

STRUCTURAL_CLASS_HEALTH_FLOOR = {
    STRUCTURAL_CLASS_SMALL: 20,
    STRUCTURAL_CLASS_MID: 20,
    STRUCTURAL_CLASS_LARGE: 25,
    STRUCTURAL_CLASS_CORE: 30,
}


def _cycle_node_count(cycle: list) -> int:
    """Effective node count: if cycle closes (first == last), exclude duplicate."""
    if not cycle:
        return 0
    if len(cycle) >= 2 and cycle[0] == cycle[-1]:
        return len(cycle) - 1
    return len(cycle)


def compute_long_file_penalty(
    scan_data: dict,
    threshold_low: int = LONG_FILE_THRESHOLD_LOW,
    threshold_high: int = LONG_FILE_THRESHOLD_HIGH,
    penalty_low: int = LONG_FILE_PENALTY_LOW,
    penalty_high: int = LONG_FILE_PENALTY_HIGH,
) -> int:
    """
    Use per_file_stats to evaluate each file's line count.
    Apply LONG_FILE_PENALTY_LOW for 300 < lines <= 800, LONG_FILE_PENALTY_HIGH for lines > 800.
    Sum all penalties. Deterministic: iterate over sorted file keys.
    """
    if not scan_data.get("valid", True):
        return 0
    per_file_stats = scan_data.get("per_file_stats") or {}
    total = 0
    for path in sorted(per_file_stats.keys()):
        stats = per_file_stats.get(path)
        if not isinstance(stats, dict):
            continue
        lines = stats.get("lines", 0)
        if lines > threshold_high:
            total += penalty_high
        elif threshold_low < lines <= threshold_high:
            total += penalty_low
    return total


def compute_circular_dependency_penalty(
    scan_data: dict,
    base_penalty_2_node: int = CYCLE_PENALTY_2_NODE,
) -> int:
    """
    Use dependency_stats["circular_dependencies"]. Evaluate size of each cycle.
    Apply penalty: 2 nodes → CYCLE_PENALTY_2_NODE, 3-5 → CYCLE_PENALTY_3_TO_5, >5 → CYCLE_PENALTY_GT_5.
    Deterministic: sort cycles before processing.
    """
    if not scan_data.get("valid", True):
        return 0
    dependency_stats = scan_data.get("dependency_stats") or {}
    cycles = dependency_stats.get("circular_dependencies") or []
    if not isinstance(cycles, list):
        return 0
    # Deterministic: sort by tuple of cycle (canonical order).
    sorted_cycles = sorted(
        (c for c in cycles if isinstance(c, list)),
        key=lambda c: tuple(c),
    )
    total = 0
    for cycle in sorted_cycles:
        n = _cycle_node_count(cycle)
        if n <= 1:
            continue
        # Log-scale penalty based on cycle size (log2), anchored at 2-node base.
        # This keeps penalties sub-linear as cycles grow.
        factor = math.log(n, 2) if n > 1 else 1.0
        penalty = int(round(base_penalty_2_node * factor))
        total += penalty
    return total


def compute_centralization_penalty(
    scan_data: dict,
    threshold_ratio: float = CENTRALIZATION_THRESHOLD_RATIO,
    penalty: int = CENTRALIZATION_PENALTY,
) -> int:
    """
    Use dependency_stats["in_degree"]. total_files = len(per_file_stats).
    threshold = total_files * CENTRALIZATION_THRESHOLD_RATIO.
    If any file exceeds threshold → apply CENTRALIZATION_PENALTY once.
    """
    if not scan_data.get("valid", True):
        return 0
    per_file_stats = scan_data.get("per_file_stats") or {}
    total_files = len(per_file_stats)
    if total_files == 0:
        return 0
    dependency_stats = scan_data.get("dependency_stats") or {}
    in_degree = dependency_stats.get("in_degree") or {}
    threshold = total_files * threshold_ratio
    for path in sorted(in_degree.keys()):
        if in_degree.get(path, 0) > threshold:
            return penalty
    return 0


def compute_cross_folder_penalty(
    scan_data: dict,
    threshold_low: float = CROSS_FOLDER_THRESHOLD_LOW,
    threshold_high: float = CROSS_FOLDER_THRESHOLD_HIGH,
    penalty_low: int = CROSS_FOLDER_PENALTY_LOW,
    penalty_high: int = CROSS_FOLDER_PENALTY_HIGH,
) -> int:
    """
    Use dependency_stats["cross_folder_dependency_ratio"].
    Apply only highest applicable threshold. Not cumulative.
    """
    if not scan_data.get("valid", True):
        return 0
    dependency_stats = scan_data.get("dependency_stats") or {}
    ratio_raw = dependency_stats.get("cross_folder_dependency_ratio")
    ratio = float(ratio_raw) if isinstance(ratio_raw, (int, float)) else 0.0
    if ratio > threshold_high:
        return penalty_high
    if ratio > threshold_low:
        return penalty_low
    return 0


def count_long_files(
    scan_data: dict,
    threshold_low: int = LONG_FILE_THRESHOLD_LOW,
) -> int:
    """Return count of files with lines > threshold_low. Deterministic order."""
    if not scan_data.get("valid", True):
        return 0
    per_file_stats = scan_data.get("per_file_stats") or {}
    count = 0
    for path in sorted(per_file_stats.keys()):
        stats = per_file_stats.get(path)
        if not isinstance(stats, dict):
            continue
        lines = stats.get("lines", 0)
        if lines > threshold_low:
            count += 1
    return count


def count_cycles(scan_data: dict) -> int:
    """Return number of circular dependency cycles."""
    if not scan_data.get("valid", True):
        return 0
    dependency_stats = scan_data.get("dependency_stats") or {}
    cycles = dependency_stats.get("circular_dependencies") or []
    if not isinstance(cycles, list):
        return 0
    return len(cycles)


def compute_architecture_score(scan_data: dict, scoring_config: dict | None = None) -> dict:
    """
    Deterministic architecture scoring. No randomness. No hidden heuristics.
    All weights from module constants. Fully explainable risk breakdown.
    """
    if not scan_data.get("valid", True):
        return {
            "raw_score": 0,
            "normalized_score": 0,
            "architecture_health_percentage": 0,
            "scoring_mode": "default",
            "scoring_profile": DEFAULT_SCORING_PROFILE,
            "risk_breakdown": {
                "long_file_penalty": 0,
                "circular_dependency_penalty": 0,
                "centralization_penalty": 0,
                "cross_folder_penalty": 0,
            },
        }

    scoring_config = scoring_config or {}
    # Explicit identity: default = reference metric; custom = conscious override.
    is_custom = bool(scoring_config)
    scoring_mode = "custom" if is_custom else "default"
    scoring_profile = (
        (scoring_config.get("scoring_profile") or "custom")
        if is_custom
        else DEFAULT_SCORING_PROFILE
    )

    # Effective thresholds/weights (can be overridden via scoring_config).
    lf_low = int(scoring_config.get("long_file_threshold_low", LONG_FILE_THRESHOLD_LOW))
    lf_high = int(scoring_config.get("long_file_threshold_high", LONG_FILE_THRESHOLD_HIGH))
    lf_pen_low = int(scoring_config.get("long_file_penalty_low", LONG_FILE_PENALTY_LOW))
    lf_pen_high = int(scoring_config.get("long_file_penalty_high", LONG_FILE_PENALTY_HIGH))

    base_cycle_penalty = int(
        scoring_config.get("cycle_penalty_2_node", CYCLE_PENALTY_2_NODE)
    )

    central_ratio = float(
        scoring_config.get(
            "centralization_threshold_ratio", CENTRALIZATION_THRESHOLD_RATIO
        )
    )
    central_penalty_value = int(
        scoring_config.get("centralization_penalty", CENTRALIZATION_PENALTY)
    )

    cf_low = float(
        scoring_config.get("cross_folder_threshold_low", CROSS_FOLDER_THRESHOLD_LOW)
    )
    cf_high = float(
        scoring_config.get("cross_folder_threshold_high", CROSS_FOLDER_THRESHOLD_HIGH)
    )
    cf_pen_low = int(
        scoring_config.get("cross_folder_penalty_low", CROSS_FOLDER_PENALTY_LOW)
    )
    cf_pen_high = int(
        scoring_config.get("cross_folder_penalty_high", CROSS_FOLDER_PENALTY_HIGH)
    )

    class_scale_overrides = scoring_config.get("structural_class_penalty_scale") or {}
    class_floor_overrides = scoring_config.get("structural_class_health_floor") or {}

    # Base penalties (unscaled, for breakdown and raw_score).
    long_penalty = compute_long_file_penalty(
        scan_data,
        threshold_low=lf_low,
        threshold_high=lf_high,
        penalty_low=lf_pen_low,
        penalty_high=lf_pen_high,
    )
    cycle_penalty = compute_circular_dependency_penalty(
        scan_data,
        base_penalty_2_node=base_cycle_penalty,
    )
    central_penalty = compute_centralization_penalty(
        scan_data,
        threshold_ratio=central_ratio,
        penalty=central_penalty_value,
    )
    folder_penalty = compute_cross_folder_penalty(
        scan_data,
        threshold_low=cf_low,
        threshold_high=cf_high,
        penalty_low=cf_pen_low,
        penalty_high=cf_pen_high,
    )

    raw_score = long_penalty + cycle_penalty + central_penalty + folder_penalty

    # Size-aware scaling relative to total file count.
    per_file_stats = scan_data.get("per_file_stats") or {}
    total_files = len(per_file_stats)
    long_count = count_long_files(scan_data, threshold_low=lf_low)
    cycle_count = count_cycles(scan_data)

    # Cross-folder ratio reused for structural profile.
    dependency_stats = scan_data.get("dependency_stats") or {}
    ratio_raw = dependency_stats.get("cross_folder_dependency_ratio")
    cross_ratio = float(ratio_raw) if isinstance(ratio_raw, (int, float)) else 0.0

    # Centralization raw score: max in_degree share across files (0–1).
    in_degree = dependency_stats.get("in_degree") or {}
    max_in = max(in_degree.values(), default=0)

    if total_files > 0:
        scaled_long = float(long_penalty) * (long_count / total_files)
        scaled_cycles = float(cycle_penalty) * (cycle_count / total_files)
        centralization_score = float(max_in) / float(total_files)
        long_file_ratio = float(long_count) / float(total_files)
        cycle_ratio = float(cycle_count) / float(total_files)
    else:
        scaled_long = 0.0
        scaled_cycles = 0.0
        centralization_score = 0.0
        long_file_ratio = 0.0
        cycle_ratio = 0.0

    # Determine structural class (use existing annotation if present, else classify).
    structural_class = scan_data.get("structural_class")
    if not structural_class:
        structural_class, _ = classify_repo(scan_data)
    penalty_scale = float(
        (class_scale_overrides.get(structural_class)
         if isinstance(class_scale_overrides, dict)
         else None)
        or STRUCTURAL_CLASS_PENALTY_SCALE.get(structural_class, 1.0)
    )
    class_floor = int(
        (class_floor_overrides.get(structural_class)
         if isinstance(class_floor_overrides, dict)
         else None)
        or STRUCTURAL_CLASS_HEALTH_FLOOR.get(structural_class, HEALTH_SCORE_FLOOR)
    )

    # Apply context-aware penalty scaling for size/shape-dependent parts.
    scaled_penalties = (
        penalty_scale * (scaled_long + scaled_cycles)
        + float(central_penalty)
        + float(folder_penalty)
    )

    # Final score: score = max(0, 100 - scaled_penalties), then apply floor.
    score = max(0.0, float(MAX_SCORE) - scaled_penalties)
    architecture_health_percentage = max(
        class_floor, min(MAX_SCORE, int(round(score)))
    )

    # Structural profile (rounded deterministic floats).
    structural_profile = {
        "long_file_ratio": round(long_file_ratio, 4),
        "cycle_ratio": round(cycle_ratio, 4),
        "centralization_score": round(centralization_score, 4),
        "cross_folder_ratio": round(cross_ratio, 4),
    }

    return {
        "raw_score": raw_score,
        "normalized_score": architecture_health_percentage,
        "architecture_health_percentage": architecture_health_percentage,
        "scoring_version": SCORING_VERSION,
        "scoring_mode": scoring_mode,
        "scoring_profile": scoring_profile,
        "risk_breakdown": {
            "long_file_penalty": long_penalty,
            "circular_dependency_penalty": cycle_penalty,
            "centralization_penalty": central_penalty,
            "cross_folder_penalty": folder_penalty,
        },
        "structural_profile": structural_profile,
    }
