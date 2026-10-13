# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

"""Print a compact, token-efficient digest of a run's report.json for synthesis.

Usage: python digest.py RUN_DIR [--max-body-lines N] [--files] [--repo NAME ...]

Diffs are NOT read. Commit SHAs are shown abbreviated; cite them in synthesis.json.
"""

import argparse
import sys

sys.dont_write_bytecode = True  # keep the skill folder free of __pycache__

from _common import configure_stdout, load_metadata, load_report, run_date  # noqa: E402


def format_stats(commit: dict) -> str:
    parts = []
    stats = commit.get('stats')
    if stats:
        parts.append(f"+{stats.get('additions', 0)}/-{stats.get('deletions', 0)}")
    if commit.get('files') is not None:
        parts.append(f"{len(commit['files'])} files")
    return f" [{', '.join(parts)}]" if parts else ''


def main() -> None:
    configure_stdout()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('run_dir', help='Run directory containing report.json')
    parser.add_argument('--max-body-lines', type=int, default=6, help='Commit message body lines to keep (default: 6)')
    parser.add_argument('--files', action='store_true', help='List changed file names per commit (if in the report)')
    parser.add_argument('--repo', action='append', help='Only include these repositories (repeatable)')
    args = parser.parse_args()

    repos = load_report(args.run_dir)
    if args.repo:
        repos = [r for r in repos if r['name'] in args.repo]
    metadata = load_metadata(args.run_dir)

    commits = [c for r in repos for c in r['commits']]
    duplicates = len(commits) - len({c['sha'] for c in commits if c['sha']}) - sum(1 for c in commits if not c['sha'])
    dates = sorted(c['date'][:10] for c in commits if c.get('date'))
    has_stats = any(c.get('stats') for c in commits)
    print('# Report digest')
    if metadata.get('username'):
        print(f"user: {metadata['username']}")
    print(f"since: {str(metadata.get('since') or '?')[:10]}  run date: {run_date(args.run_dir) or '?'}")
    if dates:
        print(f'commit dates: {dates[0]} .. {dates[-1]}')
    print(f'repositories: {len(repos)}  commits: {len(commits)}')
    if has_stats:
        additions = sum(c['stats'].get('additions', 0) for c in commits if c.get('stats'))
        deletions = sum(c['stats'].get('deletions', 0) for c in commits if c.get('stats'))
        print(f'lines: +{additions}/-{deletions}')
    if duplicates:
        print(f'note: {duplicates} commit(s) appear in more than one repository (e.g. forks); cite them under each repository')
    if any(not c['sha'] for c in commits):
        print('WARNING: some commits have no SHA (neither sha nor url fields); they cannot be cited')

    for repo in repos:
        print(f"\n## {repo['name']} ({len(repo['commits'])} commits)")
        if repo['description']:
            print(f"description: {repo['description']}")
        for commit in repo['commits']:
            date = (commit.get('date') or '')[:10]
            print(f"- {commit['short'] or '???????'} {date} {commit['subject']}{format_stats(commit)}")
            body = commit['body']
            for line in body[:args.max_body_lines]:
                print(f'    {line.strip()}')
            if args.max_body_lines and len(body) > args.max_body_lines:
                print(f'    (+{len(body) - args.max_body_lines} more lines)')
            if args.files and commit.get('files'):
                names = ', '.join(f['filename'] for f in commit['files'][:15])
                more = f' (+{len(commit["files"]) - 15} more)' if len(commit['files']) > 15 else ''
                print(f'    files: {names}{more}')


if __name__ == '__main__':
    main()
