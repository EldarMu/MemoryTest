"""
H-MEM Bottom-Up Builder
=======================

Constructs a four-layer Hierarchical Memory structure from raw transcript lines.

Algorithm (bottom-up):

  1. Episode Layer   — embed each raw utterance (using shared EmbeddingModel)
  2. K-Means cluster episodes → Memory Trace clusters
     For each cluster: LLM summarizes the behavioral pattern
     Embed the summary → Memory Trace vector
  3. K-Means cluster memory traces → Category clusters
     For each cluster: LLM summarizes the higher-level category
     Embed the summary → Category vector
  4. LLM synthesizes all categories → single Domain description
     Embed the domain text → Domain vector

Each node stores text, a vector, and ptr lists into the level below.
Vectors are returned separately (in '_vecs') for compact storage by store.py.

The positional index encoding from H-MEM (arXiv:2507.22925) is implemented
as the `episode_ptrs` / `trace_ptrs` / `category_ptrs` lists — each node
explicitly indexes its sub-nodes, enabling top-down retrieval without
exhaustive search at the bottom level.
"""

from __future__ import annotations

import numpy as np
import anthropic

from .embed import EmbeddingModel

# ─────────────────────────────────────────────────────────────────────────────
# LLM prompts
# ─────────────────────────────────────────────────────────────────────────────

_TRACE_PROMPT = """\
These are lines spoken by {name} in Futurama that cluster together semantically:

{lines}

In 1-2 sentences, describe the behavioral pattern, recurring habit, speech tendency, \
or thematic preoccupation these lines share. Be specific — what does this cluster reveal \
about how {name} thinks, speaks, or behaves? Do not name the character. No preamble."""

_CATEGORY_PROMPT = """\
These are behavioral patterns identified in {name} from Futurama:

{patterns}

In 1-2 sentences, summarize the higher-level category these patterns share. \
What unified aspect of {name}'s personality, speech style, or worldview do they reflect? \
No preamble."""

_DOMAIN_PROMPT = """\
These are the key behavioral categories extracted from {name}'s dialogue in Futurama:

{categories}

Write 3-4 sentences describing {name}'s core personality — their fundamental nature, \
worldview, and what makes them distinctively themselves. This is the most abstract, \
essential description. No preamble."""


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _n_clusters(n_items: int, target_per_cluster: int) -> int:
    return max(2, round(n_items / target_per_cluster))


def _llm(client: anthropic.Anthropic, prompt: str, max_tokens: int = 150) -> str:
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text.strip()


# ─────────────────────────────────────────────────────────────────────────────
# Main builder
# ─────────────────────────────────────────────────────────────────────────────

def build(
    character_id: str,
    display_name: str,
    lines: list[str],
    client: anthropic.Anthropic,
    embedding_model: EmbeddingModel,
    episodes_per_trace: int = 25,
    traces_per_category: int = 8,
    max_lines_per_summary: int = 12,
) -> dict:
    """
    Build an H-MEM structure from transcript lines.

    Args:
        character_id:        canonical ID (e.g. "bender")
        display_name:        full name for LLM prompts
        lines:               all transcript lines for this character
        client:              Anthropic client (for LLM summarization)
        embedding_model:     pre-fitted EmbeddingModel (shared across characters)
        episodes_per_trace:  K-Means target cluster size at episode->trace level
        traces_per_category: K-Means target cluster size at trace->category level
        max_lines_per_summary: max episodes shown to LLM per trace summary

    Returns dict with:
        character_id, display_name, domain, categories, memory_traces, episodes,
        _vecs (numpy arrays), stats
    """
    from sklearn.cluster import KMeans

    n = len(lines)
    print(f"  [{display_name}] {n} lines", flush=True)

    # ── Layer 4: Episodes ─────────────────────────────────────────────────
    print(f"    Embedding {n} episodes...", flush=True)
    ep_vecs = embedding_model.transform(lines)   # (N, D)
    episodes = [{"text": line} for line in lines]

    # ── Layer 3: Memory Traces ────────────────────────────────────────────
    n_traces = _n_clusters(n, episodes_per_trace)
    print(f"    K-Means: {n} eps -> {n_traces} traces...", flush=True)

    km_ep = KMeans(n_clusters=n_traces, random_state=42, n_init="auto")
    ep_labels = km_ep.fit_predict(ep_vecs)

    trace_texts: list[str] = []
    trace_ep_ptrs: list[list[int]] = []

    for ci in range(n_traces):
        member_idxs = [i for i, lbl in enumerate(ep_labels) if lbl == ci]

        # Pick lines closest to cluster centroid
        centroid = ep_vecs[member_idxs].mean(axis=0)
        sims = ep_vecs[member_idxs] @ centroid
        ranked = sorted(zip(sims.tolist(), member_idxs), reverse=True)
        sample_lines = [lines[idx] for _, idx in ranked[:max_lines_per_summary]]

        summary = _llm(client, _TRACE_PROMPT.format(
            name=display_name,
            lines="\n".join(f"- {l}" for l in sample_lines),
        ))
        trace_texts.append(summary)
        trace_ep_ptrs.append(member_idxs)

    print(f"    Embedding {n_traces} trace summaries...", flush=True)
    trace_vecs = embedding_model.transform(trace_texts)

    memory_traces = [
        {"text": trace_texts[i], "episode_ptrs": trace_ep_ptrs[i]}
        for i in range(n_traces)
    ]

    # ── Layer 2: Categories ───────────────────────────────────────────────
    n_cats = _n_clusters(n_traces, traces_per_category)
    print(f"    K-Means: {n_traces} traces -> {n_cats} cats...", flush=True)

    km_tr = KMeans(n_clusters=n_cats, random_state=42, n_init="auto")
    tr_labels = km_tr.fit_predict(trace_vecs)

    cat_texts: list[str] = []
    cat_trace_ptrs: list[list[int]] = []

    for ci in range(n_cats):
        member_idxs = [i for i, lbl in enumerate(tr_labels) if lbl == ci]
        patterns = [trace_texts[i] for i in member_idxs]

        summary = _llm(client, _CATEGORY_PROMPT.format(
            name=display_name,
            patterns="\n".join(f"- {p}" for p in patterns),
        ))
        cat_texts.append(summary)
        cat_trace_ptrs.append(member_idxs)

    print(f"    Embedding {n_cats} category summaries...", flush=True)
    cat_vecs = embedding_model.transform(cat_texts)

    categories = [
        {"text": cat_texts[i], "trace_ptrs": cat_trace_ptrs[i]}
        for i in range(n_cats)
    ]

    # ── Layer 1: Domain ───────────────────────────────────────────────────
    print(f"    Synthesizing domain...", flush=True)
    domain_text = _llm(client, _DOMAIN_PROMPT.format(
        name=display_name,
        categories="\n".join(f"- {t}" for t in cat_texts),
    ), max_tokens=300)

    domain_vec = embedding_model.transform([domain_text])[0]

    domain = {
        "text": domain_text,
        "category_ptrs": list(range(n_cats)),
    }

    stats = {
        "n_episodes": n,
        "n_traces": n_traces,
        "n_categories": n_cats,
    }

    print(f"    Done: {n} eps / {n_traces} traces / {n_cats} cats / 1 domain")

    return {
        "character_id": character_id,
        "display_name": display_name,
        "domain": domain,
        "categories": categories,
        "memory_traces": memory_traces,
        "episodes": episodes,
        "_vecs": {
            "domain":        domain_vec,
            "categories":    cat_vecs,
            "memory_traces": trace_vecs,
            "episodes":      ep_vecs,
        },
        "stats": stats,
    }
