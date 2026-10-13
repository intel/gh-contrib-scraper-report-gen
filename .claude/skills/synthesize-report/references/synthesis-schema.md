<!-- Copyright (C) 2026 Intel Corporation -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# synthesis.json schema (version 1)

The model writes this file; `scripts/render.py` validates it and renders `synthesis.html`.
See `templates/synthesis.example.json` for a complete example.

| Field | Type | Required | Notes |
|---|---|---|---|
| `schema_version` | `1` | yes | |
| `title` | string | yes | e.g. `Work summary: September 2026` (month of the covered period). |
| `grouping` | `"repository"` \| `"theme"` | no (default `repository`) | With `repository`, each section `name` must be an exact repository name from the report and its items may only cite that repository's commits. |
| `summary` | string or list of strings | yes | 2-4 sentences total; one paragraph per list entry. |
| `sections` | list | yes | Rendered in the given order. |
| `sections[].name` | string | yes | Repository full name or theme name. |
| `sections[].description` | string | no | One sentence of context (e.g. the repository description, rephrased plainly). |
| `sections[].items` | list | yes | Bullet points, non-empty. |
| `items[].text` | string | yes | One accomplishment, supported by every cited commit. Inline `**bold**` and `` `code` `` are supported; everything else is escaped. |
| `items[].commits` | list of SHAs | yes* | Abbreviated (>= 7 chars) or full SHAs from the digest. Rendered as links. |
| `items[].links` | list of `{label, url}` | no | Extra http(s) links; the only citation form in `--no-report` mode. |
| `period` | string | no | Overrides the computed period (`metadata.since` – run date). |
| `notes` | string or list of strings | no | Closing remarks, rendered in italics. |
| `include_stats` | boolean | no (default `true`) | Statistics are computed by the renderer from the report, never written by the model. |
| `extra_stats` | list of `{label, value}` | no | Appended to the statistics list. |
| `labels` | object | no | Override fixed labels: `period`, `statistics`, `repositories`, `commits`, `lines`, `files` (for non-English reports). |
| `lang` | string | no (default `en`) | HTML `lang` attribute. |

\* Every item must cite at least one commit (or link in `--no-report` mode); the renderer fails otherwise.

## Renderer behaviour

- Exit 1 with a list of problems on validation errors: fix `synthesis.json` and re-run.
- Exit 3 when `synthesis.html` exists and `--force` is not given.
- Warns about report commits not cited by any item (largest first; `--all-uncited` lists all). Not
  every commit needs its own bullet, but each should be covered by some item unless deliberately left
  out (e.g. trivial merges or reverts).
- Warns about items citing more than 15 commits and commits cited in more than one item.
- `--template-dir DIR` renders with a custom copy of `templates/` (both `report.html` and `blocks.html`).
