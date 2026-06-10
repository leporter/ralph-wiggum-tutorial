"""Resolve Vite-built asset paths from the production manifest.

In development the template loads modules straight from the Vite dev server. In
production Vite emits *hashed* filenames (``assets/main-a1b2c3.js``) plus a
``manifest.json`` mapping each source entry to its built output. The previous
template hard-coded ``assets/main.js`` / ``assets/main.css``, which never exist
after a hashed build — so production pages loaded no JS or CSS at all.

This helper reads the manifest (Vite 5 writes it to ``.vite/manifest.json``;
older layouts use ``manifest.json``) and resolves the ``src/main.ts`` entry to
its hashed JS file and associated CSS. Results are cached per process since the
manifest is immutable for a given build. If the manifest is missing (e.g. the
frontend hasn't been built yet) we fall back to the legacy unhashed names so
the page still renders rather than 500-ing.
"""
from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from typing import NamedTuple

logger = logging.getLogger(__name__)

ENTRY = 'src/main.ts'


class ViteAssets(NamedTuple):
    js: str
    css: list[str]


def _manifest_path(static_folder: str) -> str | None:
    for candidate in (
        os.path.join(static_folder, '.vite', 'manifest.json'),
        os.path.join(static_folder, 'manifest.json'),
    ):
        if os.path.isfile(candidate):
            return candidate
    return None


@lru_cache(maxsize=8)
def load_vite_assets(static_folder: str) -> ViteAssets:
    """Resolve the entry's hashed JS + CSS from the build manifest.

    Falls back to legacy unhashed names when no manifest is present.
    """
    path = _manifest_path(static_folder)
    if path is None:
        logger.warning('Vite manifest not found under %s; using fallback names', static_folder)
        return ViteAssets(js='assets/main.js', css=['assets/main.css'])

    with open(path, encoding='utf-8') as handle:
        manifest = json.load(handle)

    entry = manifest.get(ENTRY) or {}
    js = entry.get('file', 'assets/main.js')
    css = list(entry.get('css', []))
    return ViteAssets(js=js, css=css)
