#!/usr/bin/env python3
"""
Profile Generation Pipeline

Run this script once to:
  1. Download the Futurama transcript corpus from GitHub
  2. Parse per-character dialogue lines
  3. Use Claude to extract H-MEM profiles for each character
  4. Save profiles to data/profiles/

Usage:
    python generate_profiles.py
    python generate_profiles.py --overwrite   # Regenerate existing profiles
    python generate_profiles.py --seed-only   # Skip transcript download, use seed profiles

The generated profiles are then loaded by the chat app (app.py).
If profiles don't exist when the app starts, it falls back to seed profiles automatically.
"""

import argparse
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))


def main():
    parser = argparse.ArgumentParser(description="Generate Futurama character H-MEM profiles")
    parser.add_argument("--overwrite", action="store_true", help="Regenerate existing profiles")
    parser.add_argument("--seed-only", action="store_true", help="Write seed profiles without transcript extraction")
    parser.add_argument("--data-dir", default="data", help="Data directory (default: data/)")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    profiles_dir = data_dir / "profiles"

    print("=" * 60)
    print("Futurama H-MEM Profile Generator")
    print("=" * 60)

    if args.seed_only:
        print("\nWriting seed profiles (no transcript extraction)...")
        from pipeline.extract_profiles import build_seed_profile
        from pipeline.characters import CHARACTERS
        import json

        profiles_dir.mkdir(parents=True, exist_ok=True)
        for char_id in CHARACTERS:
            out_path = profiles_dir / f"{char_id}.json"
            if out_path.exists() and not args.overwrite:
                print(f"  {char_id}: already exists, skipping")
                continue
            profile = build_seed_profile(char_id)
            with open(out_path, "w") as f:
                json.dump(profile, f, indent=2)
            print(f"  {char_id}: seed profile written to {out_path}")
        print("\nDone! Seed profiles ready.")
        return

    # Full pipeline: download + extract
    print("\nStep 1: Fetching transcripts...")
    from pipeline.fetch_transcripts import get_transcripts
    transcripts = get_transcripts(data_dir)

    if not transcripts:
        print("WARNING: No transcript data found. Falling back to seed profiles.")
        args.seed_only = True

    print(f"\nStep 2: Extracting H-MEM profiles using Claude...")
    print("(This requires ANTHROPIC_API_KEY to be set)")
    from pipeline.extract_profiles import generate_all_profiles
    profiles = generate_all_profiles(
        transcripts=transcripts,
        output_dir=profiles_dir,
        overwrite=args.overwrite,
    )

    print(f"\nDone! Generated {len(profiles)} character profiles in {profiles_dir}/")
    print("\nCharacters available:")
    for char_id, profile in profiles.items():
        source = profile.get("profile_source", "unknown")
        lines = profile.get("transcript_line_count", 0)
        print(f"  {char_id:15s} ({source}, {lines} transcript lines)")

    print("\nStart the app with: uvicorn app:app --reload")


if __name__ == "__main__":
    main()
