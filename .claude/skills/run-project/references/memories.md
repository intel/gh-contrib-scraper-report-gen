<!-- Copyright (C) 2026 Intel Corporation -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Memories to offer

At the end of setup -- and after a run when something new was learned -- offer to save memories (one fact
each) with whatever persistent memory the session provides. Ask before saving; never store tokens or other
secrets, and keep them out of the project files.

| Memory | Example content |
|---|---|
| GitHub username | "GitHub username for contributions reports: octocat" |
| Platform and shell | "Runs the project on Windows 11, PowerShell; Python launcher `py -3`" |
| Network | "Needs proxy http://proxy.example.com:8080 (set in .env); CA bundle at <path>" or "no proxy needed" |
| Token setup | "One fine-grained token per org in .env (owners: example-org, other-org); SSO authorised" |
| Report cadence | "Generates the report monthly, since the previous run" |
| Run preferences | Only deviations from the skill defaults, e.g. "always pass --branches main,develop" |
| Output location | Non-default `--output` directory, if used |
| Follow-up | "Synthesize the report after each run" if the user always does |
