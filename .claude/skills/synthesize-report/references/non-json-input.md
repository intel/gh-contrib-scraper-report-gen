<!-- Copyright (C) 2026 Intel Corporation -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Input without report.json

Only after the user agreed to proceed (SKILL.md step 1).

1. Do not use `digest.py` or `diffs.py` -- they only understand `report.json`.
2. Inspect a small sample of the file to learn its structure. Known layouts from this scraper:
   - `report.txt`: `- owner/repo` header lines, an optional tab-indented JSON-quoted description, then
     per commit tab-indented `key: <json value>` lines (`date`, `url`, `message`, ...), commits
     separated by blank lines.
   - `report.md`: `## owner/repo` headings, an optional description paragraph, then one fenced
     ```json``` block per commit.
3. Build a compact digest with an ad-hoc stdlib Python script. To stay safe across Windows and Linux
   shells, write it to a throwaway file in a scratch directory (e.g. the system temp dir; never the run
   or skill folder) and
   run `<py> <file> "<run_dir>"`; avoid `python -c "..."` one-liners and bash-only pipelines. Open
   files with `encoding='utf-8'` and print only what synthesis needs (repo, short SHA, date, subject,
   stats).
4. Write `synthesis.json` as usual, but cite sources with `items[].links`
   (`{"label": "<short sha>", "url": "<commit url>"}`) instead of `items[].commits`, and provide any
   statistics via `extra_stats` computed by your script (never estimated; they are the only statistics
   rendered in this mode). Section names are not checked against a report in this mode, so copy
   repository names exactly; the same commit may appear under several repositories (forks).
5. Render with `--no-report`:
   ```
   <py> "<skill>/scripts/render.py" "<run_dir>" --no-report
   ```
   The template and clipboard steps stay the same.

Tip for the user: running the scraper with `--report-formats json` (and commit fields
`date url message sha stats files_changed`) gives the best results.
