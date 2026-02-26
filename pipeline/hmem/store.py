"""
H-MEM Serialization
====================

Saves/loads H-MEM structures to disk.

Layout:
  data/hmem/{character_id}.json   — tree structure (text + ptr lists), stats
  data/hmem/{character_id}.npz    — all vectors (domain, categories, traces, episodes)

Vectors are kept out of JSON because episode vectors alone are N×384 float32,
which would make JSON files enormous. numpy .npz is compact and fast.
"""

from __future__ import annotations

import json
from pathlib import Path
import numpy as np


def save(hmem: dict, output_dir: Path) -> None:
    """Serialize an H-MEM structure to disk."""
    output_dir.mkdir(parents=True, exist_ok=True)
    char_id = hmem["character_id"]

    # ── JSON: tree structure (no vectors) ────────────────────────────────
    tree = {
        "character_id": hmem["character_id"],
        "display_name": hmem["display_name"],
        "domain": hmem["domain"],
        "categories": hmem["categories"],
        "memory_traces": hmem["memory_traces"],
        "episodes": hmem["episodes"],
        "stats": hmem["stats"],
    }
    json_path = output_dir / f"{char_id}.json"
    with open(json_path, "w") as f:
        json.dump(tree, f, indent=2)

    # ── NPZ: all vectors ──────────────────────────────────────────────────
    vecs = hmem["_vecs"]
    npz_path = output_dir / f"{char_id}.npz"
    np.savez_compressed(
        npz_path,
        domain=vecs["domain"],
        categories=vecs["categories"],
        memory_traces=vecs["memory_traces"],
        episodes=vecs["episodes"],
    )

    n_eps = hmem["stats"]["n_episodes"]
    n_tr  = hmem["stats"]["n_traces"]
    n_cat = hmem["stats"]["n_categories"]
    print(f"    Saved: {json_path.name} + {npz_path.name}  "
          f"({n_eps} eps / {n_tr} traces / {n_cat} cats)")


def load(char_id: str, data_dir: Path) -> dict | None:
    """
    Load a saved H-MEM structure. Returns None if files don't exist.
    The returned dict has an '_vecs' key with numpy arrays, same as build() output.
    """
    json_path = data_dir / f"{char_id}.json"
    npz_path  = data_dir / f"{char_id}.npz"

    if not json_path.exists() or not npz_path.exists():
        return None

    with open(json_path) as f:
        tree = json.load(f)

    npz = np.load(npz_path)
    tree["_vecs"] = {
        "domain":        npz["domain"],
        "categories":    npz["categories"],
        "memory_traces": npz["memory_traces"],
        "episodes":      npz["episodes"],
    }
    return tree


def load_all(data_dir: Path, character_ids: list[str]) -> dict[str, dict]:
    """Load all available H-MEM structures. Returns only the ones that exist."""
    result = {}
    for char_id in character_ids:
        hmem = load(char_id, data_dir)
        if hmem is not None:
            result[char_id] = hmem
    return result
