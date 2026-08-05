import argparse
import asyncio
import hashlib
import re
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import boto3  # type: ignore[import-untyped]
import fitz  # type: ignore[import-untyped]
import structlog
from pinecone import Pinecone

from retail_bank_agents.config import get_settings
from retail_bank_agents.logging import configure_logging
from retail_bank_agents.providers.openai_gateway import OpenAIResponsesGateway

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Chunk:
    id: str
    text: str
    metadata: dict[str, str | int]


def normalize_text(value: str) -> str:
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def chunk_pdf(
    path: Path,
    *,
    source_uri: str,
    title: str,
    document_version: str,
    segment: str,
    target_chars: int = 2_800,
    overlap_chars: int = 350,
) -> list[Chunk]:
    """Page-aware chunks keep citations stable and avoid crossing policy-page boundaries."""
    chunks: list[Chunk] = []
    with fitz.open(path) as document:
        for page_number, page in enumerate(document, start=1):
            text = normalize_text(page.get_text("text"))
            if not text:
                continue
            start = 0
            ordinal = 0
            while start < len(text):
                end = min(len(text), start + target_chars)
                if end < len(text):
                    boundary = text.rfind("\n", start + target_chars // 2, end)
                    if boundary > start:
                        end = boundary
                value = text[start:end].strip()
                if value:
                    digest = hashlib.sha256(
                        f"{source_uri}|{document_version}|{page_number}|{ordinal}|{value}".encode()
                    ).hexdigest()
                    chunks.append(
                        Chunk(
                            id=digest,
                            text=value,
                            metadata={
                                "title": title,
                                "page": page_number,
                                "section": f"page-{page_number}",
                                "uri": source_uri,
                                "document_version": document_version,
                                "publication_status": "approved",
                                "customer_segment": segment,
                            },
                        )
                    )
                    ordinal += 1
                if end >= len(text):
                    break
                start = max(end - overlap_chars, start + 1)
    return chunks


def batches(values: list[Chunk], size: int) -> Iterator[list[Chunk]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


async def ingest_prefix(prefix: str, segment: str) -> None:
    settings = get_settings()
    if not settings.s3_document_bucket:
        raise ValueError("S3_DOCUMENT_BUCKET is required")
    s3 = boto3.client("s3", region_name=settings.aws_region)
    paginator = s3.get_paginator("list_objects_v2")
    openai = OpenAIResponsesGateway(settings)
    index = Pinecone(api_key=settings.pinecone_api_key.get_secret_value()).Index(
        settings.pinecone_index
    )
    for page in paginator.paginate(Bucket=settings.s3_document_bucket, Prefix=prefix):
        for item in page.get("Contents", []):
            key = str(item["Key"])
            if not key.lower().endswith(".pdf"):
                continue
            version = str(item.get("ETag", "unknown")).strip('"')
            with tempfile.TemporaryDirectory(prefix="bank-ingest-") as temp_dir:
                local_path = Path(temp_dir) / "document.pdf"
                s3.download_file(settings.s3_document_bucket, key, str(local_path))
                chunks = chunk_pdf(
                    local_path,
                    source_uri=f"s3://{settings.s3_document_bucket}/{key}",
                    title=Path(key).stem,
                    document_version=version,
                    segment=segment,
                )
                for batch in batches(chunks, 64):
                    embeddings = await openai.embed([chunk.text for chunk in batch])
                    vectors: list[dict[str, object]] = []
                    for chunk, embedding in zip(batch, embeddings, strict=True):
                        metadata: dict[str, object] = dict(chunk.metadata)
                        metadata["text"] = chunk.text
                        vectors.append({"id": chunk.id, "values": embedding, "metadata": metadata})
                    await asyncio.to_thread(
                        index.upsert, vectors=vectors, namespace=settings.pinecone_namespace
                    )
                logger.info("document_ingested", key=key, chunks=len(chunks), version=version)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest approved retail-bank PDFs from S3")
    parser.add_argument("--prefix", default="approved/")
    parser.add_argument("--segment", default="all", choices=("all", "mass", "affluent", "private"))
    args = parser.parse_args()
    settings = get_settings()
    configure_logging(settings.log_level)
    asyncio.run(ingest_prefix(args.prefix, args.segment))


if __name__ == "__main__":
    main()
