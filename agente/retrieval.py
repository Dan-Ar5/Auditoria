from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections import Counter
from typing import Any, Dict, List, Optional

from .corpus import NormativeCorpus, matches

CANDIDATES_PER_METHOD = 20  # top-k de cada método antes de RRF (TIF, 3.5.2)
RERANK_CANDIDATES = 30      # candidatos fusionados que pasan al Cross-Encoder (TIF, 3.5.3)

STOPWORDS = set("""
a al ante bajo con contra de del desde durante en entre hacia hasta mediante para por segun sin sobre tras
el la los las lo un una unos unas y o u e ni que se su sus es son ser como mas pero si no le les
this the of and or to in for be by on with as an is are at it its that which from any
""".split())


def _tokens(text: str) -> List[str]:
    """Minúsculas, sin tildes, sin stopwords y con un stemming simple por prefijo."""
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    words = re.findall(r"[a-z]+\.\d+(?:\.\d+)*|[a-z0-9]+", text)
    return [w if any(ch.isdigit() for ch in w) else w[:6] for w in words if w not in STOPWORDS and len(w) > 1]


class LocalBM25Retriever:
    """Backend local (solo librería estándar): BM25 + filtros de metadatos. Sin Docker ni modelos."""

    mode = "local"

    def __init__(self, corpus: NormativeCorpus, k1: float = 1.5, b: float = 0.75) -> None:
        self.corpus = corpus
        self.k1 = k1
        self.b = b
        self.index()

    def index(self, rebuild: bool = False) -> Dict[str, Any]:
        self._docs = [Counter(_tokens(self._indexable(f))) for f in self.corpus.fragments]
        self._lengths = [sum(d.values()) for d in self._docs]
        self._avg = sum(self._lengths) / max(len(self._lengths), 1)
        df = Counter(term for doc in self._docs for term in doc)
        n = len(self._docs)
        self._idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}
        return {"backend": self.mode, "fragments": n, "reindexed": True}

    @staticmethod
    def _indexable(fragment: Dict[str, Any]) -> str:
        return " ".join(str(fragment.get(k) or "") for k in ("control", "seccion_jerarquica", "texto"))

    def search(self, query: str, top_k: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        terms = _tokens(query)
        scored = []
        for i, fragment in enumerate(self.corpus.fragments):
            if filters and not matches(fragment, filters):
                continue
            doc, length = self._docs[i], self._lengths[i]
            score = 0.0
            for term in terms:
                tf = doc.get(term, 0)
                if tf:
                    score += self._idf[term] * tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * length / self._avg))
            if score > 0:
                scored.append((score, fragment))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [{**fragment, "score": round(score, 4), "retrieval": "bm25"} for score, fragment in scored[:top_k]]


class QdrantHybridRetriever:
    """Backend real (TIF 3.5): densa (multilingüe) + BM25 -> RRF en Qdrant -> Cross-Encoder."""

    mode = "qdrant"

    def __init__(
        self,
        corpus: NormativeCorpus,
        url: str = "http://localhost:6333",
        collection: str = "agt_consent_corpus",
        dense_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        sparse_model: str = "Qdrant/bm25",
        reranker_model: Optional[str] = "BAAI/bge-reranker-v2-m3-int8",
        cache_dir: str = ".modelos",
    ) -> None:
        try:
            from fastembed import SparseTextEmbedding, TextEmbedding
            from qdrant_client import QdrantClient
        except ImportError as exc:
            raise RuntimeError("El modo qdrant requiere qdrant-client y fastembed. Instala requirements.txt") from exc

        self.corpus = corpus
        self.collection = collection
        self.client = QdrantClient(location=":memory:") if url == ":memory:" else QdrantClient(url=url)
        self.client.get_collections()  # falla rápido si Qdrant no está levantado
        self.dense = TextEmbedding(model_name=dense_model, cache_dir=cache_dir)
        self.sparse = SparseTextEmbedding(model_name=sparse_model, cache_dir=cache_dir, language="spanish")
        self.dense_model = dense_model
        self.reranker = None
        self.reranker_error = None
        if reranker_model:
            try:
                from fastembed.rerank.cross_encoder import TextCrossEncoder
                self.reranker = TextCrossEncoder(model_name=reranker_model, cache_dir=cache_dir)
            except Exception as exc:  # noqa: BLE001 - el re-ranking es opcional
                self.reranker_error = str(exc)

    def _fingerprint(self) -> str:
        payload = json.dumps([f["texto"] for f in self.corpus.fragments] + [self.dense_model], ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def _stored_fingerprint(self) -> Optional[str]:
        if not self.client.collection_exists(self.collection):
            return None
        points, _ = self.client.scroll(self.collection, limit=1, with_payload=True)
        return points[0].payload.get("corpus_hash") if points else None

    def index(self, rebuild: bool = False) -> Dict[str, Any]:
        from qdrant_client.models import Distance, Modifier, PointStruct, SparseVector, SparseVectorParams, VectorParams

        fingerprint = self._fingerprint()
        if not rebuild and self._stored_fingerprint() == fingerprint:
            return {"backend": self.mode, "fragments": len(self.corpus), "reindexed": False}

        if self.client.collection_exists(self.collection):
            self.client.delete_collection(self.collection)
        texts = [f["texto"] for f in self.corpus.fragments]
        dense_vectors = list(self.dense.embed(texts, batch_size=32))
        self.client.create_collection(
            collection_name=self.collection,
            vectors_config={"denso": VectorParams(size=len(dense_vectors[0]), distance=Distance.COSINE)},
            sparse_vectors_config={"bm25": SparseVectorParams(modifier=Modifier.IDF)},
        )
        sparse_vectors = list(self.sparse.embed(texts, batch_size=32))
        points = [
            PointStruct(
                id=i + 1,
                vector={"denso": dense.tolist(),
                        "bm25": SparseVector(indices=sparse.indices.tolist(), values=sparse.values.tolist())},
                payload={**fragment, "corpus_hash": fingerprint},
            )
            for i, (fragment, dense, sparse) in enumerate(zip(self.corpus.fragments, dense_vectors, sparse_vectors))
        ]
        for start in range(0, len(points), 64):
            self.client.upsert(self.collection, points=points[start:start + 64])
        return {"backend": self.mode, "fragments": len(points), "reindexed": True}

    @staticmethod
    def _qdrant_filter(filters: Optional[Dict[str, Any]]):
        from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue

        if not filters:
            return None
        conditions = []
        for key, expected in filters.items():
            if expected is None:
                continue
            if isinstance(expected, (list, tuple, set)):
                conditions.append(FieldCondition(key=key, match=MatchAny(any=list(expected))))
            else:
                conditions.append(FieldCondition(key=key, match=MatchValue(value=expected)))
        return Filter(must=conditions) if conditions else None

    def search(self, query: str, top_k: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        from qdrant_client.models import Fusion, FusionQuery, Prefetch, SparseVector

        qfilter = self._qdrant_filter(filters)
        dense = next(iter(self.dense.query_embed(query))).tolist()
        sparse = next(iter(self.sparse.query_embed(query)))
        fused = self.client.query_points(
            collection_name=self.collection,
            prefetch=[
                Prefetch(query=dense, using="denso", limit=CANDIDATES_PER_METHOD, filter=qfilter),
                Prefetch(query=SparseVector(indices=sparse.indices.tolist(), values=sparse.values.tolist()),
                         using="bm25", limit=CANDIDATES_PER_METHOD, filter=qfilter),
            ],
            query=FusionQuery(fusion=Fusion.RRF),
            limit=RERANK_CANDIDATES if self.reranker else top_k,
            with_payload=True,
        ).points
        candidates = [({k: v for k, v in p.payload.items() if k != "corpus_hash"}, p.score) for p in fused]

        if self.reranker and candidates:
            scores = list(self.reranker.rerank(query, [c[0]["texto"] for c in candidates]))
            ranked = sorted(zip(candidates, scores), key=lambda item: item[1], reverse=True)[:top_k]
            return [{**fragment, "score": round(float(score), 4), "rrf_score": round(rrf, 4),
                     "retrieval": "densa+bm25->rrf->cross-encoder"} for (fragment, rrf), score in ranked]
        return [{**fragment, "score": round(rrf, 4), "retrieval": "densa+bm25->rrf"}
                for fragment, rrf in candidates[:top_k]]


def build_retriever(mode: str, corpus: NormativeCorpus, **kwargs: Any):
    if mode == "qdrant":
        return QdrantHybridRetriever(corpus, **kwargs)
    return LocalBM25Retriever(corpus)
