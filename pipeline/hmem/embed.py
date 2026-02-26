"""
Embedding using TF-IDF + Truncated SVD (Latent Semantic Analysis).

No model downloads needed — entirely local, uses scikit-learn.

The vectorizer is fit once on the full corpus (all characters), then used
for both H-MEM construction and query embedding at retrieval time.
This ensures query vectors land in the same space as stored episode vectors.

Bigrams + sublinear TF weighting captures Futurama's distinctive vocabulary
("meatbag", "shiny metal ass", "good news everyone", etc.) better than unigrams alone.
"""

from __future__ import annotations

import joblib
import numpy as np
from pathlib import Path
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

N_COMPONENTS = 256   # SVD output dimension


class EmbeddingModel:
    """
    Fit-once, transform-many text embedder.
    Produces L2-normalized float32 vectors so cosine_similarity == dot product.
    """

    def __init__(self):
        self.tfidf = TfidfVectorizer(
            ngram_range=(1, 2),
            min_df=2,
            max_df=0.95,
            max_features=60_000,
            sublinear_tf=True,
        )
        self.svd = TruncatedSVD(n_components=N_COMPONENTS, random_state=42)
        self._fitted = False

    def fit(self, texts: list[str]) -> "EmbeddingModel":
        mat = self.tfidf.fit_transform(texts)
        # Cap components to min(vocab-1, n_samples-1) — SVD constraint
        n_features = mat.shape[1]
        n_samples = mat.shape[0]
        actual_components = min(N_COMPONENTS, n_features - 1, n_samples - 1)
        if actual_components != self.svd.n_components:
            self.svd = TruncatedSVD(n_components=actual_components, random_state=42)
        self.svd.fit(mat)
        self._fitted = True
        var = self.svd.explained_variance_ratio_.sum()
        print(f"    Embedding model: vocab={n_features:,}, "
              f"{actual_components}-d SVD explains {var:.1%} of variance")
        return self

    def transform(self, texts: list[str]) -> np.ndarray:
        assert self._fitted, "Call fit() on the full corpus before transform()"
        mat = self.tfidf.transform(texts)
        vecs = self.svd.transform(mat)
        return normalize(vecs, norm="l2").astype(np.float32)

    def fit_transform(self, texts: list[str]) -> np.ndarray:
        mat = self.tfidf.fit_transform(texts)
        vecs = self.svd.fit_transform(mat)
        self._fitted = True
        return normalize(vecs, norm="l2").astype(np.float32)

    def save(self, path: Path) -> None:
        joblib.dump(self, path)

    @staticmethod
    def load(path: Path) -> "EmbeddingModel":
        return joblib.load(path)


# ─── Module-level singleton ────────────────────────────────────────────────
# Populated once by load_model() after the embedding model is built.
_model: EmbeddingModel | None = None


def load_model(path: Path) -> None:
    global _model
    _model = EmbeddingModel.load(path)


def embed(texts: list[str]) -> np.ndarray:
    """Embed texts using the loaded model. Call load_model() first."""
    assert _model is not None, "Call load_model(path) before embed()"
    return _model.transform(texts)
