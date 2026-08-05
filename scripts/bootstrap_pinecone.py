import argparse

from pinecone import Pinecone, ServerlessSpec

from retail_bank_agents.config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Create the configured Pinecone index")
    parser.add_argument("--cloud", default="aws")
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args()
    settings = get_settings()
    client = Pinecone(api_key=settings.pinecone_api_key.get_secret_value())
    existing = {item.name for item in client.list_indexes()}
    if settings.pinecone_index not in existing:
        client.create_index(
            name=settings.pinecone_index,
            dimension=3072,
            metric="cosine",
            spec=ServerlessSpec(cloud=args.cloud, region=args.region),
            deletion_protection="enabled",
            tags={"application": "retail-bank-a2a", "data_class": "confidential"},
        )
    print(settings.pinecone_index)


if __name__ == "__main__":
    main()
