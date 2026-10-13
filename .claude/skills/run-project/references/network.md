<!-- Copyright (C) 2026 Intel Corporation -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Network: proxy and certificates

Background: README.md "Network Configuration" and "SSL Certificate Issues"; the run scripts load `.env`
after the caller's environment, so `.env` values win (see `import_env_vars` in `run.sh`, `Import-EnvVars`
in `run.ps1`; CA handling in `src/modules/api.py`). The skill scripts resolve settings the same way.

## Investigate

From preflight `network` and `api`:
- `effective_proxies`: what Python uses -- proxy variables, or on Windows the manually configured system
  proxy when no variable is set. Note where each comes from: `proxy_keys_in_env_file`,
  `proxy_keys_in_environment`, `git_http_proxy`. Automatic (PAC) proxy configuration is not resolved: ask
  the user for the resulting proxy host and port.
- `proxy_conflicts`: upper- and lower-case variables with different values -- tools disagree on which wins.
  Ask the user which proxy is correct and persist that one consistently.
- `overridden_by_env_file`: environment values that `.env` replaces in the run scripts.
- `api.reachable` / `api.error`, and `direct_connection` (tried only when a proxy is configured):
  - unreachable with proxy, direct works -> proxy wrong or not needed for this host (`NO_PROXY`).
  - unreachable both ways -> a proxy is probably required: ask the user for it (their IT documentation,
    browser/system settings, or the `git_http_proxy` value).
  - SSL/certificate errors -> a corporate CA is likely intercepting TLS: set `REQUESTS_CA_BUNDLE` (or pass
    `--ca-bundle`) per README.md "SSL Certificate Issues". Never default to `--no-verify-ssl`.
- `ca_bundle.exists` false -> the configured path is wrong.

Retest after each change: `<py> "<skill>/scripts/preflight.py"` (temporarily try values by setting them in
the command's environment before writing them).

## Confirm and persist

Show the user the proxy/CA values you found or tested and ask them to confirm, including "no proxy
needed". Then, with confirmation, persist them in `.env` with `envfile.py set HTTPS_PROXY=... HTTP_PROXY=...
NO_PROXY=...` (diff first, then `--apply`). Credentials embedded in a proxy URL are secrets: let the user
add those themselves. Finally offer a memory of the confirmed network setup (see [memories.md](memories.md)).
