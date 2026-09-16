#!/usr/bin/env python3
"""Fail-closed verifier for the r43-r65 formal carry-forward ledger.

This verifier intentionally does not infer completion from branch names.  A
revision only passes after the manifest records a final acceptance state and
concrete evidence.  During the audit, --allow-pending can be used to validate
only the ledger shape without emitting the final carry-forward PASS marker.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

EXPECTED_START = 43
EXPECTED_END = 65
EXPECTED_REVISIONS = list(range(EXPECTED_START, EXPECTED_END + 1))
FINAL_STATES = {
    "materialized",
    "already-equivalent",
    "not-applicable-with-evidence",
}
NON_FINAL_STATES = {"pending-audit"}
FORBIDDEN_EXPERIMENTAL_REVISIONS = {66, 67, 68, 69}


def fail(message: str) -> None:
    print(f"R43_R65_CARRY_FORWARD_FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "config"
        / "r43-r65-carry-forward-manifest.json",
    )
    parser.add_argument(
        "--allow-pending",
        action="store_true",
        help="validate ledger shape while audit entries are still pending",
    )
    args = parser.parse_args()

    try:
        data = json.loads(args.manifest.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"cannot read manifest: {exc}")

    declared_range = data.get("range") or {}
    if declared_range.get("start") != EXPECTED_START or declared_range.get("end") != EXPECTED_END:
        fail(f"range must be exactly r{EXPECTED_START}-r{EXPECTED_END}")

    rows = data.get("revisions")
    if not isinstance(rows, list):
        fail("revisions must be a list")

    numbers = [row.get("revision") for row in rows if isinstance(row, dict)]
    if numbers != EXPECTED_REVISIONS:
        fail(
            "revision sequence must be contiguous and ordered: "
            + ",".join(f"r{n}" for n in EXPECTED_REVISIONS)
        )

    if FORBIDDEN_EXPERIMENTAL_REVISIONS.intersection(numbers):
        fail("r66-r69 experiments must never appear in the formal carry-forward set")

    pending: list[int] = []
    for row in rows:
        revision = row["revision"]
        branch = row.get("source_branch")
        status = row.get("status")
        evidence = row.get("evidence")

        expected_prefix = f"dev-r{revision}-"
        if not isinstance(branch, str) or not branch.startswith(expected_prefix):
            fail(f"r{revision} source_branch must start with {expected_prefix!r}")

        if status in NON_FINAL_STATES:
            pending.append(revision)
            if evidence not in ([], None):
                fail(f"r{revision} pending audit must not masquerade evidence as acceptance")
            continue

        if status not in FINAL_STATES:
            fail(f"r{revision} has unsupported status {status!r}")

        if not isinstance(evidence, list) or not evidence:
            fail(f"r{revision} final state requires at least one concrete evidence entry")

        for index, item in enumerate(evidence):
            if not isinstance(item, dict):
                fail(f"r{revision} evidence[{index}] must be an object")
            kind = item.get("kind")
            ref = item.get("ref")
            note = item.get("note")
            if kind not in {"source", "test", "commit", "comparison", "runtime"}:
                fail(f"r{revision} evidence[{index}] has unsupported kind {kind!r}")
            if not isinstance(ref, str) or not ref.strip():
                fail(f"r{revision} evidence[{index}] requires a non-empty ref")
            if not isinstance(note, str) or not note.strip():
                fail(f"r{revision} evidence[{index}] requires a non-empty note")

    if pending:
        rendered = ", ".join(f"r{n}" for n in pending)
        if not args.allow_pending:
            fail(f"audit is still pending for: {rendered}")
        print(f"R43_R65_LEDGER_STRUCTURE_PASS pending={len(pending)} [{rendered}]")
        return 0

    print("R43_R65_CARRY_FORWARD_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
