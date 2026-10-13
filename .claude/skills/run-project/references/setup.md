<!-- Copyright (C) 2026 Intel Corporation -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Initial setup

Work through only the items preflight reports as missing, in this order. After each fix, re-run
`preflight.py`. Explain briefly what each step is for; new users may not know the project.

## 1. Python environment

Needed when `missing` contains `venv`. Python version per README.md "Introduction" (prerequisites). Install per README.md "Quick Installation" -- the run scripts create the venv and install
requirements (`./run.sh install` / `.\run.ps1 -Tasks install`). If pip fails with timeouts or SSL errors,
do the network step first.

## 2. Network: proxy and certificates

Always investigate on first setup, even if nothing failed: follow [network.md](network.md).

## 3. Token(s)

If `token.present` is false or a token is invalid:
- Point the user to README.md "Setting up GitHub Personal Access Token" (permissions, per-owner token map
  format, `.env`). Recommend fine-grained read-only tokens; one per organisation (resource owner) works well
  with the owner:token map.
- The user adds `GITHUB_TOKEN=...` to `.env` themselves (never via chat). Then re-run preflight and check
  `api.tokens[]`: `valid`, `login`, `sso`. An `sso` note means the token must be authorised for the
  organisation's single sign-on on GitHub's token settings page.
- Repositories the scraper can't access are logged at run time ("Failed to fetch repository ...").

## 4. Username

Use the request, conversation, or memory; otherwise suggest `api.tokens[].login` and confirm.

## 5. Repositories

If `repositories.count` is 0 (or the user wants to rediscover), run [discovery.md](discovery.md), let the
user confirm the list, then:
```
<py> "<skill>/scripts/envfile.py" set GITHUB_REPOSITORIES=<owner/repo,owner/repo,...>          # shows the diff
<py> "<skill>/scripts/envfile.py" set GITHUB_REPOSITORIES=<...> --apply                        # after confirmation
```

## 6. Memories

Offer the memories in [memories.md](memories.md) for what was learned, then continue with the run.
