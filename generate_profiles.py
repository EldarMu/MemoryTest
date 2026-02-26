#!/usr/bin/env python3
"""
H-MEM Build Pipeline

Downloads Futurama transcripts, then:

  Step 1: Fit a single TF-IDF + SVD embedding model on ALL character lines
          (global vocabulary ensures query vectors land in the same space as stored vectors)

  Step 2: For each character, bottom-up H-MEM construction:
    a. Embed all their transcript lines                     (Layer 4: Episodes)
    b. K-Means cluster episodes; LLM-summarize each cluster (Layer 3: Memory Traces)
    c. K-Means cluster traces; LLM-summarize each cluster  (Layer 2: Categories)
    d. LLM synthesizes all categories into one description  (Layer 1: Domain)

  Step 3: Save tree structure as JSON + vectors as .npz per character
          Save the fitted embedding model as embedding_model.pkl

The H-MEM files are loaded by app.py at startup.
Per-message retrieval traverses the hierarchy top-down.

Usage:
    export ANTHROPIC_API_KEY=sk-...
    python generate_profiles.py
    python generate_profiles.py --characters bender fry   # subset
    python generate_profiles.py --overwrite               # rebuild existing
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def main():
    parser = argparse.ArgumentParser(description="Build H-MEM structures from Futurama transcripts")
    parser.add_argument("--characters", nargs="+", help="Character IDs to build (default: all)")
    parser.add_argument("--overwrite", action="store_true", help="Rebuild even if files exist")
    parser.add_argument("--data-dir", default="data", help="Root data directory")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    hmem_dir = data_dir / "hmem"
    hmem_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("Futurama H-MEM Builder")
    print("=" * 60)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set.")
        sys.exit(1)

    import anthropic
    client = anthropic.Anthropic(api_key=api_key)

    from pipeline.characters import CHARACTERS
    from pipeline.fetch_transcripts import get_transcripts
    from pipeline.hmem.embed import EmbeddingModel
    from pipeline.hmem.build import build
    from pipeline.hmem.store import save, load

    # ── Step 1: Transcripts ───────────────────────────────────────────────
    print("\n[1/3] Fetching transcripts...")
    transcripts = get_transcripts(data_dir)
    total = sum(len(v) for v in transcripts.values())
    print(f"      {total:,} lines across {len(transcripts)} characters")

    target_chars = args.characters or list(CHARACTERS.keys())
    unknown = set(target_chars) - set(CHARACTERS.keys())
    if unknown:
        print(f"ERROR: Unknown character IDs: {unknown}")
        sys.exit(1)

    # ── Step 2: Fit embedding model on all corpus text ────────────────────
    # Fit on ALL lines so the vocabulary is global — queries will map
    # into the same vector space as any character's stored episode vectors.
    model_path = hmem_dir / "embedding_model.pkl"
    if model_path.exists() and not args.overwrite:
        print(f"\n[2/3] Loading existing embedding model from {model_path}")
        embedding_model = EmbeddingModel.load(model_path)
    else:
        print("\n[2/3] Fitting embedding model on full corpus...")
        all_lines = [line for lines in transcripts.values() for line in lines]
        print(f"      Fitting on {len(all_lines):,} lines total...")
        embedding_model = EmbeddingModel()
        embedding_model.fit(all_lines)
        embedding_model.save(model_path)
        print(f"      Saved to {model_path}")

    # ── Step 3: Build H-MEM per character ────────────────────────────────
    print(f"\n[3/3] Building H-MEM for: {', '.join(target_chars)}")
    built = []
    skipped = []

    for char_id in target_chars:
        meta = CHARACTERS[char_id]
        lines = transcripts.get(char_id, [])

        if not lines:
            print(f"\n  [{meta['display_name']}] SKIP -- no transcript lines found")
            skipped.append(char_id)
            continue

        if not args.overwrite and load(char_id, hmem_dir) is not None:
            print(f"\n  [{meta['display_name']}] already built (--overwrite to rebuild)")
            skipped.append(char_id)
            continue

        print(f"\n  [{meta['display_name']}]")
        try:
            hmem = build(
                character_id=char_id,
                display_name=meta["display_name"],
                lines=lines,
                client=client,
                embedding_model=embedding_model,
            )
            save(hmem, hmem_dir)
            built.append(char_id)
        except Exception as e:
            print(f"  ERROR building {char_id}: {e}")
            import traceback
            traceback.print_exc()

    print(f"\nSummary -- built: {built} | skipped: {skipped}")
    print(f"H-MEM files in: {hmem_dir}/")
    print("Start the app:   uvicorn app:app --reload --port 8000")


if __name__ == "__main__":
    main()
