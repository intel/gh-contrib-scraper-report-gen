<!-- Copyright (C) 2026 Intel Corporation -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Grouping by theme

Use only when the user asks for it (e.g. "group by theme/topic/workstream"). Set `"grouping": "theme"`.

1. Read the whole digest first, then define 2-6 themes describing *what* the work was for
   (e.g. "Release automation", "Data validation", "Developer documentation"), not *how*
   (avoid themes like "Refactoring" or "Fixes" unless the user asks for change-type grouping).
2. Themes may span repositories. Name the repository inside the item text when it adds clarity,
   e.g. "Added retry logic to the upload client (example-service)".
3. A commit may be cited in more than one theme only if it genuinely contributes to both.
4. No catch-all themes. Only small, genuinely minor leftovers go into a final "Maintenance" theme,
   each checked by hand; anything substantial gets a proper theme or item.
5. Order themes by significance (most substantial first).
6. If the user provides theme names or a mapping (repository or keyword -> theme), follow it exactly.
