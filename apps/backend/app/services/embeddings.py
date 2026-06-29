import hashlib
import json
import math
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol

from app.core.config import settings


class EmbeddingError(RuntimeError):
    pass


class EmbeddingProvider(Protocol):
    model: str
    dimensions: int

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        ...

    def embed_text(self, text: str) -> list[float]:
        ...


@dataclass(frozen=True)
class LocalHashEmbeddingProvider:
    dimensions: int = settings.embedding_dimensions
    model: str = "local-hash-v1"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_text(text) for text in texts]

    def embed_text(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in _embedding_tokens(text):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign

        return normalize_vector(vector)


@dataclass(frozen=True)
class OpenAIEmbeddingProvider:
    api_key: str = settings.openai_api_key
    model: str = settings.openai_embedding_model
    dimensions: int = settings.embedding_dimensions

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not self.api_key:
            raise EmbeddingError("OPENAI_API_KEY is required for OpenAI embeddings.")
        if not texts:
            return []

        payload = json.dumps(
            {
                "model": self.model,
                "input": texts,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            "https://api.openai.com/v1/embeddings",
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read().decode("utf-8")
        except urllib.error.URLError as exc:
            raise EmbeddingError(f"OpenAI embedding request failed: {exc}") from exc

        decoded = json.loads(body)
        rows = sorted(decoded.get("data", []), key=lambda item: item["index"])
        vectors = [normalize_vector(row["embedding"]) for row in rows]
        if not vectors:
            raise EmbeddingError("OpenAI embedding response did not include vectors.")
        return vectors

    def embed_text(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]


def get_default_embedding_provider() -> EmbeddingProvider:
    if settings.openai_api_key:
        return OpenAIEmbeddingProvider()
    return LocalHashEmbeddingProvider()


def embedding_text(title: str | None, content: str | None, keywords: str | None) -> str:
    return "\n".join(
        value.strip()
        for value in (title, content, keywords)
        if value and value.strip()
    )


def format_vector(vector: list[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in vector) + "]"


def parse_vector(value: object) -> list[float] | None:
    if value is None:
        return None
    if isinstance(value, list):
        return [float(item) for item in value]

    text = str(value).strip()
    if not text:
        return None
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    if not text.strip():
        return None
    try:
        return [float(item.strip()) for item in text.split(",") if item.strip()]
    except ValueError:
        return None


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0

    dot = sum(left_item * right_item for left_item, right_item in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(item * item for item in left))
    right_norm = math.sqrt(sum(item * item for item in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return max(0.0, min(1.0, dot / (left_norm * right_norm)))


def normalize_vector(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(item * item for item in vector))
    if norm == 0:
        return vector
    return [item / norm for item in vector]


def _embedding_tokens(text: str) -> tuple[str, ...]:
    normalized = re.sub(r"\s+", " ", text.strip().casefold())
    words = re.findall(r"[0-9a-zA-Z가-힣]+", normalized)
    char_grams: list[str] = []
    compact = re.sub(r"\s+", "", normalized)
    for size in (2, 3, 4):
        char_grams.extend(
            compact[index : index + size]
            for index in range(max(0, len(compact) - size + 1))
        )
    return tuple([*words, *char_grams])
