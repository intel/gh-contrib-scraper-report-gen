# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

"""Build a GitHub dependency-graph snapshot for requirements.txt from a pip installation report.

Usage: python -m pip install --dry-run --ignore-installed --quiet --report report.json -r requirements.txt
       python pip_report_snapshot.py report.json > snapshot.json
       gh api --method POST repos/OWNER/REPO/dependency-graph/snapshots --input snapshot.json

The dependency graph (and Dependabot alerts) then covers every package a fresh 'pip install -r requirements.txt'
installs, not only the direct requirements.

pip resolves for the platform it runs on (uvloop, for example, is not installed on Windows), so the workflow runs this
once per OS. Each run gets its own job correlator, so the Windows and Linux snapshots do not replace each other (how
the graph shows the two manifests is checked after the first run). Reads GITHUB_SHA, GITHUB_REF, GITHUB_RUN_ID, GITHUB_WORKFLOW and GITHUB_JOB from
the environment (local defaults for testing). Writes nothing but stdout and stderr. Standard library only.
"""

import argparse
import datetime
import json
import os
import re
import sys

MANIFEST = "requirements.txt"
DETECTOR = {
    "name": "pip-install-report",
    "url": "https://pip.pypa.io/en/stable/reference/installation-report/",
}
_NAME_END = re.compile(r"[\s;\[<>=!~(@]")


def normalize(name: str) -> str:
    """PEP 503 normalized project name, as used in pkg:pypi PURLs."""
    return re.sub(r"[-_.]+", "-", name).lower()


def build_snapshot(report: dict, env: dict) -> dict:
    """Return the dependency submission payload for a pip installation report."""
    packages = {normalize(p["metadata"]["name"]): p for p in report.get("install", [])}
    if not packages:
        raise ValueError("the pip report lists no packages; refusing to submit an empty snapshot")
    purls = {name: f"pkg:pypi/{name}@{p['metadata']['version']}" for name, p in packages.items()}

    resolved = {}
    for name, package in sorted(packages.items()):
        # Edges by name only (markers and extras are not evaluated), restricted to packages pip actually resolved
        children = {normalize(_NAME_END.split(req, maxsplit=1)[0]) for req in package["metadata"].get("requires_dist") or []}
        resolved[name] = {
            "package_url": purls[name],
            "relationship": "direct" if package.get("requested") else "indirect",
            "scope": "runtime",
            "dependencies": sorted(purls[c] for c in children if c in purls and c != name),
        }

    environment = report.get("environment", {})
    platform = environment.get("sys_platform") or "unknown"
    python = ".".join((environment.get("python_full_version") or "unknown").split(".")[:2])
    variant = f"{platform}, Python {python}"
    manifest_key = f"{MANIFEST} ({variant})"
    return {
        "version": 0,
        "sha": env["GITHUB_SHA"],
        "ref": env["GITHUB_REF"],
        "job": {
            # Only the latest snapshot per (correlator, detector name) counts, so one correlator per OS and Python
            "correlator": f"{env['GITHUB_WORKFLOW']} {env['GITHUB_JOB']} {platform} py{python}",
            "id": env["GITHUB_RUN_ID"],
        },
        "detector": {**DETECTOR, "version": report.get("pip_version") or "unknown"},
        "metadata": {"sys_platform": platform, "python_version": python},
        "scanned": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "manifests": {
            manifest_key: {"name": manifest_key, "file": {"source_location": MANIFEST}, "resolved": resolved},
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", maxsplit=1)[0])
    parser.add_argument("report", help="pip installation report (pip install --dry-run --report FILE)")
    args = parser.parse_args()

    with open(args.report, encoding="utf-8") as f:
        report = json.load(f)
    env = {
        "GITHUB_SHA": "0" * 40,
        "GITHUB_REF": "refs/heads/local",
        "GITHUB_RUN_ID": "local",
        "GITHUB_WORKFLOW": "local",
        "GITHUB_JOB": "local",
    } | {k: v for k, v in os.environ.items() if k.startswith("GITHUB_") and v}
    try:
        snapshot = build_snapshot(report, env)
    except (KeyError, ValueError) as e:
        print(f"::error::cannot build snapshot: {e}", file=sys.stderr)
        return 1

    json.dump(snapshot, sys.stdout, indent=1)
    print()
    for key, manifest in snapshot["manifests"].items():
        resolved = manifest["resolved"].values()
        direct = sum(r["relationship"] == "direct" for r in resolved)
        print(f"{key}: {len(resolved)} packages ({direct} direct)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
