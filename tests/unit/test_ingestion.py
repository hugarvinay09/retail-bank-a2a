from retail_bank_agents.rag.ingestion import normalize_text


def test_normalize_text_preserves_paragraphs() -> None:
    assert normalize_text("Fee    schedule\n\n\nAmount") == "Fee schedule\n\nAmount"
