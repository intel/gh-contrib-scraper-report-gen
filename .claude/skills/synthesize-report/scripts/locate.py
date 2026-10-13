# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

"""Locate a report run directory and describe what it contains.

Usage: python locate.py [--output-dir DIR] [--run NAME_OR_PATH]

Prints JSON. "status" is "json" when report.json is present (the supported input),
otherwise "no_json" -- in that case stop and ask the user before proceeding.
"""

import argparse
import json
import os
import sys

sys.dont_write_bytecode = True  # keep the skill folder free of __pycache__

from _common import RUN_DIR_PATTERN, configure_stdout, find_run_dir, load_metadata, run_date  # noqa: E402

KNOWN_REPORTS = ('report.json', 'report.txt', 'report.md')
SYNTHESIS_FILES = ('synthesis.json', 'synthesis.html')


def main() -> None:
    configure_stdout()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--output-dir', default='output', help='Directory containing run folders (default: ./output)')
    parser.add_argument('--run', help='Run folder name inside --output-dir, or a path to any run folder')
    args = parser.parse_args()

    run_dir = find_run_dir(args.output_dir, args.run)
    entries = sorted(os.listdir(run_dir))
    commits_dir = os.path.join(run_dir, 'commits')
    diff_count = len([f for f in os.listdir(commits_dir) if f.endswith('.diff')]) if os.path.isdir(commits_dir) else 0
    metadata = load_metadata(run_dir)

    result = {
        'run_dir': run_dir,
        'run_date': run_date(run_dir),
        'status': 'json' if 'report.json' in entries else 'no_json',
        'reports_present': [f for f in KNOWN_REPORTS if f in entries],
        'other_files': [f for f in entries if f not in KNOWN_REPORTS + SYNTHESIS_FILES + ('commits', 'metadata.json')],
        'diff_files': diff_count,
        'existing_synthesis': [f for f in SYNTHESIS_FILES if f in entries],
        'metadata': {k: metadata[k] for k in ('username', 'since', 'branches') if k in metadata},
        # Repositories scanned, including those without commits in the report
        'repositories_scanned': len(metadata.get('repositories', [])),
    }
    if result['status'] == 'no_json':
        parent = os.path.dirname(run_dir)
        older = sorted((d for d in os.listdir(parent) if RUN_DIR_PATTERN.match(d)
                        and os.path.isfile(os.path.join(parent, d, 'report.json'))), reverse=True)
        result['newest_run_with_json'] = os.path.join(parent, older[0]) if older else None
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
