"""Classify merge changes by four Git trees, without blaming upstream for local-only code."""

from __future__ import annotations

import argparse
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class TreeEntry:
    """The mode and object ID recorded for one path in a Git tree."""

    mode: str
    object_id: str


def run_git(*args: str) -> bytes:
    return subprocess.run(
        ["git", *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout


def read_tree(revision: str) -> dict[str, TreeEntry]:
    """Read a complete tree while retaining paths that contain non-ASCII characters."""

    entries: dict[str, TreeEntry] = {}
    for raw_entry in run_git("ls-tree", "-r", "-z", "--full-tree", revision).split(b"\0"):
        if not raw_entry:
            continue
        metadata, raw_path = raw_entry.split(b"\t", 1)
        mode, _kind, object_id = metadata.decode("ascii").split()
        entries[raw_path.decode("utf-8")] = TreeEntry(mode=mode, object_id=object_id)
    return entries


def changed(left: TreeEntry | None, right: TreeEntry | None) -> bool:
    return left != right


def build_report(
    base: dict[str, TreeEntry],
    local: dict[str, TreeEntry],
    upstream: dict[str, TreeEntry],
    merged: dict[str, TreeEntry],
) -> dict[str, list[str] | int]:
    """Return the path groups that need a human merge-decision audit."""

    local_only_preserved = 0
    local_only_modified: list[str] = []
    local_only_removed: list[str] = []
    local_change_lost: list[str] = []
    upstream_baseline_removed: list[str] = []
    both_sides_changed: list[str] = []

    for path in sorted(set(base) | set(local) | set(upstream) | set(merged)):
        base_entry = base.get(path)
        local_entry = local.get(path)
        upstream_entry = upstream.get(path)
        merged_entry = merged.get(path)

        if base_entry is None and local_entry is not None and upstream_entry is None:
            if merged_entry is None:
                local_only_removed.append(path)
            elif changed(local_entry, merged_entry):
                local_only_modified.append(path)
            else:
                local_only_preserved += 1
            continue

        if (
            base_entry is not None
            and changed(base_entry, local_entry)
            and upstream_entry == base_entry
            and changed(local_entry, merged_entry)
        ):
            local_change_lost.append(path)

        if base_entry is not None and upstream_entry is None:
            upstream_baseline_removed.append(path)

        if (
            base_entry is not None
            and changed(base_entry, local_entry)
            and changed(base_entry, upstream_entry)
        ):
            both_sides_changed.append(path)

    return {
        "local_only_preserved": local_only_preserved,
        "local_only_modified": local_only_modified,
        "local_only_removed": local_only_removed,
        "local_change_lost": local_change_lost,
        "upstream_baseline_removed": upstream_baseline_removed,
        "both_sides_changed": both_sides_changed,
    }


def print_paths(title: str, paths: list[str]) -> None:
    print(f"\n{title}: {len(paths)}")
    for path in paths:
        print(f"  {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("merge", help="A merge commit to inspect")
    parser.add_argument(
        "--local-parent",
        help="Local parent revision; defaults to the first parent of the merge",
    )
    parser.add_argument(
        "--upstream-parent",
        help="Upstream parent revision; defaults to the second parent of the merge",
    )
    args = parser.parse_args()

    parents = run_git("show", "-s", "--format=%P", args.merge).decode("ascii").split()
    if len(parents) != 2 and (args.local_parent is None or args.upstream_parent is None):
        parser.error("merge must have exactly two parents, or both parent revisions must be supplied")

    local_parent = args.local_parent or parents[0]
    upstream_parent = args.upstream_parent or parents[1]
    merge_base = run_git("merge-base", local_parent, upstream_parent).decode("ascii").strip()
    report = build_report(
        read_tree(merge_base),
        read_tree(local_parent),
        read_tree(upstream_parent),
        read_tree(args.merge),
    )

    print(f"merge: {args.merge}")
    print(f"base: {merge_base}")
    print(f"local parent: {local_parent}")
    print(f"upstream parent: {upstream_parent}")
    print(f"local-only paths preserved unchanged: {report['local_only_preserved']}")
    print_paths("LOCAL-ONLY PATHS MODIFIED BY MERGE", report["local_only_modified"])
    print_paths("LOCAL-ONLY PATHS REMOVED BY MERGE", report["local_only_removed"])
    print_paths("LOCAL CHANGES NOT PRESERVED WHILE UPSTREAM WAS UNCHANGED", report["local_change_lost"])
    print_paths("UPSTREAM REMOVED PATHS THAT EXISTED AT THE MERGE BASE", report["upstream_baseline_removed"])
    print_paths("PATHS CHANGED ON BOTH SIDES", report["both_sides_changed"])
    print(
        "\nOnly the fourth group represents an upstream deletion. The first three groups are local merge "
        "decisions and must never be described as upstream deleting local-only code."
    )


if __name__ == "__main__":
    main()
