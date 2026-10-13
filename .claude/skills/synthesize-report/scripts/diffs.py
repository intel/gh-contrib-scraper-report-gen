# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

"""Rank commits by likely importance and print compact digests of their diffs.

Usage:
  python diffs.py rank RUN_DIR [--top N]
  python diffs.py show RUN_DIR SHA [SHA ...] [--max-lines-per-file N] [--max-chars N]

"rank" uses only the report and diff headers (no patch content) to suggest which commits
are worth a closer look. "show" prints per-file change counts and truncated patches,
skipping noise (lock files, generated/vendored/binary files).
"""

import argparse
import math
import os
import re
import sys

sys.dont_write_bytecode = True  # keep the skill folder free of __pycache__

from _common import clean_text, configure_stdout, fail, index_commits, is_noise_file, load_report, resolve_sha  # noqa: E402

TYPE_WEIGHTS = {
    'feat': 3.0, 'perf': 2.5, 'fix': 2.5, 'refactor': 2.0, 'revert': 1.0, 'test': 1.5,
    'docs': 1.0, 'build': 0.75, 'ci': 0.75, 'chore': 0.5, 'style': 0.5,
}
DEFAULT_TYPE_WEIGHT = 1.5
CONVENTIONAL_PATTERN = re.compile(r'^(\w+)(\([^)]*\))?!?:')
FILE_SEPARATOR = '-' * 60


def parse_diff(path: str) -> list[dict]:
    """Parse a diff file written by the scraper into [{filename, status, additions, deletions, patch}]."""
    with open(path, encoding='utf-8', errors='replace') as f:
        content = clean_text(f.read())
    files = []
    # A separator line is only one if followed by the next file header (or EOF); a patch line can look the same
    for block in re.split(r'^' + FILE_SEPARATOR + r'\n(?=File: |\Z)', content, flags=re.MULTILINE):
        if not block.strip():
            continue
        entry = {'filename': '?', 'status': '?', 'additions': 0, 'deletions': 0, 'patch': ''}
        header, _, patch = block.partition('Patch:\n')
        for line in header.splitlines():
            if line.startswith('File: '):
                entry['filename'] = line[6:].strip()
            elif line.startswith('Status: '):
                entry['status'] = line[8:].strip()
            elif line.startswith('Changes: '):
                match = re.match(r'Changes: \+(\d+) -(\d+)', line)
                if match:
                    entry['additions'], entry['deletions'] = int(match.group(1)), int(match.group(2))
        entry['patch'] = patch.rstrip('\n')
        files.append(entry)
    return files


def commit_files(run_dir: str, commit: dict) -> tuple[list[dict] | None, bool]:
    """Return (files, has_diff). Falls back to report files_changed when no diff file was saved."""
    path = os.path.join(run_dir, 'commits', f"{commit['sha']}.diff")
    if commit['sha'] and os.path.isfile(path):
        return parse_diff(path), True
    return commit.get('files'), False


def score(commit: dict, files: list[dict] | None) -> float:
    match = CONVENTIONAL_PATTERN.match(commit['subject'])
    weight = TYPE_WEIGHTS.get(match.group(1).lower(), DEFAULT_TYPE_WEIGHT) if match else DEFAULT_TYPE_WEIGHT
    if files:
        meaningful = [f for f in files if not is_noise_file(f['filename'])]
        lines = sum(f.get('additions', 0) + f.get('deletions', 0) for f in meaningful)
        breadth = len(meaningful)
    else:
        stats = commit.get('stats') or {}
        lines, breadth = stats.get('total', 0), 0
    return weight * (1 + math.log10(1 + lines)) + 0.3 * math.log2(1 + breadth) + 0.1 * min(len(commit['body']), 10)


def cmd_rank(args) -> None:
    repos = load_report(args.run_dir)
    rows = []
    for repo in repos:
        for commit in repo['commits']:
            if not commit['sha']:
                continue
            files, has_diff = commit_files(args.run_dir, commit)
            rows.append((score(commit, files), repo['name'], commit, has_diff))
    # Commits without a saved diff can't be analysed, so they rank after those with one
    rows.sort(key=lambda r: (r[3], r[0]), reverse=True)
    print(f'# Top {min(args.top, len(rows))} of {len(rows)} commits by heuristic importance (verify with judgment)')
    for value, repo_name, commit, has_diff in rows[:args.top]:
        note = '' if has_diff else ' (no diff saved)'
        print(f"{value:5.2f}  {commit['short']}  {repo_name}  {commit['subject']}{note}")


def cmd_show(args) -> None:
    repos = load_report(args.run_dir)
    index = index_commits(repos)
    budget = args.max_chars
    for ref in args.shas:
        entry, error = resolve_sha(ref, index)
        if error:
            print(f'\n### {ref}: ERROR {error}')
            continue
        repo, commit = entry
        print(f"\n### {commit['short']} {repo['name']} {(commit.get('date') or '')[:10]}")
        print(f"subject: {commit['subject']}")
        for line in commit['body'][:10]:
            print(f'    {line.strip()}')
        files, has_diff = commit_files(args.run_dir, commit)
        if not files:
            print('(no diff or file list available)')
            continue
        if not has_diff:
            print('(no diff saved -- likely exceeded the scraper download limits; file list only)')
        for entry in files:
            print(f"* {entry['filename']} [{entry.get('status', '?')}] +{entry.get('additions', 0)} -{entry.get('deletions', 0)}")
            if not has_diff:
                continue
            if is_noise_file(entry['filename']):
                print('  (noise file, patch skipped)')
                continue
            if not entry['patch']:
                print('  (no patch: binary or too large)')
                continue
            lines = entry['patch'].splitlines()
            shown = lines[:args.max_lines_per_file]
            text = '\n'.join(shown)
            if len(text) > budget:
                print(f'  (patch omitted: character budget of {args.max_chars} exhausted)')
                continue
            budget -= len(text)
            print(text)
            if len(lines) > len(shown):
                print(f'  ... ({len(lines) - len(shown)} more patch lines)')


def main() -> None:
    configure_stdout()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    rank = sub.add_parser('rank', help='Rank commits by heuristic importance')
    rank.add_argument('run_dir')
    rank.add_argument('--top', type=int, default=10)
    show = sub.add_parser('show', help='Print compact diff digests for chosen commits')
    show.add_argument('run_dir')
    show.add_argument('shas', nargs='+')
    show.add_argument('--max-lines-per-file', type=int, default=60)
    show.add_argument('--max-chars', type=int, default=20000, help='Total patch characters across all commits')
    args = parser.parse_args()
    if not os.path.isdir(args.run_dir):
        fail(f'Run directory not found: {args.run_dir}')
    cmd_rank(args) if args.command == 'rank' else cmd_show(args)


if __name__ == '__main__':
    main()
