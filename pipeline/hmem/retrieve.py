"""
H-MEM Top-Down Retrieval
========================

Given a query string, traverses the hierarchy from Domain down to Episodes,
narrowing the candidate set at each level using cosine similarity.

This is the core efficiency gain H-MEM describes: instead of searching all N episodes,
we start from the most abstract level (Domain), identify the most relevant Categories,
then only search Traces within those Categories, then only Episodes within those Traces.

The search space shrinks at each level:
  all categories  →  top-k_cat
  traces in those categories  →  top-k_trace
  episodes in those traces  →  top-k_ep

Return value includes scores so the frontend can show which nodes were activated.
"""

from __future__ import annotations

import numpy as np
from .embed import embed, EmbeddingModel


def retrieve(
    hmem: dict,
    query: str,
    top_k_categories: int = 3,
    top_k_traces: int = 5,
    top_k_episodes: int = 8,
    embedding_model: EmbeddingModel | None = None,
) -> dict:
    """
    Top-down hierarchical retrieval.

    Args:
        hmem:              loaded H-MEM structure (from store.load)
        query:             the user's message
        top_k_categories:  how many categories to descend into
        top_k_traces:      how many traces to return
        top_k_episodes:    how many episodes to return

    Returns dict with:
        domain         — always returned (string)
        categories     — list of {text, score, index}
        traces         — list of {text, score, index, category_idx}
        episodes       — list of {text, score, index, trace_idx}
        search_stats   — how many candidates were considered at each level
    """
    _embed = embedding_model.transform if embedding_model else embed
    q_vec = _embed([query])[0]   # (D,)

    # Guard: if query is entirely out-of-vocabulary the vector will be zero.
    # Fall back to returning the first k nodes at each level (still useful context).
    q_norm = float(np.linalg.norm(q_vec))
    if q_norm < 1e-8:
        q_vec = np.ones(q_vec.shape, dtype=np.float32) / np.sqrt(q_vec.shape[0])

    vecs = hmem["_vecs"]
    struct = hmem

    # ── Domain (always returned) ──────────────────────────────────────────
    domain_score = float(q_vec @ vecs["domain"])

    # ── Categories: search all, take top-k ───────────────────────────────
    cat_vecs = vecs["categories"]               # (n_cats, D)
    cat_scores = (cat_vecs @ q_vec).tolist()    # (n_cats,)
    ranked_cats = sorted(
        enumerate(cat_scores), key=lambda x: x[1], reverse=True
    )[:top_k_categories]

    selected_cats = [
        {
            "text": struct["categories"][i]["text"],
            "score": score,
            "index": i,
        }
        for i, score in ranked_cats
    ]

    # ── Traces: search only within selected categories ────────────────────
    candidate_trace_idxs: list[int] = []
    trace_to_cat: dict[int, int] = {}
    for cat_entry in selected_cats:
        ci = cat_entry["index"]
        for ti in struct["categories"][ci]["trace_ptrs"]:
            if ti not in trace_to_cat:
                candidate_trace_idxs.append(ti)
                trace_to_cat[ti] = ci

    tr_vecs = vecs["memory_traces"]
    cand_vecs = tr_vecs[candidate_trace_idxs]         # (n_cand, D)
    cand_scores = (cand_vecs @ q_vec).tolist()

    ranked_traces = sorted(
        zip(candidate_trace_idxs, cand_scores), key=lambda x: x[1], reverse=True
    )[:top_k_traces]

    selected_traces = [
        {
            "text": struct["memory_traces"][ti]["text"],
            "score": score,
            "index": ti,
            "category_idx": trace_to_cat[ti],
        }
        for ti, score in ranked_traces
    ]

    # ── Episodes: search only within selected traces ──────────────────────
    candidate_ep_idxs: list[int] = []
    ep_to_trace: dict[int, int] = {}
    for tr_entry in selected_traces:
        ti = tr_entry["index"]
        for ei in struct["memory_traces"][ti]["episode_ptrs"]:
            if ei not in ep_to_trace:
                candidate_ep_idxs.append(ei)
                ep_to_trace[ei] = ti

    ep_vecs = vecs["episodes"]
    cand_ep_vecs = ep_vecs[candidate_ep_idxs]         # (n_cand, D)
    cand_ep_scores = (cand_ep_vecs @ q_vec).tolist()

    ranked_eps = sorted(
        zip(candidate_ep_idxs, cand_ep_scores), key=lambda x: x[1], reverse=True
    )[:top_k_episodes]

    selected_episodes = [
        {
            "text": struct["episodes"][ei]["text"],
            "score": score,
            "index": ei,
            "trace_idx": ep_to_trace[ei],
        }
        for ei, score in ranked_eps
    ]

    return {
        "domain": {
            "text": struct["domain"]["text"],
            "score": domain_score,
        },
        "categories": selected_cats,
        "traces": selected_traces,
        "episodes": selected_episodes,
        "search_stats": {
            "total_categories": len(struct["categories"]),
            "searched_categories": len(struct["categories"]),
            "total_traces": len(struct["memory_traces"]),
            "searched_traces": len(candidate_trace_idxs),
            "total_episodes": len(struct["episodes"]),
            "searched_episodes": len(candidate_ep_idxs),
        },
    }
