"""
Transcript fetcher for Futurama corpus.

Downloads the futurama_scripts.txt corpus from GitHub (acalabrigo/futurama-corpus)
which contains Character: dialogue lines from 7 seasons + 4 movies.
Parses into per-character dialogue dicts and saves to data/raw_transcripts.json.
"""

import json
import re
import sys
from pathlib import Path
from collections import defaultdict

import httpx

CORPUS_URL = "https://raw.githubusercontent.com/acalabrigo/futurama-corpus/master/data/futurama_scripts.txt"

# Canonical character name normalization
CHARACTER_ALIASES = {
    "fry": "fry",
    "philip": "fry",
    "philip j. fry": "fry",
    "leela": "leela",
    "turanga leela": "leela",
    "bender": "bender",
    "bender bending rodriguez": "bender",
    "professor": "professor",
    "prof": "professor",
    "farnsworth": "professor",
    "professor farnsworth": "professor",
    "prof. farnsworth": "professor",
    "zoidberg": "zoidberg",
    "dr. zoidberg": "zoidberg",
    "dr zoidberg": "zoidberg",
    "amy": "amy",
    "amy wong": "amy",
    "hermes": "hermes",
    "hermes conrad": "hermes",
    "kif": "kif",
    "kif kroker": "kif",
    "zapp": "zapp",
    "zapp brannigan": "zapp",
}

MAIN_CHARACTERS = {
    "fry", "leela", "bender", "professor", "zoidberg", "amy", "hermes", "kif", "zapp"
}


def normalize_character(name: str) -> str | None:
    """Normalize character name to canonical ID, return None if not a main character."""
    cleaned = name.strip().rstrip(":").lower()
    return CHARACTER_ALIASES.get(cleaned)


def fetch_corpus(output_path: Path) -> str:
    """Download corpus from GitHub. Returns raw text."""
    print(f"Fetching Futurama corpus from {CORPUS_URL}...")
    with httpx.Client(follow_redirects=True, timeout=60) as client:
        resp = client.get(CORPUS_URL)
        resp.raise_for_status()
    text = resp.text
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text, encoding="utf-8")
    print(f"Saved corpus ({len(text):,} chars) to {output_path}")
    return text


def parse_corpus(text: str) -> dict[str, list[str]]:
    """
    Parse the corpus text into per-character dialogue lists.

    Expected format (approximately):
        Fry: Oh god, I'm so sick of being poor.
        Leela: Welcome to the future, Fry.
    """
    lines_by_character: dict[str, list[str]] = defaultdict(list)
    # Pattern: "CharacterName: dialogue text"
    line_pattern = re.compile(r"^([A-Za-z][A-Za-z\s\.\#\-']*?):\s+(.+)$")

    for raw_line in text.splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        m = line_pattern.match(raw_line)
        if not m:
            continue
        char_raw, dialogue = m.group(1), m.group(2).strip()
        char_id = normalize_character(char_raw)
        if char_id and char_id in MAIN_CHARACTERS:
            lines_by_character[char_id].append(dialogue)

    return dict(lines_by_character)


def get_transcripts(data_dir: Path = Path("data")) -> dict[str, list[str]]:
    """
    Load transcripts from cache or download and parse fresh.
    Returns dict: {character_id: [list of dialogue lines]}
    """
    raw_path = data_dir / "raw_corpus.txt"
    parsed_path = data_dir / "raw_transcripts.json"

    if parsed_path.exists():
        print(f"Loading cached transcripts from {parsed_path}")
        with open(parsed_path) as f:
            return json.load(f)

    # Download
    if raw_path.exists():
        print(f"Using cached raw corpus from {raw_path}")
        text = raw_path.read_text(encoding="utf-8")
    else:
        text = fetch_corpus(raw_path)

    # Parse
    print("Parsing corpus...")
    by_char = parse_corpus(text)

    # Save parsed
    parsed_path.parent.mkdir(parents=True, exist_ok=True)
    with open(parsed_path, "w") as f:
        json.dump(by_char, f, indent=2)

    # Print stats
    print("\nDialogue line counts:")
    for char, lines in sorted(by_char.items(), key=lambda x: -len(x[1])):
        print(f"  {char:15s}: {len(lines):4d} lines")

    return by_char


if __name__ == "__main__":
    transcripts = get_transcripts()
    total = sum(len(v) for v in transcripts.values())
    print(f"\nTotal lines across main characters: {total:,}")
