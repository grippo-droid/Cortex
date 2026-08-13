"""T2.4 — per-user vector store isolation.

These are the tests that matter most: they assert that one user's chunks are
unreachable from another user's collection, which is the property the whole
application is graded on.
"""

import io

import pytest

from app.services import vector_store
from app.services.embeddings import embed_texts
from tests.conftest import register

ALICE_SECRET = "The alpha project launch code is HELIOTROPE-9."
BOB_SECRET = "Bob's quarterly revenue was four million euros."


def upload_text(client, headers, text: str):
    return client.post("/documents", headers=headers, data={"text": text})


def upload_file(client, headers, filename, content: bytes):
    return client.post(
        "/documents",
        headers=headers,
        files={"file": (filename, io.BytesIO(content), "text/plain")},
    )


# --------------------------------------------------------------------------
# Collection naming
# --------------------------------------------------------------------------


def test_collection_name_is_derived_from_the_user_id():
    assert vector_store.collection_name_for_user(7) == "cortex_user_7"
    assert vector_store.collection_name_for_user(1) != vector_store.collection_name_for_user(2)


@pytest.mark.parametrize("bad", ["7", "cortex_user_1", "../escape", None, True, 1.5])
def test_collection_name_rejects_non_integer_ids(bad):
    """A string here would let a caller address an arbitrary collection."""
    with pytest.raises(TypeError):
        vector_store.collection_name_for_user(bad)


# --------------------------------------------------------------------------
# Cross-tenant reachability
# --------------------------------------------------------------------------


def test_one_users_chunks_are_absent_from_another_users_collection(client):
    alice = register(client, "alice@example.com")
    bob = register(client, "bob@example.com")

    upload_text(client, alice["headers"], ALICE_SECRET)
    upload_text(client, bob["headers"], BOB_SECRET)

    alice_id = alice["user"]["id"]
    bob_id = bob["user"]["id"]

    # Search Bob's collection with a query embedded from Alice's exact secret.
    query = embed_texts([ALICE_SECRET])[0]
    bob_hits = vector_store.query_user_chunks(bob_id, query, limit=10)
    alice_hits = vector_store.query_user_chunks(alice_id, query, limit=10)

    assert all("HELIOTROPE" not in hit["content"] for hit in bob_hits)
    assert any("HELIOTROPE" in hit["content"] for hit in alice_hits)


def test_a_user_with_no_documents_retrieves_nothing(client):
    alice = register(client, "alice@example.com")
    bob = register(client, "bob@example.com")

    upload_text(client, alice["headers"], ALICE_SECRET)

    query = embed_texts([ALICE_SECRET])[0]

    assert vector_store.query_user_chunks(bob["user"]["id"], query, limit=10) == []


def test_chunk_metadata_records_the_source_document(client):
    alice = register(client, "alice@example.com")

    document_id = upload_file(
        client, alice["headers"], "brief.txt", ALICE_SECRET.encode()
    ).json()["id"]

    hits = vector_store.query_user_chunks(
        alice["user"]["id"], embed_texts([ALICE_SECRET])[0], limit=5
    )

    assert hits
    assert hits[0]["metadata"]["document_id"] == document_id
    assert hits[0]["metadata"]["filename"] == "brief.txt"


def test_deleting_a_document_removes_its_vectors(client):
    alice = register(client, "alice@example.com")

    document_id = upload_text(client, alice["headers"], ALICE_SECRET).json()["id"]
    alice_id = alice["user"]["id"]

    query = embed_texts([ALICE_SECRET])[0]
    assert vector_store.query_user_chunks(alice_id, query, limit=10)

    client.delete(f"/documents/{document_id}", headers=alice["headers"])

    remaining = vector_store.query_user_chunks(alice_id, query, limit=10)
    assert all("HELIOTROPE" not in hit["content"] for hit in remaining)


def test_deleting_one_document_leaves_the_others(client):
    alice = register(client, "alice@example.com")

    first = upload_text(client, alice["headers"], ALICE_SECRET).json()["id"]
    upload_text(client, alice["headers"], "A second unrelated note about gardening.")

    client.delete(f"/documents/{first}", headers=alice["headers"])

    hits = vector_store.query_user_chunks(
        alice["user"]["id"], embed_texts(["gardening"])[0], limit=10
    )
    assert any("gardening" in hit["content"] for hit in hits)


def test_each_user_gets_their_own_collection(client):
    alice = register(client, "alice@example.com")
    bob = register(client, "bob@example.com")

    upload_text(client, alice["headers"], ALICE_SECRET)
    upload_text(client, bob["headers"], BOB_SECRET)

    names = {collection.name for collection in vector_store._get_client().list_collections()}

    assert vector_store.collection_name_for_user(alice["user"]["id"]) in names
    assert vector_store.collection_name_for_user(bob["user"]["id"]) in names


def test_chunk_count_matches_what_was_stored(client):
    alice = register(client, "alice@example.com")
    long_text = "Paragraph about isolation. " * 400

    document = upload_text(client, alice["headers"], long_text).json()

    hits = vector_store.query_user_chunks(
        alice["user"]["id"], embed_texts(["isolation"])[0], limit=100
    )

    assert document["chunk_count"] > 1
    assert len(hits) == document["chunk_count"]
