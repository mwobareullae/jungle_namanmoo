"""Inventory benchmark run files and verify lossless directory migrations."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Record benchmark run file hashes or verify them after reorganization."
    )
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify-against", type=Path)
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inventory_run(root: Path, manifest_path: Path) -> dict[str, Any]:
    run_dir = manifest_path.parent
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files: list[dict[str, Any]] = []
    directory_digest = hashlib.sha256()
    for path in sorted(item for item in run_dir.rglob("*") if item.is_file()):
        relative_path = path.relative_to(run_dir).as_posix()
        file_hash = sha256_file(path)
        size = path.stat().st_size
        files.append(
            {
                "path": relative_path,
                "size": size,
                "sha256": file_hash,
            }
        )
        directory_digest.update(relative_path.encode("utf-8"))
        directory_digest.update(b"\0")
        directory_digest.update(str(size).encode("ascii"))
        directory_digest.update(b"\0")
        directory_digest.update(file_hash.encode("ascii"))
        directory_digest.update(b"\n")
    return {
        "run_id": str(manifest.get("run_id") or run_dir.name),
        "relative_dir": run_dir.relative_to(root).as_posix(),
        "file_count": len(files),
        "byte_count": sum(item["size"] for item in files),
        "directory_sha256": directory_digest.hexdigest(),
        "files": files,
    }


def build_inventory(root: Path) -> dict[str, Any]:
    resolved_root = root.resolve()
    runs = [
        inventory_run(resolved_root, path)
        for path in sorted(resolved_root.rglob("manifest.json"))
    ]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        grouped[run["run_id"]].append(run)
    duplicates = []
    for run_id, copies in sorted(grouped.items()):
        if len(copies) < 2:
            continue
        duplicates.append(
            {
                "run_id": run_id,
                "copy_count": len(copies),
                "content_identical": len(
                    {copy["directory_sha256"] for copy in copies}
                )
                == 1,
                "relative_dirs": [copy["relative_dir"] for copy in copies],
            }
        )
    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "root": resolved_root.as_posix(),
        "manifest_count": len(runs),
        "unique_run_count": len(grouped),
        "file_count": sum(run["file_count"] for run in runs),
        "duplicates": duplicates,
        "runs": runs,
    }


def canonical_runs(inventory: dict[str, Any]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for run in inventory.get("runs", []):
        grouped[run["run_id"]].append(run)
    canonical: dict[str, dict[str, Any]] = {}
    for run_id, copies in grouped.items():
        hashes = {copy["directory_sha256"] for copy in copies}
        if len(hashes) != 1:
            raise ValueError(f"Conflicting duplicate run content: {run_id}")
        canonical[run_id] = copies[0]
    return canonical


def verify_inventory(
    expected: dict[str, Any],
    actual: dict[str, Any],
) -> dict[str, Any]:
    expected_runs = canonical_runs(expected)
    actual_runs = canonical_runs(actual)
    missing = sorted(set(expected_runs) - set(actual_runs))
    unexpected = sorted(set(actual_runs) - set(expected_runs))
    changed = sorted(
        run_id
        for run_id in set(expected_runs) & set(actual_runs)
        if expected_runs[run_id]["directory_sha256"]
        != actual_runs[run_id]["directory_sha256"]
    )
    duplicate_ids = sorted(
        duplicate["run_id"]
        for duplicate in actual.get("duplicates", [])
    )
    result = {
        "expected_unique_run_count": len(expected_runs),
        "actual_unique_run_count": len(actual_runs),
        "missing_run_ids": missing,
        "unexpected_run_ids": unexpected,
        "changed_run_ids": changed,
        "duplicate_run_ids": duplicate_ids,
    }
    result["verified"] = not any(
        (missing, unexpected, changed, duplicate_ids)
    )
    return result


def main() -> None:
    args = parse_args()
    inventory = build_inventory(args.root)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(inventory, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"inventory={args.output.resolve()}")
    print(f"manifest_count={inventory['manifest_count']}")
    print(f"unique_run_count={inventory['unique_run_count']}")
    print(f"duplicate_group_count={len(inventory['duplicates'])}")
    if args.verify_against:
        expected = json.loads(args.verify_against.read_text(encoding="utf-8"))
        result = verify_inventory(expected, inventory)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if not result["verified"]:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
