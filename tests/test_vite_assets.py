"""Tests for production Vite asset resolution from the manifest.

Why this matters: hashed production builds emit names like ``main-a1b2c3.js``
and record them in ``manifest.json``. The template previously hard-coded
``assets/main.js``/``.css``, so production pages silently shipped no JS/CSS.
These tests pin that the resolver reads the manifest entry for ``src/main.ts``
and returns the hashed JS + CSS, and that it degrades gracefully when the
manifest is absent (frontend not yet built).
"""
from __future__ import annotations

import json
import os

from app.vite_manifest import ViteAssets, load_vite_assets


def _write_manifest(static_dir: str) -> None:
    vite_dir = os.path.join(static_dir, '.vite')
    os.makedirs(vite_dir, exist_ok=True)
    with open(os.path.join(vite_dir, 'manifest.json'), 'w', encoding='utf-8') as fh:
        json.dump({
            'src/main.ts': {
                'file': 'assets/main-abc123.js',
                'css': ['assets/main-def456.css'],
                'isEntry': True,
            },
        }, fh)


def test_resolves_hashed_assets(tmp_path: object) -> None:
    load_vite_assets.cache_clear()
    static_dir = str(tmp_path)
    _write_manifest(static_dir)
    assets = load_vite_assets(static_dir)
    assert assets == ViteAssets(js='assets/main-abc123.js', css=['assets/main-def456.css'])


def test_falls_back_without_manifest(tmp_path: object) -> None:
    load_vite_assets.cache_clear()
    assets = load_vite_assets(str(tmp_path))
    assert assets.js == 'assets/main.js'
    assert assets.css == ['assets/main.css']
