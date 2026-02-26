# Futurama H-MEM Demo

An AI chat interface demonstrating the **H-MEM hierarchical memory algorithm** applied to
Futurama character personalization.

Paper: **H-MEM: Hierarchical Memory for High-Efficiency Long-Term Reasoning in LLM Agents**
([arXiv:2507.22925](https://arxiv.org/abs/2507.22925))

---

## What this actually does

The H-MEM algorithm constructs memory hierarchically from raw observations (transcript lines)
and retrieves relevant memories top-down at query time. This repo implements that pipeline end-to-end.

### Build phase (bottom-up, run once)

```
Raw transcript lines (Episodes)
          │
          │  TF-IDF + SVD embedding (local, no API)
          ▼
Layer 4 — Episodes: each line embedded as a 256-d vector
          │
          │  K-Means clustering (~25 lines per cluster)
          │  + LLM (Claude Haiku) summarizes each cluster
          ▼
Layer 3 — Memory Traces: each cluster is one behavioral pattern
          │
          │  K-Means clustering (~8 traces per cluster)
          │  + LLM summarizes each cluster of patterns
          ▼
Layer 2 — Categories: higher-level behavioral categories
          │
          │  LLM synthesizes all categories
          ▼
Layer 1 — Domain: single core personality description
```

Each node stores its **text** and **index pointers into the level below** (the positional
index encoding from H-MEM). This is what enables top-down retrieval without exhaustive search.

### Retrieval phase (per message, top-down)

```
User query
    │  embed query
    ▼
Search all Categories  →  take top-k
    │  follow ptr lists downward
    ▼
Search Traces in selected Categories  →  take top-k
    │  follow ptr lists downward
    ▼
Search Episodes in selected Traces  →  take top-k
    │
    ▼
Build system prompt from:
    Domain (always) + retrieved Categories + Traces + Episodes
    │
    ▼
Claude generates character response
```

The search space shrinks at each level. For Fry (3,466 lines / 139 traces / 17 cats):
a query about "pizza" searches 17 categories, then ~50 candidate traces, then ~200 candidate
episodes — rather than all 3,466. The retrieved set is what actually conditions the response.

---

## Quick start

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-...

# Build H-MEM structures from Futurama transcripts
python generate_profiles.py

# Start the app
uvicorn app:app --reload --port 8000
# open http://localhost:8000
```

The pipeline downloads the Futurama corpus from GitHub (~1.5MB, 7 seasons),
fits the embedding model on all 13,667 lines, then builds each character's
H-MEM structure. Expect ~5 min for all 9 characters.

To build a subset first:
```bash
python generate_profiles.py --characters bender fry
```

---

## Corpus stats

| Character | Lines | Memory Traces | Categories |
|-----------|-------|---------------|------------|
| Fry | 3,466 | ~139 | ~17 |
| Bender | 2,917 | ~117 | ~15 |
| Leela | 2,783 | ~111 | ~14 |
| Professor | 1,478 | ~59 | ~7 |
| Amy | 828 | ~33 | ~4 |
| Hermes | 791 | ~32 | ~4 |
| Zoidberg | 779 | ~31 | ~4 |
| Zapp | 393 | ~16 | ~2 |
| Kif | 232 | ~9 | ~2 |

---

## Architecture

```
pipeline/
  fetch_transcripts.py     Download + parse Futurama corpus (Character: dialogue format)
  hmem/
    embed.py               TF-IDF + TruncatedSVD embedder (fit once, transform many)
    build.py               Bottom-up H-MEM construction (the actual algorithm)
    retrieve.py            Top-down retrieval given a query
    store.py               JSON (structure) + .npz (vectors) serialization

generate_profiles.py       CLI: fit embedding model + build H-MEM for all characters

app.py                     FastAPI: loads H-MEM at startup, does retrieval per message,
                           exposes retrieved nodes to frontend via SSE

static/index.html          Single-page UI: character selector, H-MEM structure panel
                           (highlights which nodes were retrieved), streaming chat
```

---

## What the UI shows

The left panel shows the full H-MEM tree for the selected character.
After each message, the nodes that were **actually retrieved** for that specific
query are highlighted — so you can see the memory retrieval in action:

- **L1 Domain** — always shown (core personality)
- **L2 Categories** — highlighted ones were in the top-k for this query
- **L3 Memory Traces** — highlighted ones were reachable via selected categories + highest similarity
- **L4 Episodes** — the actual transcript lines that grounded the response, with similarity scores

This makes the memory mechanism transparent: same character, different questions, different
memory paths activated, shaping the response differently.

---

## Extending this

The H-MEM structure is pluggable. `build_system_prompt()` in `app.py` constructs the
system prompt from whatever `retrieve()` returns. To try a different memory architecture:
replace `retrieve.py` with a different retrieval strategy and the rest stays the same.
