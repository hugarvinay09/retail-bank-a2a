import asyncio
from time import monotonic

import cohere
from pinecone import Pinecone

from retail_bank_agents.config import Settings
from retail_bank_agents.domain.models import RetrievedDocument
from retail_bank_agents.metrics import PROVIDER_LATENCY
from retail_bank_agents.providers.openai_gateway import OpenAIResponsesGateway


class PineconeCohereRetriever:
    """Dense retrieval with metadata isolation followed by cross-encoder reranking."""

    def __init__(self, settings: Settings, openai: OpenAIResponsesGateway) -> None:
        self._settings = settings
        self._openai = openai
        self._index = Pinecone(api_key=settings.pinecone_api_key.get_secret_value()).Index(
            settings.pinecone_index
        )
        self._cohere = cohere.ClientV2(api_key=settings.cohere_api_key.get_secret_value())

    async def search(
        self, query: str, *, customer_segment: str, top_k: int = 6
    ) -> list[RetrievedDocument]:
        embedding = (await self._openai.embed([query]))[0]
        started = monotonic()
        result = await asyncio.to_thread(
            self._index.query,
            vector=embedding,
            top_k=max(20, top_k * 3),
            include_metadata=True,
            namespace=self._settings.pinecone_namespace,
            filter={
                "$and": [
                    {"publication_status": {"$eq": "approved"}},
                    {"customer_segment": {"$in": [customer_segment, "all"]}},
                ]
            },
        )
        PROVIDER_LATENCY.labels(provider="pinecone", operation="query").observe(
            monotonic() - started
        )
        candidates = []
        for match in result.matches:
            metadata = dict(match.metadata or {})
            text = str(metadata.get("text", ""))
            if text:
                candidates.append((str(match.id), text, metadata, float(match.score or 0)))
        if not candidates:
            return []

        started = monotonic()
        reranked = await asyncio.to_thread(
            self._cohere.rerank,
            model=self._settings.cohere_rerank_model,
            query=query,
            documents=[item[1] for item in candidates],
            top_n=top_k,
        )
        PROVIDER_LATENCY.labels(provider="cohere", operation="rerank").observe(
            monotonic() - started
        )
        documents: list[RetrievedDocument] = []
        for row in reranked.results:
            doc_id, text, metadata, _ = candidates[row.index]
            documents.append(
                RetrievedDocument(
                    id=doc_id,
                    text=text,
                    title=str(metadata.get("title", "Untitled approved document")),
                    page=int(metadata["page"]) if metadata.get("page") is not None else None,
                    section=str(metadata["section"]) if metadata.get("section") else None,
                    uri=str(metadata["uri"]) if metadata.get("uri") else None,
                    score=max(0.0, min(1.0, float(row.relevance_score))),
                    metadata={key: value for key, value in metadata.items() if key not in {"text"}},
                )
            )
        return documents
