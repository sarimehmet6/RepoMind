# Model Evolution

This document records each scoring version: what changed, how benchmarks were affected, and why.

---

## Version 2.0

**Version:** `2.0`  
**Default profile:** `v2_default`

### Change summary

- **Structural classification.** Repositories are classified into a structural class (e.g. `small_lib`, `mid_app`, `large_framework`, `core_engine`) based on size and layout. The class is written to `structural_class`; supporting metadata to `structural_class_meta`.
- **Context-aware penalty scaling.** Penalties are scaled by structural class (e.g. large frameworks get a lower scale factor) so that one-size-fits-all thresholds do not over-penalize big codebases.
- **Structural class health floor.** A minimum health score per class (e.g. `core_engine` has a higher floor) so that “inherently complex” layouts are not driven to very low scores by the same raw penalties as small apps.
- **`scoring_version` in output.** Every architecture score includes `scoring_version: "2.0"` (and `structural_profile`) so that results are traceable and comparable across runs and tools.

### Benchmark result summary

Benchmark runs on the fixed 10-repo OSS corpus show score distribution and regression vs. a pre–structural-class baseline. Large/framework repos see less harsh penalties; small libs remain strict. Exact numbers are recorded in benchmark artifacts for the tag or commit that introduced v2.0.

### Rationale

- Raw penalty sums were over-penalizing large, multi-package repos compared to small libraries.
- A single global health floor and no scaling made it hard to use one metric for both small tools and large frameworks.
- Versioning the model and exposing it in the output allows safe iteration and reproducible benchmarks without breaking consumers that track version.
