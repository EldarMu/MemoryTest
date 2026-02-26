"""
Futurama H-MEM Chat Demo — FastAPI Backend

Per-message flow:
  1. User sends message to /api/chat
  2. Embed the query (sentence-transformers, local)
  3. Top-down H-MEM retrieval: Domain → relevant Categories → relevant Traces → relevant Episodes
  4. Build a focused system prompt from the retrieved nodes
  5. Stream Claude's response
  6. Also return the retrieval result so the frontend can visualize what was activated

Run:
    uvicorn app:app --reload --port 8000
"""

import json
import os
from pathlib import Path
from typing import AsyncIterator

import anthropic
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

app = FastAPI(title="Futurama H-MEM Demo")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ─────────────────────────────────────────────────────────────────────────────
# Startup: load H-MEM structures
# ─────────────────────────────────────────────────────────────────────────────

HMEM: dict = {}              # char_id → full H-MEM structure (with _vecs)
CHARACTERS: dict = {}        # char_id → metadata
EMBEDDING_MODEL = None       # shared EmbeddingModel (fitted on full corpus)


@app.on_event("startup")
async def startup():
    global HMEM, CHARACTERS, EMBEDDING_MODEL

    from pipeline.characters import CHARACTERS as CHAR_META
    CHARACTERS = CHAR_META

    hmem_dir = Path("data/hmem")

    # Load embedding model (needed for query embedding at retrieval time)
    model_path = hmem_dir / "embedding_model.pkl"
    if model_path.exists():
        from pipeline.hmem.embed import EmbeddingModel
        EMBEDDING_MODEL = EmbeddingModel.load(model_path)
        print(f"Loaded embedding model from {model_path}")
    else:
        print("WARNING: No embedding model found. Run: python generate_profiles.py")

    from pipeline.hmem.store import load_all
    HMEM = load_all(hmem_dir, list(CHAR_META.keys()))

    if not HMEM:
        print("WARNING: No H-MEM structures found in data/hmem/")
        print("         Run: python generate_profiles.py")
    else:
        print(f"Loaded H-MEM for: {list(HMEM.keys())}")
        for char_id, h in HMEM.items():
            s = h["stats"]
            print(f"  {char_id}: {s['n_episodes']} eps / {s['n_traces']} traces / {s['n_categories']} cats")


# ─────────────────────────────────────────────────────────────────────────────
# System prompt — built from retrieved memories, not a static template
# ─────────────────────────────────────────────────────────────────────────────

def build_system_prompt(char_meta: dict, retrieved: dict) -> str:
    name = char_meta["display_name"]
    short = char_meta["short_name"]
    role = char_meta["role"]

    lines = [
        f"You are {name} from the animated TV show Futurama.",
        f"Role: {role}",
        "",
        "The following is your memory, retrieved hierarchically for this conversation:",
        "",
        "── DOMAIN (core personality) ──",
        retrieved["domain"]["text"],
        "",
        "── RELEVANT CATEGORIES ──",
    ]
    for cat in retrieved["categories"]:
        lines.append(f"• {cat['text']}")

    lines += ["", "── RELEVANT MEMORY TRACES ──"]
    for tr in retrieved["traces"]:
        lines.append(f"• {tr['text']}")

    lines += ["", "── RETRIEVED EPISODES (grounding examples) ──"]
    for ep in retrieved["episodes"]:
        lines.append(f'"{ep["text"]}"')

    lines += [
        "",
        f"Stay fully in character as {short}. Never break character or refer to yourself as an AI.",
        f"Use {short}'s vocabulary, speech patterns, and worldview as revealed above.",
        "Responses should be conversational and appropriately concise.",
    ]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# API Models
# ─────────────────────────────────────────────────────────────────────────────

class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    character_id: str
    messages: list[Message]


# ─────────────────────────────────────────────────────────────────────────────
# API Routes
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/characters")
async def list_characters():
    """Character list. Flags which ones have H-MEM built."""
    result = []
    for char_id, meta in CHARACTERS.items():
        entry = dict(meta)
        entry["hmem_ready"] = char_id in HMEM
        if char_id in HMEM:
            entry["stats"] = HMEM[char_id]["stats"]
        result.append(entry)
    return result


@app.get("/api/hmem/{character_id}")
async def get_hmem_overview(character_id: str):
    """
    Return the full H-MEM tree structure (no vectors) for display in the UI.
    Shows all domains, categories, traces, and episode counts.
    """
    if character_id not in HMEM:
        raise HTTPException(
            status_code=404,
            detail=f"No H-MEM built for '{character_id}'. Run: python generate_profiles.py"
        )
    h = HMEM[character_id]
    return {
        "character_id": character_id,
        "display_name": h["display_name"],
        "stats": h["stats"],
        "domain": h["domain"]["text"],
        "categories": [
            {
                "index": i,
                "text": c["text"],
                "n_traces": len(c["trace_ptrs"]),
            }
            for i, c in enumerate(h["categories"])
        ],
        "memory_traces": [
            {
                "index": i,
                "text": t["text"],
                "n_episodes": len(t["episode_ptrs"]),
                "category_idx": next(
                    (ci for ci, c in enumerate(h["categories"]) if i in c["trace_ptrs"]),
                    None
                ),
            }
            for i, t in enumerate(h["memory_traces"])
        ],
    }


@app.post("/api/chat")
async def chat(request: ChatRequest):
    """
    Streaming chat endpoint.

    For each message:
      - retrieves relevant H-MEM nodes for the query
      - builds a focused system prompt from those nodes
      - streams Claude's response as SSE
      - emits a final 'retrieval' event with the activated nodes (for UI display)
    """
    char_id = request.character_id

    if char_id not in CHARACTERS:
        raise HTTPException(status_code=404, detail=f"Unknown character '{char_id}'")

    if char_id not in HMEM:
        raise HTTPException(
            status_code=422,
            detail=f"H-MEM not built for '{char_id}'. Run: python generate_profiles.py"
        )

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not set")

    char_meta = CHARACTERS[char_id]
    hmem = HMEM[char_id]

    # Extract the most recent user message for retrieval
    user_messages = [m for m in request.messages if m.role == "user"]
    query = user_messages[-1].content if user_messages else ""

    # Top-down H-MEM retrieval (pass the shared embedding model)
    from pipeline.hmem.retrieve import retrieve
    retrieved = retrieve(hmem, query, embedding_model=EMBEDDING_MODEL)

    # Build system prompt from retrieved memories
    system_prompt = build_system_prompt(char_meta, retrieved)

    client = anthropic.Anthropic(api_key=api_key)
    messages = [{"role": m.role, "content": m.content} for m in request.messages]

    async def generate() -> AsyncIterator[str]:
        # First: emit the retrieval event so the UI can update immediately
        yield f"data: {json.dumps({'type': 'retrieval', 'data': retrieved})}\n\n"

        # Then: stream the LLM response
        with client.messages.stream(
            model="claude-opus-4-5",
            max_tokens=1024,
            system=system_prompt,
            messages=messages,
        ) as stream:
            for text in stream.text_stream:
                yield f"data: {json.dumps({'type': 'text', 'text': text})}\n\n"

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ─────────────────────────────────────────────────────────────────────────────
# Static frontend
# ─────────────────────────────────────────────────────────────────────────────

static_dir = Path("static")
static_dir.mkdir(exist_ok=True)
app.mount("/", StaticFiles(directory="static", html=True), name="static")
