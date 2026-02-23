"""
Futurama Personalization Demo — FastAPI Backend

Demonstrates H-MEM (Hierarchical Memory) inspired personalization:
  - Four-layer character memory profiles (Domain → Category → Trace → Episode)
  - Profiles extracted from Futurama transcripts via pipeline/
  - Streaming chat endpoint with character-specific system prompts
  - Memory profile served alongside chat so users can see what's shaping responses

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

app = FastAPI(title="Futurama Memory Demo")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────────────────────────────────────
# Profile loading
# ─────────────────────────────────────────────────────────────────────────────

def load_all_profiles() -> dict:
    """Load profiles from disk; fall back to seed profiles if not generated yet."""
    from pipeline.extract_profiles import load_profiles
    profiles_dir = Path("data/profiles")
    profiles = load_profiles(profiles_dir)
    return profiles


PROFILES: dict = {}


@app.on_event("startup")
async def startup():
    global PROFILES
    PROFILES = load_all_profiles()
    print(f"Loaded {len(PROFILES)} character profiles")
    for char_id, p in PROFILES.items():
        source = p.get("profile_source", "unknown")
        print(f"  {char_id}: {source}")


# ─────────────────────────────────────────────────────────────────────────────
# H-MEM system prompt builder
# ─────────────────────────────────────────────────────────────────────────────

def build_system_prompt(profile: dict) -> str:
    """
    Construct a system prompt from the H-MEM profile layers.

    The prompt is structured hierarchically — Domain first (most abstract),
    then Categories, then Memory Traces, then Episode Quotes — mirroring
    the H-MEM paper's retrieval order from abstract to specific.
    """
    h = profile["h_mem"]
    name = profile["display_name"]
    short = profile["short_name"]
    role = profile["role"]

    lines = [
        f"You are {name} from the animated TV show Futurama.",
        f"Role: {role}",
        "",
        "═══════════════════════════════════════",
        "LAYER 1 — DOMAIN (Core Personality)",
        "═══════════════════════════════════════",
        h["domain"]["content"],
        "",
        "═══════════════════════════════════════",
        "LAYER 2 — CATEGORIES (Behavioral Profile)",
        "═══════════════════════════════════════",
    ]

    for cat in h["categories"]:
        lines.append(f"[{cat['name']}]")
        lines.append(cat["description"])
        lines.append("")

    lines += [
        "═══════════════════════════════════════",
        "LAYER 3 — MEMORY TRACES (Recurring Patterns)",
        "═══════════════════════════════════════",
    ]
    for trace in h["memory_traces"]:
        lines.append(f"• {trace}")

    lines += [
        "",
        "═══════════════════════════════════════",
        "LAYER 4 — EPISODE QUOTES (Grounding Examples)",
        "═══════════════════════════════════════",
    ]
    for eq in h["episode_quotes"]:
        lines.append(f'"{eq["quote"]}" — {eq["context"]}')

    lines += [
        "",
        "═══════════════════════════════════════",
        "INSTRUCTIONS",
        "═══════════════════════════════════════",
        f"Stay fully in character as {short} at all times.",
        "Respond as {short} would in the show — use their vocabulary, speech patterns, and worldview.".replace("{short}", short),
        "Keep responses conversational and appropriately concise.",
        "Never break character. Never refer to yourself as an AI.",
        "You are not playing a role — you ARE this character.",
    ]

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# API Models
# ─────────────────────────────────────────────────────────────────────────────

class Message(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    character_id: str
    messages: list[Message]


# ─────────────────────────────────────────────────────────────────────────────
# API Routes
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/characters")
async def list_characters():
    """Return all character metadata (without full h_mem profiles for brevity)."""
    return [
        {
            "character_id": p["character_id"],
            "display_name": p["display_name"],
            "short_name": p["short_name"],
            "role": p["role"],
            "avatar": p["avatar"],
            "color": p["color"],
            "color_dark": p["color_dark"],
            "tagline": p["tagline"],
        }
        for p in PROFILES.values()
    ]


@app.get("/api/profile/{character_id}")
async def get_profile(character_id: str):
    """Return the full H-MEM profile for a character."""
    if character_id not in PROFILES:
        raise HTTPException(status_code=404, detail=f"Character '{character_id}' not found")
    return PROFILES[character_id]


@app.post("/api/chat")
async def chat(request: ChatRequest):
    """
    Streaming chat endpoint.

    Builds the character system prompt from their H-MEM profile and
    streams Claude's response back as server-sent events.
    """
    if request.character_id not in PROFILES:
        raise HTTPException(status_code=404, detail=f"Character '{request.character_id}' not found")

    profile = PROFILES[request.character_id]
    system_prompt = build_system_prompt(profile)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not set")

    client = anthropic.Anthropic(api_key=api_key)

    messages = [{"role": m.role, "content": m.content} for m in request.messages]

    async def generate() -> AsyncIterator[str]:
        with client.messages.stream(
            model="claude-opus-4-5",
            max_tokens=1024,
            system=system_prompt,
            messages=messages,
        ) as stream:
            for text in stream.text_stream:
                # SSE format: data: <json>\n\n
                yield f"data: {json.dumps({'text': text})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# Serve the frontend
# ─────────────────────────────────────────────────────────────────────────────

# Mount static files last so API routes take precedence
static_dir = Path("static")
static_dir.mkdir(exist_ok=True)
app.mount("/", StaticFiles(directory="static", html=True), name="static")
