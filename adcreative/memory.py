"""Creative memory: past concept notes retrieved by local embeddings (bge-small via fastembed)."""
import json
from pathlib import Path
import numpy as np

NOTES = Path(__file__).resolve().parent.parent / "data" / "memory_notes.json"
SIM_THRESHOLD = 0.78  # chosen after seeing the memory-off arm in results/memory_demo_threshold_probe.json (max 0.825, mean ~0.75)
_model = None


def embed(texts: list[str]) -> np.ndarray:
    global _model
    if _model is None:
        from fastembed import TextEmbedding
        _model = TextEmbedding("BAAI/bge-small-en-v1.5")
    v = np.array(list(_model.embed(texts)))
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def note_text(n: dict) -> str:
    return f"{n['audience']}: {n['angle']}. {n['hook']}"


class Memory:
    def __init__(self, notes: list[dict] | None = None, embedder=embed):
        self.notes = json.loads(NOTES.read_text()) if notes is None else notes
        self.embedder = embedder
        self.vecs = embedder([note_text(n) for n in self.notes]) if self.notes else np.zeros((0, 1))

    def sims(self, text: str) -> np.ndarray:
        return self.vecs @ self.embedder([text])[0] if self.notes else np.zeros(0)

    def retrieve(self, text: str, k=6) -> list[tuple[dict, float]]:
        s = self.sims(text)
        return [(self.notes[i], float(s[i])) for i in np.argsort(-s)[:k]]

    def max_sim(self, text: str) -> tuple[float, str | None]:
        if not self.notes:
            return 0.0, None
        s = self.sims(text)
        i = int(np.argmax(s))
        return float(s[i]), self.notes[i]["id"]
