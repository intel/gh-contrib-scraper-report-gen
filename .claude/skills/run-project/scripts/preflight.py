# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

"""Check whether the project is set up to generate a report, without changing anything.

Usage: python preflight.py [--root DIR] [--api-url URL] [--output-dir DIR] [--ca-bundle PATH] [--no-verify-ssl] [--offline]

Prints JSON: project/venv state, .env keys (names only), token summary (owner keys and fingerprints only),
network settings (proxy sources, CA bundle) and a connectivity/token check against the GitHub API,
plus the last report run. "missing" lists what blocks a report run.
"""

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import urllib.request
from datetime import datetime

sys.dont_write_bytecode = True  # keep the skill folder free of __pycache__

from _common import (DEFAULT_API_URL, NETWORK_KEYS, ORIGINAL_ENVIRON, GitHubClient, configure_stdout, describe_error,  # noqa: E402
                     fail, find_project_root, fingerprint, load_settings, parse_tokens, read_env_file,
                     redact_url, ssl_context)

RUN_DIR_PATTERN = re.compile(r'^\d{8}_\d{6}$')


def run_quiet(args: list[str], cwd: str) -> tuple[int, str]:
    try:
        result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=15)
        return result.returncode, result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return -1, ''


def venv_info(root: str) -> dict:
    python = os.path.join(root, '.venv', 'Scripts' if os.name == 'nt' else 'bin', 'python.exe' if os.name == 'nt' else 'python')
    info = {'exists': os.path.isdir(os.path.join(root, '.venv')), 'python': python if os.path.isfile(python) else None}
    if info['python']:
        code, out = run_quiet([python, '-c', 'import sys, github, yaml; print("%d.%d" % sys.version_info[:2])'], root)
        info['python_version'] = out or None
        info['dependencies_installed'] = code == 0
    return info


def last_run(root: str, output_dir: str) -> dict | None:
    base = os.path.join(root, output_dir)
    if not os.path.isdir(base):
        return None
    runs = sorted(d for d in os.listdir(base) if RUN_DIR_PATTERN.match(d) and os.path.isdir(os.path.join(base, d)))
    if not runs:
        return None
    name = runs[-1]
    info = {'run_dir': os.path.join(base, name),
            'generated_at': datetime.strptime(name, '%Y%m%d_%H%M%S').strftime('%Y-%m-%dT%H:%M:%S'),
            'run_count': len(runs)}
    try:
        with open(os.path.join(base, name, 'metadata.json'), encoding='utf-8') as f:
            metadata = json.load(f)
        info.update(username=metadata.get('username'), since=metadata.get('since'),
                    repositories=len(metadata.get('repositories', [])), branches=metadata.get('branches'))
    except (OSError, ValueError):
        pass
    return info


def network_info(root: str, env_file: dict, settings: dict) -> dict:
    proxies = {k: redact_url(v) for k, v in urllib.request.getproxies().items()}
    code, git_proxy = run_quiet(['git', 'config', '--get', 'http.proxy'], root) if shutil.which('git') else (-1, '')
    ca = settings.get('REQUESTS_CA_BUNDLE') or settings.get('SSL_CERT_FILE')
    return {
        # getproxies() covers environment variables and, on Windows, the system (registry) proxy
        'effective_proxies': proxies,
        'proxy_keys_in_env_file': [k for k in NETWORK_KEYS if 'proxy' in k.lower() and k in env_file],
        'proxy_keys_in_environment': [k for k in NETWORK_KEYS if 'proxy' in k.lower() and k in ORIGINAL_ENVIRON],
        # Upper/lower-case variants with different values: which one wins depends on the tool
        'proxy_conflicts': sorted({k.upper() for k in NETWORK_KEYS if 'proxy' in k.lower()
                                   and len({v for kk, v in {**ORIGINAL_ENVIRON, **env_file}.items()
                                            if kk.lower() == k.lower()}) > 1}),
        'git_http_proxy': redact_url(git_proxy) if code == 0 and git_proxy else None,
        'ca_bundle': {'path': ca, 'exists': os.path.isfile(ca)} if ca else None,
    }


def check_api(settings: dict, tokens: dict, api_url: str, args) -> dict:
    context = ssl_context(settings, args.no_verify_ssl, args.ca_bundle)
    status, headers, payload = GitHubClient(None, api_url, context).get('/rate_limit')
    result = {'api_url': api_url, 'reachable': status == 200,
              'error': None if status == 200 else describe_error(status, payload), 'tokens': []}
    if status != 200 and status != 0:
        result['reachable'] = True  # the server answered; only the request was refused
    if status == 0 and urllib.request.getproxies():
        # Compare with a direct connection to tell proxy problems from network problems
        direct = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context))
        try:
            direct.open(urllib.request.Request(api_url.rstrip('/') + '/rate_limit',
                                               headers={'User-Agent': 'gh-contrib-scraper-setup'}), timeout=15).close()
            result['direct_connection'] = 'works'
        except Exception as e:  # pylint: disable=W0718:broad-exception-caught
            result['direct_connection'] = f'fails: {getattr(e, "reason", e)}'
    for key, token in tokens.items():
        status, headers, payload = GitHubClient(token, api_url, context).get('/user')
        entry = {'owner_key': key, 'fingerprint': fingerprint(token), 'valid': status == 200}
        if status == 200:
            entry['login'] = payload.get('login')
            entry['scopes'] = headers.get('X-OAuth-Scopes')  # None for fine-grained tokens
            entry['token_kind'] = 'classic' if headers.get('X-OAuth-Scopes') is not None else 'fine-grained or app'
        else:
            entry['error'] = describe_error(status, payload)
            if headers.get('X-GitHub-SSO'):
                entry['sso'] = 'token needs SSO authorization for an organization'
        result['tokens'].append(entry)
    return result


def main() -> None:
    configure_stdout()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--root', help='Project root (default: search upwards from the current directory)')
    parser.add_argument('--api-url', default=DEFAULT_API_URL)
    parser.add_argument('--output-dir', default='output')
    parser.add_argument('--ca-bundle')
    parser.add_argument('--no-verify-ssl', action='store_true')
    parser.add_argument('--offline', action='store_true', help='Skip network checks')
    args = parser.parse_args()

    root = find_project_root(args.root)
    if not root:
        fail('Project root not found (a folder with src/main.py and run.sh); pass --root')
    env_path = os.path.join(root, '.env')
    env_file = read_env_file(env_path)
    settings = load_settings(root)
    tokens = parse_tokens(settings.get('GITHUB_TOKEN', ''))
    repositories = [r for r in settings.get('GITHUB_REPOSITORIES', '').split(',') if r.strip()]

    code, _ = run_quiet(['git', 'check-ignore', '-q', '.env'], root) if shutil.which('git') else (-1, '')
    result = {
        'project_root': root,
        'platform': {'system': platform.system(), 'release': platform.release(), 'python': sys.version.split()[0],
                     'ssh_session': bool(os.environ.get('SSH_CONNECTION')),
                     'wsl': 'microsoft' in platform.release().lower()},
        'run_script': 'run.ps1' if os.name == 'nt' else 'run.sh',
        'venv': venv_info(root),
        'env_file': {'exists': os.path.isfile(env_path), 'git_ignored': {0: True, 1: False}.get(code),
                     'keys': sorted(env_file),
                     # run.ps1 keeps quotes, run.sh strips them: flag keys whose value is quoted
                     'quoted_values': sorted(k for k, v in env_file.items() if v[:1] in '"\'' and v[-1:] == v[:1])},
        # Keys set both in the environment and .env with different values (.env wins in the run scripts)
        'overridden_by_env_file': sorted(k for k, v in env_file.items() if k in ORIGINAL_ENVIRON and ORIGINAL_ENVIRON[k] != v),
        'token': {'present': bool(tokens), 'source': '.env' if 'GITHUB_TOKEN' in env_file else
                  ('environment' if 'GITHUB_TOKEN' in ORIGINAL_ENVIRON else None),
                  'owners': sorted(tokens), 'fingerprints': {k: fingerprint(v) for k, v in tokens.items()}},
        'repositories': {'count': len(repositories), 'source': '.env' if 'GITHUB_REPOSITORIES' in env_file
                         else ('environment' if 'GITHUB_REPOSITORIES' in ORIGINAL_ENVIRON else None)},
        'branches': settings.get('GITHUB_BRANCHES') or None,
        'network': network_info(root, env_file, settings),
        'last_run': last_run(root, args.output_dir),
    }
    if not args.offline:
        result['api'] = check_api(settings, tokens, args.api_url, args)

    missing = []
    if not result['venv']['python'] or not result['venv'].get('dependencies_installed'):
        missing.append('venv')
    if not tokens:
        missing.append('token')
    if not repositories:
        missing.append('repositories')
    api = result.get('api')
    if api and not api['reachable']:
        missing.append('network')
    if api and tokens and not any(t['valid'] for t in api['tokens']):
        missing.append('valid_token')
    result['missing'] = missing
    result['ready'] = not missing
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
