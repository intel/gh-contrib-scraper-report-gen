# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

"""Shared helpers for the synthesize-report skill scripts (stdlib only)."""

import json
import os
import re
import sys

RUN_DIR_PATTERN = re.compile(r'^\d{8}_\d{6}$')
SHA_PATTERN = re.compile(r'(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])')
FULL_SHA_PATTERN = re.compile(r'[0-9a-f]{40}')

# Files whose changes rarely say anything about the work done
NOISE_FILE_PATTERNS = [re.compile(p) for p in (
    r'(^|/)(package-lock\.json|npm-shrinkwrap\.json|yarn\.lock|pnpm-lock\.yaml|poetry\.lock|Pipfile\.lock|uv\.lock'
    r'|Cargo\.lock|go\.sum|composer\.lock|Gemfile\.lock|packages\.lock\.json)$',
    r'\.(min\.js|min\.css|map|snap|svg|png|jpe?g|gif|ico|pdf|zip|gz|whl|jar|dll|so|exe)$',
    r'(^|/)(dist|build|vendor|node_modules|third_party|__snapshots__)/',
)]

CONTROL_PATTERN = re.compile(r'\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(\x07|\x1b\\)?|[\x00-\x08\x0b-\x1f\x7f]')

TRAILER_PATTERN = re.compile(
    r'^(Signed-off-by|Co-authored-by|Co-Authored-By|Change-Id|Reviewed-by|Acked-by|Tested-by|Cc):', re.IGNORECASE)


def configure_stdout() -> None:
    """Force UTF-8 output so non-ASCII text survives Windows consoles."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass


def fail(message: str, code: int = 1) -> None:
    print(f'ERROR: {message}', file=sys.stderr)
    sys.exit(code)


def find_run_dir(output_dir: str = 'output', run: str | None = None) -> str:
    """Resolve a run directory: an explicit path, a run name inside output_dir, or the latest run."""
    if run:
        if os.path.isdir(run):
            return os.path.abspath(run)
        candidate = os.path.join(output_dir, run)
        if os.path.isdir(candidate):
            return os.path.abspath(candidate)
        fail(f'Run directory not found: {run}')
    if not os.path.isdir(output_dir):
        fail(f'Output directory not found: {os.path.abspath(output_dir)}')
    runs = sorted(d for d in os.listdir(output_dir)
                  if RUN_DIR_PATTERN.match(d) and os.path.isdir(os.path.join(output_dir, d)))
    if not runs:
        fail(f'No run directories (YYYYMMDD_HHMMSS) found in {os.path.abspath(output_dir)}')
    return os.path.abspath(os.path.join(output_dir, runs[-1]))


def read_json(path: str):
    with open(path, encoding='utf-8-sig') as f:
        return json.load(f)


def load_metadata(run_dir: str) -> dict:
    path = os.path.join(run_dir, 'metadata.json')
    if not os.path.isfile(path):
        return {}
    try:
        return read_json(path)
    except (OSError, ValueError):
        return {}


def run_date(run_dir: str) -> str | None:
    """Return the run's date (YYYY-MM-DD) derived from its directory name, if it follows the naming scheme."""
    name = os.path.basename(os.path.normpath(run_dir))
    if RUN_DIR_PATTERN.match(name):
        return f'{name[0:4]}-{name[4:6]}-{name[6:8]}'
    return None


def is_noise_file(filename: str) -> bool:
    return any(p.search(filename) for p in NOISE_FILE_PATTERNS)


def clean_text(text: str) -> str:
    """Remove terminal escape sequences and control characters (keeps newlines and tabs)."""
    return CONTROL_PATTERN.sub('', text.replace('\r\n', '\n'))


def split_message(message: str) -> tuple[str, list[str]]:
    """Split a commit message into its subject line and meaningful body lines (trailers removed)."""
    lines = clean_text(message or '').strip().splitlines()
    subject = lines[0].strip() if lines else ''
    body = [line.rstrip() for line in lines[1:] if line.strip() and not TRAILER_PATTERN.match(line.strip())]
    return subject, body


def load_report(run_dir: str) -> list[dict]:
    """Load report.json and normalize commits.

    Returns:
        A list of repositories: {'name', 'description', 'commits': [...]}; each commit has
        'sha' (may be None), 'short', 'date', 'url', 'subject', 'body', 'stats', 'files'.
    """
    path = os.path.join(run_dir, 'report.json')
    try:
        data = read_json(path)
    except (OSError, ValueError) as e:
        fail(f'Cannot read {path}: {e}')
    if not isinstance(data, list) or not all(isinstance(r, dict) for r in data):
        fail(f'Unexpected report.json structure in {path}: expected a list of repository objects')

    repos = []
    for repo in data:
        commits = []
        raw_commits = repo.get('commits') or []
        if not isinstance(raw_commits, list):
            fail(f'Unexpected report.json structure: "commits" of {repo.get("name")} is not a list')
        for raw in raw_commits:
            if not isinstance(raw, dict):
                continue
            sha = raw.get('sha') if isinstance(raw.get('sha'), str) else None
            if not sha or not FULL_SHA_PATTERN.fullmatch(sha.lower()):
                match = SHA_PATTERN.search(str(raw.get('url') or ''))
                sha = match.group(0) if match else None
            files = raw.get('files_changed')
            if isinstance(files, list):
                files = [dict(f, filename=clean_text(f['filename'])) for f in files
                         if isinstance(f, dict) and isinstance(f.get('filename'), str)]
            else:
                files = None
            subject, body = split_message(str(raw.get('message') or ''))
            commits.append({
                'sha': sha.lower() if sha else None,
                'short': None,
                'date': raw.get('date') if isinstance(raw.get('date'), str) else None,
                'url': raw.get('url') if isinstance(raw.get('url'), str) else None,
                'subject': subject,
                'body': body,
                'stats': raw.get('stats') if isinstance(raw.get('stats'), dict) else None,
                'files': files,
            })
        repos.append({'name': clean_text(str(repo.get('name') or '')),
                      'description': clean_text(str(repo.get('description') or '')),
                      'commits': commits})
    assign_short_shas(repos)
    return repos


def assign_short_shas(repos: list[dict]) -> None:
    """Abbreviate SHAs git-style: at least 7 characters, longer where needed to stay unique."""
    shas = sorted({c['sha'] for r in repos for c in r['commits'] if c['sha']})
    lengths = {}
    for i, sha in enumerate(shas):
        length = 7
        for neighbour in (shas[i - 1] if i else None, shas[i + 1] if i + 1 < len(shas) else None):
            if neighbour:
                common = next((k for k in range(40) if sha[k] != neighbour[k]), 40)
                length = max(length, common + 1)
        lengths[sha] = length
    for repo in repos:
        for commit in repo['commits']:
            if commit['sha']:
                commit['short'] = commit['sha'][:lengths[commit['sha']]]


def index_commits(repos: list[dict]) -> dict[str, list[tuple[dict, dict]]]:
    """Map full commit SHA -> [(repo, commit), ...] (a SHA can appear in several repositories, e.g. forks)."""
    index: dict[str, list[tuple[dict, dict]]] = {}
    for repo in repos:
        for commit in repo['commits']:
            if commit['sha']:
                index.setdefault(commit['sha'], []).append((repo, commit))
    return index


def resolve_sha(ref, index: dict[str, list[tuple[dict, dict]]],
                prefer_repo: str | None = None) -> tuple[tuple[dict, dict] | None, str | None]:
    """Resolve a (possibly abbreviated) SHA to (repo, commit). Returns (entry, error)."""
    ref = str(ref or '').strip().lower()
    if not re.fullmatch(r'[0-9a-f]{7,40}', ref):
        return None, f'"{ref}" is not a commit SHA (7-40 hex characters)'
    matches = [sha for sha in index if sha.startswith(ref)]
    if not matches:
        return None, f'commit "{ref}" is not in the report'
    if len(matches) > 1:
        return None, f'commit "{ref}" is ambiguous ({len(matches)} matches); use more characters'
    entries = index[matches[0]]
    preferred = [e for e in entries if e[0]['name'] == prefer_repo]
    return (preferred or entries)[0], None
