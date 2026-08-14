"""Measure real cosine distances, so the relevance threshold is set from data.

`RETRIEVAL_MAX_DISTANCE` decides when a retrieved chunk is too unrelated to the
question to be worth answering from. Guessing that number is how you get either
false refusals or answers drawn from irrelevant text, so it is measured here.

Three question classes matter, not two:

  relevant   - answerable from the corpus; must stay BELOW the threshold
  near-miss  - same subject area, but the corpus does not answer it; the
               genuinely hard case, and where a tight threshold does damage
  off-topic  - unrelated to anything uploaded; should sit ABOVE the threshold

The threshold is only useful if there is daylight between the relevant band and
the off-topic band.

Run from the backend directory, with the provider selected by environment:

    cd backend
    EMBEDDING_PROVIDER=local PYTHONPATH=. python ../docs/measurements/measure_distances.py

Nothing is written to the real database or vector store; a temporary Chroma
directory is used and discarded.

--------------------------------------------------------------------------
RECORDED RESULT - all-MiniLM-L6-v2 (EMBEDDING_PROVIDER=local), 384 dimensions
Corpus: 15 chunks across 3 documents. Cosine distance, range [0, 2].

  class       min      median   max
  relevant    0.1602   0.2570   0.4587
  near-miss   0.4627   0.5742   0.6355
  off-topic   0.7978   0.9317   0.9679

  gap between worst relevant and best off-topic: +0.3391

Cross-checked against the corpus used in the isolation test report: the owner
asking about their own memo measured 0.2684, and a different user asking the
identical question against unrelated documents measured 0.9730.

Chosen default: 0.75. It clears the worst relevant question by 0.29 and sits
just under the closest off-topic question, deliberately nearer the off-topic
end, because a false refusal is worse than an occasional over-answer.

Note that relevant and near-miss are NOT separable by distance: near-miss
begins at 0.4627, only 0.004 above the worst relevant question. That is by
design. Related-but-unanswered questions should reach the model, which can
refuse with an explanation, rather than receive a blunt canned reply.

NOT YET MEASURED: text-embedding-3-small (EMBEDDING_PROVIDER=openai), which is
the submission default. The account had no quota when this was written. Cosine
distance is normalised, so the scale transfers better than L2 would, but this
should be re-run on OpenAI before relying on 0.75 there.
--------------------------------------------------------------------------
"""

import os
import statistics
import sys
import tempfile

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ["CHROMA_PERSIST_DIR"] = tempfile.mkdtemp(prefix="distance-measure-")

from app.services import vector_store  # noqa: E402
from app.services.embeddings import embed_texts  # noqa: E402
from app.services.retrieval import retrieve_context  # noqa: E402
from app.config import settings  # noqa: E402

USER_ID = 1

DOCUMENTS = {
    "handbook.md": """
    Employee handbook, Northwind Robotics.
    Annual leave is 25 days plus public holidays. Leave must be requested at
    least two weeks in advance through the internal portal.
    Remote work is permitted up to three days per week with manager approval.
    The core hours during which everyone must be reachable are 10:00 to 16:00.
    """,
    "expenses.md": """
    Expense policy.
    Meals during business travel are reimbursed up to 40 euro per day.
    Taxi fares are reimbursed only when public transport is unavailable or
    unsafe. Receipts must be submitted within 30 days of the expense.
    Flights over six hours may be booked in premium economy.
    """,
    "security.md": """
    Security practices.
    All laptops must have full-disk encryption enabled before first use.
    Passwords must be at least 14 characters and stored in the company password
    manager. Two-factor authentication is mandatory for all production systems.
    Report a suspected phishing email to security@northwind.example.
    """,
}

QUESTIONS = {
    "relevant": [
        "How many days of annual leave do I get?",
        "How much can I claim for meals when travelling?",
        "Do I need two-factor authentication?",
        "What are the core hours?",
        "How long do I have to submit receipts?",
        "Can I work remotely?",
    ],
    "near-miss": [
        "What is the parental leave policy?",
        "Can I expense a hotel minibar?",
        "How often are passwords rotated?",
        "What is the policy on sabbaticals?",
    ],
    "off-topic": [
        "What is the alpha project launch code?",
        "How do I grow tomatoes?",
        "Who won the 1998 World Cup?",
        "Write me a Python function that sorts a list.",
        "What is the capital of Mongolia?",
    ],
}


def chunk(text: str) -> list[str]:
    """Paragraph-ish chunks, close enough to the real chunker for this purpose."""
    return [line.strip() for line in text.strip().splitlines() if line.strip()]


def main() -> None:
    print(f"provider  : {settings.embedding_provider}")
    print("metric    : cosine distance (1 - cosine similarity), range [0, 2]")

    total_chunks = 0
    for doc_id, (filename, body) in enumerate(DOCUMENTS.items(), start=1):
        pieces = chunk(body)
        vector_store.add_document_chunks(
            user_id=USER_ID,
            document_id=doc_id,
            filename=filename,
            chunks=pieces,
            embeddings=embed_texts(pieces),
        )
        total_chunks += len(pieces)

    print(f"corpus    : {total_chunks} chunks across {len(DOCUMENTS)} documents\n")

    summary: dict[str, list[float]] = {}
    for label, questions in QUESTIONS.items():
        print(f"--- {label} ---")
        best_distances = []

        for question in questions:
            # max_distance=0 disables filtering, so the raw numbers are visible
            # rather than the threshold hiding the very data used to pick it.
            chunks = retrieve_context(USER_ID, question, limit=5, max_distance=0)
            distances = [c.distance for c in chunks if c.distance is not None]
            if not distances:
                print(f"  {question[:52]:54} (no hits)")
                continue

            best = min(distances)
            best_distances.append(best)
            spread = f"{min(distances):.4f} .. {max(distances):.4f}"
            print(f"  {question[:52]:54} best={best:.4f}  top5={spread}")

        summary[label] = best_distances
        if best_distances:
            print(
                f"  => best-hit distance: min={min(best_distances):.4f} "
                f"median={statistics.median(best_distances):.4f} "
                f"max={max(best_distances):.4f}\n"
            )

    print("=== separation ===")
    relevant_max = max(summary["relevant"])
    offtopic_min = min(summary["off-topic"])
    nearmiss_min = min(summary["near-miss"])
    print(f"worst relevant question  : {relevant_max:.4f}")
    print(f"best near-miss question  : {nearmiss_min:.4f}")
    print(f"best off-topic question  : {offtopic_min:.4f}")
    print(f"gap relevant -> off-topic: {offtopic_min - relevant_max:+.4f}")
    print(f"configured threshold     : {settings.retrieval_max_distance}")

    if offtopic_min > relevant_max:
        print(
            f"\nA threshold anywhere in ({relevant_max:.4f}, {offtopic_min:.4f}) "
            "separates relevant from off-topic on this corpus."
        )
    else:
        print("\nNO CLEAN SEPARATION: the bands overlap on this corpus.")


if __name__ == "__main__":
    sys.exit(main())
