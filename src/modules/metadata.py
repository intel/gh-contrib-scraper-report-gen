# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

"""Handles saving metadata about the scraping process."""

from datetime import datetime
import json
import logging
import os

log = logging.getLogger(__name__)


def save_metadata(output_path: str, username: str, repo_full_names: list[str], since: datetime) -> None:
    """Save basic metadata about the query to a JSON file.

    Args:
        output_path: Existing path to save the metadata file
        username: GitHub username scanned
        repo_full_names: List of repository names
        since: Date representing the earliest commit/PR
    """
    os.makedirs(output_path, exist_ok=True)
    metadata_path = os.path.join(output_path, 'metadata.json')
    data = {
        'username': username,
        'repositories': repo_full_names,
        'since': since.isoformat(),
    }
    try:
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)
        log.info('Saved metadata to %s', metadata_path)
    except Exception as e:  # pylint: disable=W0718:broad-exception-caught
        log.error('Failed to save metadata: %s', str(e))
