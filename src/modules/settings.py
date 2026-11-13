# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

"""Reads the project's environment variables, falling back to their legacy names."""

import logging
import os

log = logging.getLogger(__name__)

# Current name -> legacy name. The legacy GITHUB_* names collide with variables that
# GitHub tooling (gh, Actions, other CLIs) reads, so they are deprecated.
LEGACY_NAMES = {
    'GHCS_TOKEN': 'GITHUB_TOKEN',
    'GHCS_REPOSITORIES': 'GITHUB_REPOSITORIES',
    'GHCS_BRANCHES': 'GITHUB_BRANCHES',
}

_warned: set[str] = set()


def get_env(name: str, default: str = '') -> str:
    """Return the value of `name`, or of its legacy name (with a one-time deprecation warning)."""
    value = os.environ.get(name)
    if value:
        return value
    legacy = LEGACY_NAMES.get(name)
    value = os.environ.get(legacy) if legacy else None
    if value:
        if legacy not in _warned:
            _warned.add(legacy)
            log.warning('Environment variable %s is deprecated; rename it to %s', legacy, name)
        return value
    return default
