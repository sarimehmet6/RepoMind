# RepoMind – Deterministic Architecture Scoring Engine (Research Phase)

RepoMind scans a codebase and produces a deterministic architecture health score plus a structured report. It detects layer violations, long files, circular dependencies, centralization, and cross-folder coupling. The scoring model is versioned and under active calibration; this project is **not production-ready** and is intended for research and internal evaluation.

**Important:** The scoring model is versioned (e.g. `scoring_version: "2.0"`). Scores may change between versions as thresholds and formulas evolve. This project is in active calibration and benchmark development. Do not rely on scores for critical decisions without tracking which scoring version produced them.

---

## Usage

```bash
repomind audit .
repomind audit . --markdown-report
repomind benchmark /path/to/repo1 /path/to/repo2
```

---

## Model Evolution

Scores are tied to a **scoring version** (e.g. `2.0`). Each version defines fixed thresholds and penalty logic. When we change the model, we bump the version and document the change in [docs/MODEL_EVOLUTION.md](docs/MODEL_EVOLUTION.md). This lets you:

- Reproduce and compare runs over time
- Know which policy produced a given score
- Track benchmark results per version

The current default profile is `v2_default`. Overrides via `.repomind.json` use a custom profile name and are recorded in the scan output.

---

## Benchmark Corpus

RepoMind is tested against a fixed set of 10 open-source Python repositories (e.g. requests, flask, fastapi, click, celery, django, pydantic, sqlalchemy, numpy, pandas). Benchmark runs (`benchmark_repos.py --local`) produce comparable results across scoring versions and help validate changes before release.

---

## Guaranteed scan.json fields

The following fields are guaranteed in `scan.json` for the architecture score and classification:

| Field | Description |
|-------|-------------|
| `architecture_score.scoring_version` | Version string of the scoring model (e.g. `"2.0"`) |
| `architecture_score.structural_profile` | Ratios and metrics used in scoring (e.g. `long_file_ratio`, `cycle_ratio`, `centralization_score`, `cross_folder_ratio`) |
| `structural_class` | Top-level classification (e.g. `small_lib`, `mid_app`, `large_framework`, `core_engine`) |
| `structural_class_meta` | Metadata for the structural class (e.g. size band, heuristics applied) |

---

## Configuration

RepoMind reads optional config from the repository root: `.repomind.json`.

- **Layer order** (for layer violation detection): `"layer_order": ["data", "domain", "api"]` — list folder names from lowest to highest layer.
- **Scoring override:** `"scoring": { ... }` — override thresholds and penalties. All keys are optional; omitted keys use defaults. When you override, the scan result records `scoring_mode: "custom"` and optionally a named `scoring_profile` (e.g. `"enterprise_relaxed"`). The default profile `v2_default` is the reference metric; overrides are explicit deviation so benchmarks and reports stay unambiguous.

Supported scoring keys (same names as in code):

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `long_file_threshold_low` | int | 500 | Min lines for "long file" low band |
| `long_file_threshold_high` | int | 800 | Min lines for "long file" high band |
| `long_file_penalty_low` | int | 2 | Risk points per file in low band |
| `long_file_penalty_high` | int | 5 | Risk points per file in high band |
| `cycle_penalty_2_node` | int | 10 | Base penalty for 2-node cycle (log-scale) |
| `centralization_threshold_ratio` | float | 0.05 | in_degree > this × total_files → penalty |
| `centralization_penalty` | int | 10 | Risk points if centralization exceeded |
| `cross_folder_threshold_low` | float | 0.2 | Ratio above this → low penalty |
| `cross_folder_threshold_high` | float | 0.4 | Ratio above this → high penalty |
| `cross_folder_penalty_low` | int | 10 | Risk points for low threshold |
| `cross_folder_penalty_high` | int | 20 | Risk points for high threshold |
| `structural_class_penalty_scale` | object | — | Per-class scale, e.g. `{"large_framework": 0.7}` |
| `structural_class_health_floor` | object | — | Per-class floor, e.g. `{"core_engine": 30}` |
| `scoring_profile` | string | — | When using overrides, name this profile (e.g. `"enterprise_relaxed"`). Written to `scan.json` so you can tell which policy was used. |

Example `.repomind.json` (default metric, no override):

```json
{
  "layer_order": ["data", "domain", "api"]
}
```

Example with scoring override (scan will show `scoring_mode: "custom"`, `scoring_profile: "enterprise_relaxed"`):

```json
{
  "layer_order": ["data", "domain", "api"],
  "scoring": {
    "scoring_profile": "enterprise_relaxed",
    "long_file_threshold_low": 400,
    "structural_class_health_floor": { "large_framework": 28 }
  }
}
```

---

## Roadmap

- **Config override** — Done. `.repomind.json` scoring overrides and `scoring_mode` / `scoring_profile` in output.
- **HTML report** — Planned.
- **CI integration** — Planned.
- **Logistic / percentile-based scoring** — Under research; no commitment to a release format yet.

---

## Status

This project is in **research phase**. The scoring model and output format may change. Use it for experimentation and benchmarking, not as a single source of truth for production decisions without version tracking and validation in your own context.
