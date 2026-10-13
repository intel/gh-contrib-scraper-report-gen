<!-- Copyright (C) 2026 Intel Corporation -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Discovering repositories

The scraper needs an explicit repository list (README.md "Known limitations"). Discovery proposes one.

```
<py> "<skill>/scripts/discover.py" <username> --since <YYYY-MM-DD> [--extra-repos <existing,list>]
```

Use a wide enough window (e.g. the last 3-6 months) so occasional repositories show up. Pass the current
`GITHUB_REPOSITORIES` (and the last run's repositories, if any) via `--extra-repos` so they are re-checked
rather than silently dropped. It runs sequentially and may take a minute or more.

Sources, merged per token (see the script's docstring): GitHub contribution data (GraphQL), PR search,
commit search fallback, and -- for narrowly scoped tokens -- the token's recently pushed repositories. Each
candidate is checked with the same author query the scraper uses.

## Presenting results

Show a table from `repositories[]`: `name`, `verified`, `sources`, `latest_commit`, `default_branch`,
`pr_base_branches`, and `fork`/`archived`/`verify_error` where present (optional fields). Then:
- `verified: true` -> propose including.
- `verified: "pr_activity_only"` -> PRs but no default-branch commits in the window; include if the user
  expects work there (`--fetch-pr-commits` collects PR commits).
- `verified: null` + `verify_error` -> not accessible with the current tokens; mention it.
- `verified: false` -> no commits found; include only if the user insists.
- `pr_base_branches` -> PRs targeting non-default branches; PR commits there are collected only if those
  branches are passed via `--branches` (which then must also list the default branch names). Mention it,
  but keep the default (no branches) unless the user wants them.

Always state the blind spots: `restricted_contributions` (contributions hidden from the token), every entry
in `warnings`, and that work only on non-default branches without PRs, or commits made with an email not
linked to the GitHub account, can't be discovered. Ask the user to add any repositories they know are
missing, then persist the confirmed list (setup step 5).
