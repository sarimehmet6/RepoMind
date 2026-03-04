"""Repository filesystem and structure scanner."""

import ast
import json
import re
from pathlib import Path

from repomind.classification.structural_class import classify_repo
from repomind.scoring.architecture_score import (
    LONG_FILE_THRESHOLD_LOW,
    compute_architecture_score,
)

# Directories to skip when walking (case-sensitive for determinism).
_SKIP_DIRS = frozenset({".git", "venv", ".venv", "env", ".env"})

# Minimum line count to consider a file "long".
LONG_FILE_THRESHOLD = 300

# Line count above which a file is considered for "god module" (with degree threshold).
GOD_MODULE_LINE_THRESHOLD = 800

# Config file at repo root for layer order (low to high). Key: "layer_order".
REPOMIND_CONFIG_NAME = ".repomind.json"

# Patterns for TODO/FIXME (case-insensitive, word boundary).
_TODO_PATTERN = re.compile(r"\bTODO\b", re.IGNORECASE)
_FIXME_PATTERN = re.compile(r"\bFIXME\b", re.IGNORECASE)


def _should_skip(path: Path, root: Path) -> bool:
    """Return True if any path component is in the skip set."""
    try:
        rel = path.relative_to(root)
    except ValueError:
        return True
    return any(part in _SKIP_DIRS for part in rel.parts)


def _count_functions_and_classes(source: str) -> tuple[int, int]:
    """Return (function_count, class_count) for Python source. Uses ast; returns (0, 0) on parse error."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return (0, 0)
    function_count = sum(1 for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
    class_count = sum(1 for n in ast.walk(tree) if isinstance(n, ast.ClassDef))
    return (function_count, class_count)


def _path_to_module_name(rel_path: str) -> str:
    """
    Convert relative file path to a normalized Python module name.
    - Removes leading 'src/' if present.
    - Example: src/copaw/agents/foo.py -> copaw.agents.foo
    """
    parts = list(Path(rel_path).with_suffix("").parts)
    if parts and parts[0] == "src":
        parts = parts[1:]
    return ".".join(parts)


def _resolve_relative_module(current_module: str, level: int, from_module: str | None, names: list[ast.alias]) -> set[str]:
    """
    Resolve relative import to absolute module names.
    - current_module: e.g. "repomind.scanners.repo_scanner"
    - level: 1 = current package, 2 = parent, etc.
    - from_module: node.module (e.g. "foo" in "from .foo import ...")
    - names: node.names (for "from . import x, y")
    Returns set of absolute module names (no filtering; caller maps to internal paths).
    """
    parts = current_module.split(".")
    if level >= len(parts):
        base = "" if level > len(parts) else ".".join(parts[: max(0, len(parts) - level)])
    else:
        base = ".".join(parts[: -level])
    out: set[str] = set()
    if from_module is not None:
        out.add(f"{base}.{from_module}" if base else from_module)
    else:
        for alias in names:
            if not alias.name:
                continue
            if alias.name == "*":
                if base:
                    out.add(base)
            else:
                out.add(f"{base}.{alias.name}" if base else alias.name)
    return out


def _extract_imports(source: str, current_module: str) -> set[str]:
    """
    Extract all imported module names from Python source using AST.
    Handles: 'import x', 'import x.y', 'from x import y', 'from x.y import z',
    and relative imports: 'from . import foo', 'from .foo import bar', 'from ..pkg import x'.
    Relative imports are resolved to absolute module names using current_module (from file path).
    Returns a set of absolute module names. External/stdlib not filtered here (caller keeps internal only).
    Safe: parse errors return empty set.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name:
                    imported.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                if node.module:
                    imported.add(node.module)
            else:
                imported.update(
                    _resolve_relative_module(
                        current_module, node.level, node.module, node.names
                    )
                )
    return imported


def _build_internal_module_map(per_file_stats: dict[str, dict]) -> dict[str, str]:
    """Build module_name -> relative_path for all internal .py files. Deterministic key order."""
    module_to_path: dict[str, str] = {}
    for rel_path in sorted(per_file_stats.keys()):
        module_to_path[_path_to_module_name(rel_path)] = rel_path
        if Path(rel_path).name == "__init__.py":
            parent = Path(rel_path).parent
            if parent.parts:
                parts = list(parent.parts)
                if parts and parts[0] == "src":
                    parts = parts[1:]
                module_to_path[".".join(parts)] = rel_path
    return module_to_path


def compute_strongly_connected_components(import_map: dict[str, list[str]]) -> list[list[str]]:
    """
    Tarjan's strongly connected components algorithm (O(V + E)).
    Any SCC with size > 1 represents a circular dependency group.
    Deterministic: nodes and adjacency are traversed in sorted order.
    """
    # Collect all nodes that appear either as a key or as a dependency.
    nodes = sorted(set(import_map.keys()) | {dep for deps in import_map.values() for dep in deps})
    index: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    current_index = 0
    sccs: list[list[str]] = []

    def strongconnect(v: str) -> None:
        nonlocal current_index
        index[v] = current_index
        lowlink[v] = current_index
        current_index += 1
        stack.append(v)
        on_stack.add(v)

        # Successors considered in sorted order for determinism.
        for w in sorted(import_map.get(v, [])):
            if w not in index:
                strongconnect(w)
                lowlink[v] = min(lowlink[v], lowlink[w])
            elif w in on_stack:
                lowlink[v] = min(lowlink[v], index[w])

        # If v is a root node, pop the stack and generate an SCC.
        if lowlink[v] == index[v]:
            component: list[str] = []
            while True:
                w = stack.pop()
                on_stack.remove(w)
                component.append(w)
                if w == v:
                    break
            # Sort component members for deterministic internal ordering.
            component.sort()
            sccs.append(component)

    for v in nodes:
        if v not in index:
            strongconnect(v)

    # Sort SCC groups by first file path for deterministic ordering.
    sccs.sort(key=lambda comp: comp[0] if comp else "")
    return sccs


def _find_circular_dependencies(import_map: dict[str, list[str]]) -> list[list[str]]:
    """
    Find circular dependency groups using SCCs.
    Returns a deterministic list of cycles; each cycle is a list of file paths with the first
    file repeated at the end to close the cycle, e.g. ["file_a.py", "file_b.py", "file_a.py"].
    """
    sccs = compute_strongly_connected_components(import_map)
    cycles: list[list[str]] = []
    for comp in sccs:
        if len(comp) <= 1:
            continue
        # For 2-node SCCs, emit [a, b, a] for compatibility.
        if len(comp) == 2:
            a, b = comp
            cycles.append([a, b, a])
        else:
            # For larger SCCs, represent as sorted list plus first element again.
            cycles.append(comp + [comp[0]])
    # Deterministic ordering by full tuple of cycle.
    cycles.sort(key=lambda c: tuple(c))
    return cycles


def _top_level_folder(rel_path: str) -> str:
    """
    Return the top-level folder for a file path.
    Defined as the first folder after the project root or 'src'.
    Examples:
    - src/copaw/agents/foo.py -> copaw
    - copaw/agents/foo.py -> copaw
    - repomind/scanners/foo.py -> repomind
    - foo.py (at repo root) -> '.'
    """
    parts = rel_path.replace("\\", "/").strip("/").split("/")
    if not parts or parts == [""]:
        return "."
    if parts[0] == "src":
        return parts[1] if len(parts) > 1 else "."
    # If there's at least one directory component, use the first one.
    if len(parts) >= 2:
        return parts[0]
    return "."


def _compute_folder_coupling(import_map: dict[str, list[str]]) -> tuple[dict, float, int, int]:
    """
    Build folder-level coupling from import_map. Deterministic.
    Returns (folder_coupling, cross_folder_dependency_ratio).
    folder_coupling: { folder: { "external_dependencies": int, "depends_on": [folder, ...] } }
    """
    total_edges = 0
    cross_edges = 0
    folder_depends_on: dict[str, set[str]] = {}

    for src_file, deps in import_map.items():
        src_folder = _top_level_folder(src_file)
        folder_depends_on.setdefault(src_folder, set())
        for dep in deps:
            total_edges += 1
            dst_folder = _top_level_folder(dep)
            if src_folder != dst_folder:
                cross_edges += 1
                folder_depends_on[src_folder].add(dst_folder)

    folder_coupling = {}
    for folder in sorted(folder_depends_on.keys()):
        depends_on = sorted(folder_depends_on[folder])
        folder_coupling[folder] = {
            "external_dependencies": len(depends_on),
            "depends_on": depends_on,
        }

    ratio = (cross_edges / total_edges) if total_edges > 0 else 0.0
    return folder_coupling, ratio, total_edges, cross_edges


def _build_cycle_analysis(circular_dependencies: list[list[str]]) -> dict:
    """
    Classify and enrich circular dependency cycles for reporting.
    Types:
      - 2 nodes -> tight_coupling
      - 3–5 nodes -> layer_leak
      - >5 nodes -> structural_cycle
    Each cycle adds: type, length, files, folders, risk_score.
    Deterministic ordering by (type, length, files tuple).
    """
    def _effective_nodes(cycle: list[str]) -> list[str]:
        if len(cycle) >= 2 and cycle[0] == cycle[-1]:
            return cycle[:-1]
        return cycle[:]

    typed_cycles = []
    tight_count = 0
    leak_count = 0
    structural_count = 0

    for raw in circular_dependencies:
        nodes = _effective_nodes(raw)
        length = len(nodes)
        if length < 2:
            continue
        if length == 2:
            ctype = "tight_coupling"
            tight_count += 1
        elif 3 <= length <= 5:
            ctype = "layer_leak"
            leak_count += 1
        else:
            ctype = "structural_cycle"
            structural_count += 1

        folders = sorted({ _top_level_folder(p) for p in nodes })
        risk_score = length * 2

        typed_cycles.append(
            {
                "type": ctype,
                "length": length,
                "files": nodes,
                "folders": folders,
                "risk_score": risk_score,
            }
        )

    typed_cycles.sort(
        key=lambda c: (
            c["type"],
            c["length"],
            tuple(c["files"]),
        )
    )

    return {
        "tight_coupling_count": tight_count,
        "layer_leak_count": leak_count,
        "structural_cycle_count": structural_count,
        "cycles": typed_cycles,
    }


def _load_repomind_config(root: Path) -> dict:
    """Load .repomind.json at repo root. Returns {} if missing/invalid."""
    config_path = root / REPOMIND_CONFIG_NAME
    if not config_path.is_file():
        return {}
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    return {}


def _compute_tight_coupling_pairs(circular_dependencies: list[list[str]]) -> list[list[str]]:
    """Extract 2-node cycles (mutual imports) as sorted pairs. Deterministic."""
    pairs: list[list[str]] = []
    for cycle in circular_dependencies:
        # Cycle is e.g. ["a", "b", "a"] for 2-node
        if len(cycle) == 3 and cycle[0] == cycle[-1]:
            a, b = cycle[0], cycle[1]
            pair = sorted([a, b])
            if pair not in pairs:
                pairs.append(pair)
    return sorted(pairs, key=lambda p: (p[0], p[1]))


def _compute_core_modules(
    import_map: dict[str, list[str]],
    in_degree: dict[str, int],
    all_paths: list[str],
) -> list[dict]:
    """
    Core module score: normalized in/out degree and combined centrality.
    Returns list of entries sorted by centrality desc then path; only files with dependency activity.
    """
    max_in = max(in_degree.values()) if in_degree else 1
    max_out = 1
    for path in all_paths:
        out = len(import_map.get(path, []))
        if out > max_out:
            max_out = out
    if max_in == 0:
        max_in = 1
    if max_out == 0:
        max_out = 1

    candidates: list[tuple[str, int, int, float]] = []
    for path in all_paths:
        inc = in_degree.get(path, 0)
        out = len(import_map.get(path, []))
        if inc == 0 and out == 0:
            continue
        norm_in = inc / max_in
        norm_out = out / max_out
        centrality = (norm_in + norm_out) / 2.0
        candidates.append((path, inc, out, centrality))

    candidates.sort(key=lambda x: (-x[3], x[0]))
    return [
        {
            "path": p,
            "in_degree": inc,
            "out_degree": out,
            "normalized_in": round(inc / max_in, 4),
            "normalized_out": round(out / max_out, 4),
            "centrality_score": round(c, 4),
        }
        for p, inc, out, c in candidates
    ]


def _compute_god_module_candidates(
    per_file_stats: dict[str, dict],
    import_map: dict[str, list[str]],
    in_degree: dict[str, int],
) -> list[dict]:
    """Files with lines > 800 and (in_degree + out_degree) above project median. Sorted by path."""
    all_paths = sorted(per_file_stats.keys())
    degrees = []
    for path in all_paths:
        deg = in_degree.get(path, 0) + len(import_map.get(path, []))
        degrees.append(deg)
    degrees.sort()
    n = len(degrees)
    median_degree = degrees[n // 2] if n else 0

    candidates = []
    for path in all_paths:
        lines = (per_file_stats.get(path) or {}).get("lines", 0)
        if lines <= GOD_MODULE_LINE_THRESHOLD:
            continue
        inc = in_degree.get(path, 0)
        out = len(import_map.get(path, []))
        total = inc + out
        if total > median_degree:
            candidates.append(
                {"path": path, "lines": lines, "in_degree": inc, "out_degree": out}
            )
    return sorted(candidates, key=lambda x: x["path"])


def _compute_layer_violations(
    import_map: dict[str, list[str]],
    layer_order: list[str],
) -> list[dict]:
    """
    Detect lower-level folder importing higher-level folder.
    layer_order[0] = lowest layer. Violation when importer layer index < imported layer index.
    Returns list sorted by importer_folder then imported_folder.
    """
    layer_index = {f: i for i, f in enumerate(layer_order)}
    violations_set: set[tuple[str, str]] = set()
    for src_file, deps in import_map.items():
        src_folder = _top_level_folder(src_file)
        si = layer_index.get(src_folder)
        if si is None:
            continue
        for dep in deps:
            dst_folder = _top_level_folder(dep)
            di = layer_index.get(dst_folder)
            if di is None:
                continue
            if si < di:
                violations_set.add((src_folder, dst_folder))
    return sorted(
        [{"importer_folder": a, "imported_folder": b} for a, b in violations_set],
        key=lambda x: (x["importer_folder"], x["imported_folder"]),
    )


def _build_architectural_risks(
    dependency_stats: dict,
    per_file_stats: dict[str, dict],
    layer_order: list[str] | None,
) -> dict:
    """Build architectural_risks for scan.json. Deterministic, sorted lists."""
    import_map = dependency_stats.get("import_map") or {}
    in_degree = dependency_stats.get("in_degree") or {}
    circular_dependencies = dependency_stats.get("circular_dependencies") or []
    all_paths = sorted(per_file_stats.keys())

    tight_coupling_pairs = _compute_tight_coupling_pairs(circular_dependencies)
    core_modules = _compute_core_modules(import_map, in_degree, all_paths)
    god_module_candidates = _compute_god_module_candidates(
        per_file_stats, import_map, in_degree
    )
    layer_violations = (
        _compute_layer_violations(import_map, layer_order)
        if layer_order
        else []
    )

    return {
        "tight_coupling_pairs": tight_coupling_pairs,
        "core_modules": core_modules,
        "god_module_candidates": god_module_candidates,
        "layer_violations": layer_violations,
    }


def _build_dependency_stats(
    py_files: list[Path],
    per_file_stats: dict[str, dict],
    root: Path,
) -> dict[str, dict]:
    """
    Build import_map (file -> [imported internal files]), in_degree, and circular_dependencies.
    Only includes imports that resolve to other .py files in the same repository; external libs ignored.
    """
    module_to_path = _build_internal_module_map(per_file_stats)
    import_map: dict[str, list[str]] = {}
    for file_path in py_files:
        rel_path = str(file_path.relative_to(root))
        try:
            text = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            import_map[rel_path] = []
            continue
        current_module = _path_to_module_name(rel_path)
        imported_modules = _extract_imports(text, current_module)
        # Only internal project modules; stdlib and pip are not in module_to_path.
        internal_deps = sorted(module_to_path[m] for m in imported_modules if m in module_to_path)
        import_map[rel_path] = internal_deps

    in_degree: dict[str, int] = {rel_path: 0 for rel_path in sorted(per_file_stats.keys())}
    for deps in import_map.values():
        for dep in deps:
            if dep in in_degree:
                in_degree[dep] += 1

    circular_dependencies = _find_circular_dependencies(import_map)
    cycle_analysis = _build_cycle_analysis(circular_dependencies)
    folder_coupling, cross_folder_dependency_ratio, total_edges, cross_edges = _compute_folder_coupling(import_map)

    possible_import_resolution_issue = bool(
        total_edges > 0 and cross_folder_dependency_ratio == 0.0
    )

    return {
        "import_map": import_map,
        "in_degree": in_degree,
        "circular_dependencies": circular_dependencies,
        "cycle_analysis": cycle_analysis,
        "folder_coupling": folder_coupling,
        "cross_folder_dependency_ratio": cross_folder_dependency_ratio,
        "possible_import_resolution_issue": possible_import_resolution_issue,
    }


def scan_repository(path: str) -> dict:
    """
    Scan a repository at the given path and return structured metadata.
    Walks only .py files, ignores .git and common virtual env directories.
    Deterministic: file order and keys are stable.
    """
    root = Path(path).resolve()
    if not root.is_dir():
        return {"path": str(root), "valid": False, "error": "Not a directory"}

    total_lines = 0
    todo_count = 0
    fixme_count = 0
    long_files: list[dict] = []
    per_file_stats: dict[str, dict] = {}

    # Collect .py files under root, skipping _SKIP_DIRS; sort for determinism.
    py_files: list[Path] = []
    for p in sorted(root.rglob("*.py")):
        if not p.is_file():
            continue
        if _should_skip(p, root):
            continue
        py_files.append(p)

    for file_path in py_files:
        try:
            text = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines = text.splitlines()
        line_count = len(lines)
        total_lines += line_count

        todo_count += len(_TODO_PATTERN.findall(text))
        fixme_count += len(_FIXME_PATTERN.findall(text))

        func_count, class_count = _count_functions_and_classes(text)
        rel_path = str(file_path.relative_to(root))
        per_file_stats[rel_path] = {
            "lines": line_count,
            "function_count": func_count,
            "class_count": class_count,
        }

        if line_count > LONG_FILE_THRESHOLD:
            long_files.append({"path": rel_path, "lines": line_count})

    # Sort long_files by path for deterministic output.
    long_files.sort(key=lambda x: x["path"])

    dependency_stats = _build_dependency_stats(py_files, per_file_stats, root)
    config = _load_repomind_config(root)
    layer_order = config.get("layer_order")
    architectural_risks = _build_architectural_risks(
        dependency_stats, per_file_stats, layer_order
    )

    total_files = len(per_file_stats)
    total_long_files = sum(
        1
        for path in sorted(per_file_stats.keys())
        if (per_file_stats.get(path) or {}).get("lines", 0) > LONG_FILE_THRESHOLD_LOW
    )
    in_degree = dependency_stats.get("in_degree") or {}
    max_in = max(in_degree.values(), default=0)
    max_in_degree_file = ""
    if in_degree:
        candidates = sorted(p for p, d in in_degree.items() if d == max_in)
        if candidates:
            max_in_degree_file = candidates[0]
    total_cycles = len(dependency_stats.get("circular_dependencies") or [])

    scan_result = {
        "path": str(root),
        "valid": True,
        "source_files": len(py_files),
        "total_lines": total_lines,
        "total_files": total_files,
        "total_long_files": total_long_files,
        "max_in_degree_file": max_in_degree_file,
        "total_cycles": total_cycles,
        "long_files": long_files,
        "todo_count": todo_count,
        "fixme_count": fixme_count,
        "per_file_stats": per_file_stats,
        "dependency_stats": dependency_stats,
        "architectural_risks": architectural_risks,
    }

    structural_class, structural_meta = classify_repo(scan_result)
    scan_result["structural_class"] = structural_class
    scan_result["structural_class_meta"] = structural_meta

    scoring_config = (config.get("scoring") or {}) if isinstance(config, dict) else {}
    scan_result["architecture_score"] = compute_architecture_score(
        scan_result, scoring_config
    )
    return scan_result
