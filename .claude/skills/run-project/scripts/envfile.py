# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

"""Set non-secret keys in the project's .env, showing the change first.

Usage: python envfile.py set KEY=VALUE [KEY=VALUE ...] [--root DIR] [--apply]

Without --apply it only prints the diff. Refuses GITHUB_TOKEN (the user edits secrets themselves),
values with spaces, quotes, '#' or '$' (the run scripts don't parse them the same way), and a .env
that git does not ignore (or can't be checked; --no-git-check skips that). No backup copy is made, since
it would duplicate the secrets; only the listed keys' lines change.
"""

import argparse
import difflib
import os
import re
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True  # keep the skill folder free of __pycache__

from _common import ENV_LINE, SECRET_KEY, configure_stdout, fail, find_project_root, redact_url  # noqa: E402

KEY_PATTERN = re.compile(r'^[A-Z][A-Z0-9_]*$')
SECRET_KEYS = {'GITHUB_TOKEN'}


def main() -> None:
    configure_stdout()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('command', choices=['set'])
    parser.add_argument('pairs', nargs='+', metavar='KEY=VALUE')
    parser.add_argument('--root')
    parser.add_argument('--apply', action='store_true', help='Write the change (default: show the diff only)')
    parser.add_argument('--no-git-check', action='store_true', help='Skip the git-ignore check (no git available)')
    args = parser.parse_args()

    root = find_project_root(args.root)
    if not root:
        fail('Project root not found; pass --root')
    updates = {}
    for pair in args.pairs:
        key, sep, value = pair.partition('=')
        if not sep or not KEY_PATTERN.match(key):
            fail(f'Expected KEY=VALUE with an upper-case key, got: {pair}')
        if key in SECRET_KEYS or SECRET_KEY.search(key):
            fail(f'{key} is a secret; ask the user to add it to .env themselves')
        if re.search(r'[\s"\'#$`]', value):
            fail(f'Value for {key} contains spaces, quotes, "#", "$" or "`", which run.sh and run.ps1 parse differently')
        updates[key] = value

    path = os.path.join(root, '.env')
    if not args.no_git_check:
        if not shutil.which('git'):
            fail('git not found: cannot verify that .env is git-ignored (re-run with --no-git-check if it is)')
        code = subprocess.run(['git', 'check-ignore', '-q', '.env'], cwd=root, capture_output=True).returncode
        if code == 1:
            fail('.env is not ignored by git; refusing to write it')
        if code != 0:
            fail('could not verify that .env is git-ignored (not a git checkout?); re-run with --no-git-check if it is')
    old_lines = []
    if os.path.isfile(path):
        with open(path, encoding='utf-8-sig') as f:
            old_lines = f.read().splitlines()
    new_lines, done = [], set()
    for line in old_lines:
        match = ENV_LINE.match(line)
        key = match.group(1).strip() if match else None
        if key in updates:
            if key not in done:
                new_lines.append(f'{key}={updates[key]}')
                done.add(key)
            continue  # drop duplicate definitions of an updated key
        new_lines.append(line)
    new_lines.extend(f'{k}={v}' for k, v in updates.items() if k not in done)

    def masked(line: str) -> str:
        match = ENV_LINE.match(line)
        if not match:
            return line
        key, value = match.group(1).strip(), match.group(2).strip()
        return f'{key}=<hidden>' if SECRET_KEY.search(key) else f'{key}={redact_url(value)}'

    # Only changed lines (no context), with secrets and proxy credentials masked
    diff = list(difflib.unified_diff([masked(x) for x in old_lines], [masked(x) for x in new_lines],
                                     '.env (current)', '.env (new)', n=0, lineterm=''))
    print('\n'.join(diff) if diff else 'No changes.')
    if not diff or not args.apply:
        return
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(new_lines) + '\n')
    if os.name != 'nt' and not old_lines:
        os.chmod(path, 0o600)
    print(f'Updated {path}')


if __name__ == '__main__':
    main()
