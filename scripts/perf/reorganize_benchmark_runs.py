"""Move the existing recommendation benchmark corpus into the stage layout."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.perf.inventory_benchmark_runs import build_inventory, verify_inventory


STAGE_IDS = (
    "baseline-v1",
    "opt1-es-retrieval",
    "opt2-precomputed-features",
    "opt3-bulk-prefetch",
)
OPT1_SCORING_DIAGNOSTIC_IDS = {
    "recommendation-80000-full-personalized-20260715-004324",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reorganize the local recommendation benchmark corpus."
    )
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def ensure_within(root: Path, path: Path) -> Path:
    resolved_root = root.resolve()
    resolved_path = path.resolve()
    if resolved_path != resolved_root and resolved_root not in resolved_path.parents:
        raise ValueError(f"Path escapes benchmark root: {resolved_path}")
    return resolved_path


def classify_run(root: Path, run_dir: Path) -> Path | None:
    relative = run_dir.relative_to(root)
    top = relative.parts[0]
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    run_id = str(manifest.get("run_id") or run_dir.name)

    if top == "baseline-v1-full-personalized":
        return Path("stages/baseline-v1/runs/scale-sweep") / run_id
    if top == "INTENT":
        return Path("stages/baseline-v1/runs/diagnostics/intent-parser") / run_id
    if top == "opt1-es-retrieval-full-personalized":
        if run_id in OPT1_SCORING_DIAGNOSTIC_IDS:
            kind = Path("diagnostics/scoring")
        elif int(manifest.get("dataset", 0)) == 80000 and int(manifest.get("vus", 0)) == 10:
            if run_id.endswith("-20260714-225808"):
                kind = Path("scale-sweep")
            else:
                kind = Path("headline-repeats")
        else:
            kind = Path("scale-sweep")
        return Path("stages/opt1-es-retrieval/runs") / kind / run_id
    if top == "opt2-precomputed-features-full-personalized":
        return Path("stages/opt2-precomputed-features/runs/headline-repeats") / run_id
    if top == "opt3-bulk-prefetch-full-personalized":
        return Path("stages/opt3-bulk-prefetch/runs/headline-repeats") / run_id
    if top == "sweeps" and relative.parts[1].startswith("opt2-precomputed-features"):
        return Path("stages/opt2-precomputed-features/runs/scale-sweep") / run_id
    if top == "sweeps" and relative.parts[1].startswith("opt3-bulk-prefetch"):
        return Path("stages/opt3-bulk-prefetch/runs/scale-sweep") / run_id
    if top == "_quarantine":
        return Path("quarantine") / Path(*relative.parts[1:])
    if top in {"stages", "quarantine", "legacy"}:
        return None
    return Path("legacy/pending-removal/runs") / relative


def create_layout(root: Path) -> None:
    for stage_id in STAGE_IDS:
        for run_kind in ("scale-sweep", "headline-repeats", "diagnostics"):
            (root / "stages" / stage_id / "runs" / run_kind).mkdir(
                parents=True, exist_ok=True
            )
        for analysis_path in (
            "00-summary",
            "10-pipeline",
            "20-instrumentation",
            "30-root-cause/intent-parser",
            "30-root-cause/scoring",
            "30-root-cause/data-loading",
            "40-guardrails",
            "data",
        ):
            (root / "stages" / stage_id / "analysis" / analysis_path).mkdir(
                parents=True, exist_ok=True
            )
        (root / "transitions" / stage_id).mkdir(parents=True, exist_ok=True)
    for path in ("inbox", "workbench/previews", "quarantine", "legacy/pending-removal"):
        (root / path).mkdir(parents=True, exist_ok=True)


def remove_verified_archive_duplicates(
    root: Path,
    expected_inventory: dict,
    *,
    apply: bool,
) -> list[Path]:
    removed: list[Path] = []
    for duplicate in expected_inventory.get("duplicates", []):
        if not duplicate.get("content_identical"):
            raise ValueError(f"Unverified duplicate content: {duplicate['run_id']}")
        for relative_dir in duplicate["relative_dirs"]:
            if not relative_dir.startswith("_analysis-archive/"):
                continue
            path = ensure_within(root, root / relative_dir)
            print(f"DELETE_VERIFIED_DUPLICATE {relative_dir}")
            if apply:
                shutil.rmtree(path)
            removed.append(path)
    return removed


def move_generated_legacy(root: Path, *, apply: bool) -> None:
    moves = [
        (root / "INTENT" / "_analysis", root / "legacy/pending-removal/intent-analysis"),
        (root / "_analysis-archive", root / "legacy/pending-removal/analysis-archive"),
        (root / "INDEX.md", root / "legacy/pending-removal/INDEX.pre-restructure.md"),
    ]
    for source, destination in moves:
        if not source.exists():
            continue
        ensure_within(root, source)
        ensure_within(root, destination)
        if destination.exists():
            raise FileExistsError(destination)
        print(f"MOVE_LEGACY {source.relative_to(root)} -> {destination.relative_to(root)}")
        if apply:
            destination.parent.mkdir(parents=True, exist_ok=True)
            source.rename(destination)


def remove_empty_old_roots(root: Path) -> None:
    for name in (
        "baseline-v1-full-personalized",
        "INTENT",
        "opt1-es-retrieval-full-personalized",
        "opt2-precomputed-features-full-personalized",
        "opt3-bulk-prefetch-full-personalized",
        "sweeps",
    ):
        path = root / name
        if not path.exists():
            continue
        for directory in sorted(
            (item for item in path.rglob("*") if item.is_dir()),
            key=lambda item: len(item.parts),
            reverse=True,
        ):
            if not any(directory.iterdir()):
                directory.rmdir()
        if path.exists() and not any(path.iterdir()):
            path.rmdir()


def reorganize(root: Path, expected_inventory: dict, *, apply: bool) -> None:
    resolved_root = root.resolve()
    if apply:
        create_layout(resolved_root)
    remove_verified_archive_duplicates(
        resolved_root,
        expected_inventory,
        apply=apply,
    )
    manifest_paths = sorted(resolved_root.rglob("manifest.json"))
    for manifest_path in manifest_paths:
        run_dir = manifest_path.parent
        destination_relative = classify_run(resolved_root, run_dir)
        if destination_relative is None:
            continue
        destination = ensure_within(resolved_root, resolved_root / destination_relative)
        if destination == run_dir:
            continue
        if destination.exists():
            raise FileExistsError(destination)
        print(
            f"MOVE_RUN {run_dir.relative_to(resolved_root)} -> "
            f"{destination.relative_to(resolved_root)}"
        )
        if apply:
            destination.parent.mkdir(parents=True, exist_ok=True)
            run_dir.rename(destination)
    move_generated_legacy(resolved_root, apply=apply)
    if apply:
        remove_empty_old_roots(resolved_root)
        actual = build_inventory(resolved_root)
        verification = verify_inventory(expected_inventory, actual)
        print(json.dumps(verification, ensure_ascii=False, indent=2))
        if not verification["verified"]:
            raise RuntimeError("Benchmark run hash verification failed after migration")


def main() -> None:
    args = parse_args()
    root = args.root.resolve()
    ensure_within(root, root)
    expected_inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    reorganize(root, expected_inventory, apply=args.apply)
    if not args.apply:
        print("dry_run=true; pass --apply to move files")


if __name__ == "__main__":
    main()
