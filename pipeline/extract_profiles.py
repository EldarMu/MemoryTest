"""
H-MEM-inspired profile extractor.

Takes per-character dialogue lines and uses Claude to produce a structured
four-layer Hierarchical Memory profile:

  Domain Layer     - Core personality archetype (most abstract)
  Category Layer   - Behavioral categories (speech, values, emotions, topics, relationships)
  Memory Trace Layer - Recurring patterns, catchphrases, habits
  Episode Layer    - Representative verbatim quotes with context

This mirrors the H-MEM paper (arXiv:2507.22925) structure of:
  section → subsection → subsubsection → content

The hierarchy lets a consumer start from broad understanding and
drill down to specifics, and each level includes index pointers to
sub-levels — implemented here as JSON nesting.
"""

import json
import os
import random
from pathlib import Path
from typing import Any

import anthropic

from pipeline.characters import CHARACTERS

# How many lines to sample per character for Claude analysis
SAMPLE_SIZE = 400


EXTRACTION_PROMPT = """You are analyzing dialogue from the animated TV show Futurama to build a character memory profile.

Character: {display_name}
Role: {role}

Here are {n} lines of dialogue spoken by this character across multiple episodes:

---
{dialogue_sample}
---

Create a structured Hierarchical Memory (H-MEM) profile with exactly these four layers. Be specific and grounded in the actual dialogue above.

Return ONLY valid JSON with this exact structure:

{{
  "domain": {{
    "title": "Core Personality",
    "content": "A 2-3 sentence description of this character's essential nature, worldview, and defining trait. This is the most abstract summary — who ARE they fundamentally?"
  }},
  "categories": [
    {{
      "name": "Speech Style",
      "description": "How they talk: vocabulary level, sentence length, recurring verbal tics, formality, accent/dialect markers, unique expressions"
    }},
    {{
      "name": "Core Values",
      "description": "What they care about, prioritize, and defend. What motivates their actions?"
    }},
    {{
      "name": "Emotional Tendencies",
      "description": "How they express and manage emotions. Default emotional register. What triggers strong reactions?"
    }},
    {{
      "name": "Typical Topics",
      "description": "Subject areas they frequently talk about, obsess over, or return to"
    }},
    {{
      "name": "Relationships",
      "description": "How they relate to the crew and others. Their social role and typical dynamic with other characters"
    }}
  ],
  "memory_traces": [
    "Specific recurring behavioral pattern or catchphrase #1",
    "Specific recurring behavioral pattern or catchphrase #2",
    "Specific recurring behavioral pattern or catchphrase #3",
    "Specific recurring behavioral pattern or catchphrase #4",
    "Specific recurring behavioral pattern or catchphrase #5",
    "Specific recurring behavioral pattern or catchphrase #6"
  ],
  "episode_quotes": [
    {{"quote": "Exact or near-exact quote from the dialogue above", "context": "brief note on what it reveals"}},
    {{"quote": "Another characteristic quote", "context": "what it reveals"}},
    {{"quote": "Another characteristic quote", "context": "what it reveals"}},
    {{"quote": "Another characteristic quote", "context": "what it reveals"}},
    {{"quote": "Another characteristic quote", "context": "what it reveals"}}
  ]
}}"""


def extract_profile(
    character_id: str,
    lines: list[str],
    client: anthropic.Anthropic,
    sample_size: int = SAMPLE_SIZE,
) -> dict[str, Any]:
    """Use Claude to extract an H-MEM profile from character dialogue."""
    char_meta = CHARACTERS[character_id]

    # Sample dialogue lines
    sample = random.sample(lines, min(sample_size, len(lines)))
    dialogue_sample = "\n".join(f"- {line}" for line in sample)

    prompt = EXTRACTION_PROMPT.format(
        display_name=char_meta["display_name"],
        role=char_meta["role"],
        n=len(sample),
        dialogue_sample=dialogue_sample,
    )

    print(f"  Extracting profile for {char_meta['display_name']} ({len(lines)} lines, sampling {len(sample)})...")
    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )

    # Parse JSON from response
    raw = message.content[0].text.strip()
    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    h_mem = json.loads(raw.strip())
    return h_mem


def generate_all_profiles(
    transcripts: dict[str, list[str]],
    output_dir: Path = Path("data/profiles"),
    overwrite: bool = False,
) -> dict[str, dict]:
    """
    Generate H-MEM profiles for all characters that have transcript data.
    Saves each profile to output_dir/{character_id}.json
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    profiles = {}

    for char_id, char_meta in CHARACTERS.items():
        out_path = output_dir / f"{char_id}.json"

        if out_path.exists() and not overwrite:
            print(f"  {char_id}: profile exists, skipping (use --overwrite to regenerate)")
            with open(out_path) as f:
                profiles[char_id] = json.load(f)
            continue

        lines = transcripts.get(char_id, [])
        if not lines:
            print(f"  {char_id}: no transcript lines found, using seed profile")
            profile = build_seed_profile(char_id)
        else:
            try:
                h_mem = extract_profile(char_id, lines, client)
                profile = {
                    **char_meta,
                    "h_mem": h_mem,
                    "transcript_line_count": len(lines),
                    "profile_source": "transcript_extraction",
                }
            except Exception as e:
                print(f"  {char_id}: extraction failed ({e}), using seed profile")
                profile = build_seed_profile(char_id)

        with open(out_path, "w") as f:
            json.dump(profile, f, indent=2)
        print(f"  {char_id}: saved to {out_path}")
        profiles[char_id] = profile

    return profiles


def build_seed_profile(char_id: str) -> dict[str, Any]:
    """Return a profile built from the hardcoded seed data in characters.py."""
    from pipeline.characters import CHARACTERS, SEED_H_MEM
    meta = CHARACTERS[char_id]
    return {
        **meta,
        "h_mem": SEED_H_MEM[char_id],
        "transcript_line_count": 0,
        "profile_source": "seed",
    }


def load_profiles(profiles_dir: Path = Path("data/profiles")) -> dict[str, dict]:
    """Load all saved profiles from disk. Falls back to seed profiles."""
    from pipeline.characters import CHARACTERS
    profiles = {}
    for char_id in CHARACTERS:
        path = profiles_dir / f"{char_id}.json"
        if path.exists():
            with open(path) as f:
                profiles[char_id] = json.load(f)
        else:
            profiles[char_id] = build_seed_profile(char_id)
    return profiles
