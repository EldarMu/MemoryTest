# Futurama Memory Demo

An AI chat interface demonstrating **H-MEM-style hierarchical memory personalization** using Futurama characters.

Based on the paper: **H-MEM: Hierarchical Memory for High-Efficiency Long-Term Reasoning in LLM Agents** ([arXiv:2507.22925](https://arxiv.org/abs/2507.22925))

---

## What this demos

Each Futurama character has a four-layer **H-MEM profile** extracted from real episode transcripts:

| Layer | Abstraction | Contents |
|-------|-------------|----------|
| **L1 Domain** | Most abstract | Core personality archetype |
| **L2 Categories** | Behavioral | Speech style, values, emotions, topics, relationships |
| **L3 Memory Traces** | Patterns | Catchphrases, recurring behaviors, habits |
| **L4 Episode Quotes** | Most concrete | Representative verbatim quotes with context |

This hierarchy mirrors H-MEM's `section → subsection → subsubsection → content` structure. When generating a chat response, all four layers are injected into Claude's system prompt — from the most abstract personality summary down to specific grounding quotes — giving the model a rich, structured understanding of who this character is.

The point of the demo is to let you *feel* what it's like when different memory structures shape conversation: Bender's responses carry his nihilistic bravado, the Professor's carry his cheerful doom-announcing senility, Zoidberg's carry his desperate need for belonging. Same underlying model, different memories → completely different experience.

---

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set your API key
export ANTHROPIC_API_KEY=your_key_here

# 3. (Optional but recommended) Run the full profile extraction pipeline
#    Downloads 13,667 lines of real Futurama transcripts and uses Claude to
#    extract H-MEM profiles for all 9 characters
python generate_profiles.py

#    If you skip this step, the app uses hand-crafted seed profiles automatically.

# 4. Start the app
uvicorn app:app --reload --port 8000

# 5. Open http://localhost:8000
```

---

## Profile Pipeline

```
GitHub corpus (acalabrigo/futurama-corpus)
        │  1.5MB, 7 seasons + 4 movies
        ▼
pipeline/fetch_transcripts.py
        │  parses "Character: dialogue" format
        │  extracts 13,667 lines across 9 characters
        ▼
pipeline/extract_profiles.py
        │  samples 400 lines per character
        │  calls Claude to extract structured H-MEM JSON
        ▼
data/profiles/{character}.json
        │  four-layer H-MEM profiles
        ▼
app.py  →  build_system_prompt()
        │  assembles L1→L4 into a structured system prompt
        ▼
Claude chat with full character personalization
```

---

## Characters

| Character | Lines in corpus |
|-----------|----------------|
| Fry | 3,466 |
| Bender | 2,917 |
| Leela | 2,783 |
| Professor Farnsworth | 1,478 |
| Amy Wong | 828 |
| Hermes Conrad | 791 |
| Dr. Zoidberg | 779 |
| Zapp Brannigan | 393 |
| Kif Kroker | 232 |

---

## Architecture

```
static/index.html          Single-page app
    ├── Character selector (top bar)
    ├── H-MEM Profile panel (left)  ← shows all 4 layers, collapsible
    └── Chat panel (right)          ← streaming responses

app.py                     FastAPI backend
    ├── GET  /api/characters        list of characters with metadata
    ├── GET  /api/profile/:id       full H-MEM profile JSON
    └── POST /api/chat              streaming chat (SSE)

pipeline/
    ├── characters.py               character metadata + seed H-MEM profiles
    ├── fetch_transcripts.py        download & parse Futurama corpus
    └── extract_profiles.py         Claude-powered H-MEM extraction

generate_profiles.py        CLI: run full extraction pipeline
```

---

## The Memory Architecture Point

This demo is a sandbox for experiencing different memory implementations. The H-MEM paper is one approach — hierarchical, index-based, efficient. But the profiles are intentionally decoupled from H-MEM specifically: the `h_mem` JSON structure in each profile is loaded by whatever `build_system_prompt()` produces, and you can swap in different memory representations (flat summaries, graph-based, retrieval-augmented) by changing that function and the profile extractor.

Future directions this codebase is designed to support:
- Swapping in different memory retrieval strategies (only load relevant categories/traces based on message content)
- Comparing how much each layer contributes to character fidelity
- Adding episodic memory that accumulates *during* the chat session
