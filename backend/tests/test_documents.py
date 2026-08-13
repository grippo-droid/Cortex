"""T2.1, T2.2, T2.5 — upload, extraction, listing, and per-user scoping."""

import io

import pytest
from pypdf import PdfWriter

from app.config import settings
from app.models import Document
from tests.conftest import register

SAMPLE = "Cortex keeps each tenant's documents apart. " * 40


def upload_file(client, headers, filename, content: bytes):
    return client.post(
        "/documents",
        headers=headers,
        files={"file": (filename, io.BytesIO(content), "application/octet-stream")},
    )


def upload_text(client, headers, text: str):
    return client.post("/documents", headers=headers, data={"text": text})


def make_pdf(pages: int = 1) -> bytes:
    """A structurally valid PDF. pypdf writes no text layer, so it has none."""
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)

    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


# --------------------------------------------------------------------------
# Uploading
# --------------------------------------------------------------------------


def test_upload_txt_creates_a_ready_document(client):
    alice = register(client, "alice@example.com")

    response = upload_file(client, alice["headers"], "notes.txt", SAMPLE.encode())

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["filename"] == "notes.txt"
    assert body["status"] == "ready"
    assert body["chunk_count"] >= 1


def test_upload_markdown_is_accepted(client):
    alice = register(client, "alice@example.com")

    response = upload_file(client, alice["headers"], "readme.md", b"# Title\n\nBody.")

    assert response.status_code == 201


def test_raw_text_is_accepted(client):
    alice = register(client, "alice@example.com")

    response = upload_text(client, alice["headers"], SAMPLE)

    assert response.status_code == 201
    assert response.json()["filename"] == "pasted-text.txt"


def test_upload_requires_authentication(client):
    response = upload_file(client, {}, "notes.txt", SAMPLE.encode())

    assert response.status_code == 401


@pytest.mark.parametrize("filename", ["payload.exe", "archive.zip", "photo.png", "noext"])
def test_disallowed_extensions_are_rejected(client, filename):
    alice = register(client, "alice@example.com")

    response = upload_file(client, alice["headers"], filename, b"content here")

    assert response.status_code == 415


def test_content_type_cannot_smuggle_a_disallowed_type(client):
    """The allow-list keys off the filename, not the client's declared type."""
    alice = register(client, "alice@example.com")

    response = client.post(
        "/documents",
        headers=alice["headers"],
        files={"file": ("payload.exe", io.BytesIO(b"data"), "text/plain")},
    )

    assert response.status_code == 415


def test_providing_both_file_and_text_is_rejected(client):
    alice = register(client, "alice@example.com")

    response = client.post(
        "/documents",
        headers=alice["headers"],
        files={"file": ("notes.txt", io.BytesIO(b"hello there"), "text/plain")},
        data={"text": "also this"},
    )

    assert response.status_code == 422


def test_providing_neither_file_nor_text_is_rejected(client):
    alice = register(client, "alice@example.com")

    assert client.post("/documents", headers=alice["headers"]).status_code == 422


def test_empty_file_is_rejected(client):
    alice = register(client, "alice@example.com")

    assert upload_file(client, alice["headers"], "empty.txt", b"").status_code == 422


def test_whitespace_only_text_is_rejected(client):
    alice = register(client, "alice@example.com")

    assert upload_text(client, alice["headers"], "   \n\t  ").status_code == 422


def test_oversized_file_is_rejected(client):
    alice = register(client, "alice@example.com")
    oversized = b"x" * (settings.max_upload_bytes + 1024)

    response = upload_file(client, alice["headers"], "big.txt", oversized)

    assert response.status_code == 413


def test_non_utf8_bytes_do_not_crash(client):
    """Undecodable bytes must degrade, not surface as a 500."""
    alice = register(client, "alice@example.com")

    response = upload_file(
        client, alice["headers"], "latin.txt", b"caf\xe9 " + SAMPLE.encode()
    )

    assert response.status_code == 201


def test_path_traversal_in_filename_is_stripped(client, db):
    alice = register(client, "alice@example.com")

    response = upload_file(
        client, alice["headers"], "../../../etc/passwd.txt", SAMPLE.encode()
    )

    assert response.status_code == 201
    stored = response.json()["filename"]
    assert stored == "passwd.txt"
    assert "/" not in stored and ".." not in stored


def test_windows_path_in_filename_is_stripped(client):
    alice = register(client, "alice@example.com")

    response = upload_file(
        client, alice["headers"], r"C:\Users\admin\secret.txt", SAMPLE.encode()
    )

    assert response.status_code == 201
    assert response.json()["filename"] == "secret.txt"


def test_absurdly_long_filename_is_truncated(client):
    alice = register(client, "alice@example.com")

    response = upload_file(
        client, alice["headers"], "a" * 400 + ".txt", SAMPLE.encode()
    )

    assert response.status_code == 201
    assert len(response.json()["filename"]) <= 255


# --------------------------------------------------------------------------
# PDF extraction (T2.2)
# --------------------------------------------------------------------------


def test_pdf_without_a_text_layer_is_rejected_clearly(client):
    """Scanned PDFs need OCR; the message must say so rather than 500."""
    alice = register(client, "alice@example.com")

    response = upload_file(client, alice["headers"], "scan.pdf", make_pdf())

    assert response.status_code == 422
    assert "no text" in response.json()["detail"].lower()


def test_corrupt_pdf_is_rejected_not_crashed(client):
    alice = register(client, "alice@example.com")

    response = upload_file(client, alice["headers"], "broken.pdf", b"%PDF-1.4 garbage")

    assert response.status_code == 422


# --------------------------------------------------------------------------
# Listing, reading, deleting — all scoped to the owner
# --------------------------------------------------------------------------


def test_list_returns_only_the_callers_documents(client):
    alice = register(client, "alice@example.com")
    bob = register(client, "bob@example.com")

    upload_file(client, alice["headers"], "alice-notes.txt", SAMPLE.encode())
    upload_file(client, bob["headers"], "bob-notes.txt", SAMPLE.encode())

    alice_list = client.get("/documents", headers=alice["headers"]).json()
    bob_list = client.get("/documents", headers=bob["headers"]).json()

    assert [item["filename"] for item in alice_list] == ["alice-notes.txt"]
    assert [item["filename"] for item in bob_list] == ["bob-notes.txt"]


def test_list_requires_authentication(client):
    assert client.get("/documents").status_code == 401


def test_new_user_sees_an_empty_list(client):
    alice = register(client, "alice@example.com")

    assert client.get("/documents", headers=alice["headers"]).json() == []


def test_documents_are_stored_against_their_owner(client, db):
    alice = register(client, "alice@example.com")
    bob = register(client, "bob@example.com")

    upload_file(client, alice["headers"], "alice.txt", SAMPLE.encode())
    upload_file(client, bob["headers"], "bob.txt", SAMPLE.encode())

    rows = {doc.filename: doc.user_id for doc in db.query(Document).all()}
    assert rows["alice.txt"] == alice["user"]["id"]
    assert rows["bob.txt"] == bob["user"]["id"]


def test_reading_another_users_document_by_id_returns_404(client):
    """Enumerating ids must not reveal that someone else's document exists."""
    alice = register(client, "alice@example.com")
    bob = register(client, "bob@example.com")

    alice_doc_id = upload_file(
        client, alice["headers"], "alice.txt", SAMPLE.encode()
    ).json()["id"]

    response = client.get(f"/documents/{alice_doc_id}", headers=bob["headers"])

    assert response.status_code == 404


def test_missing_and_forbidden_documents_are_indistinguishable(client):
    alice = register(client, "alice@example.com")
    bob = register(client, "bob@example.com")

    alice_doc_id = upload_file(
        client, alice["headers"], "alice.txt", SAMPLE.encode()
    ).json()["id"]

    forbidden = client.get(f"/documents/{alice_doc_id}", headers=bob["headers"])
    missing = client.get("/documents/999999", headers=bob["headers"])

    assert forbidden.status_code == missing.status_code == 404
    assert forbidden.json() == missing.json()


def test_owner_can_read_their_own_document(client):
    alice = register(client, "alice@example.com")

    document_id = upload_file(
        client, alice["headers"], "alice.txt", SAMPLE.encode()
    ).json()["id"]

    response = client.get(f"/documents/{document_id}", headers=alice["headers"])

    assert response.status_code == 200
    assert response.json()["filename"] == "alice.txt"


def test_deleting_another_users_document_is_refused(client):
    alice = register(client, "alice@example.com")
    bob = register(client, "bob@example.com")

    alice_doc_id = upload_file(
        client, alice["headers"], "alice.txt", SAMPLE.encode()
    ).json()["id"]

    response = client.delete(f"/documents/{alice_doc_id}", headers=bob["headers"])

    assert response.status_code == 404
    # And Alice's document is untouched.
    assert client.get(f"/documents/{alice_doc_id}", headers=alice["headers"]).status_code == 200


def test_embedding_failure_marks_the_document_failed(client, db):
    """A provider outage or exhausted quota must not look like success."""
    from app.services.embeddings import EmbeddingError, set_embedding_provider

    class FailingProvider:
        def embed(self, texts):
            raise EmbeddingError("You have no credits remaining.")

    alice = register(client, "alice@example.com")
    set_embedding_provider(FailingProvider())

    response = upload_text(client, alice["headers"], SAMPLE)

    assert response.status_code == 502
    stored = db.query(Document).one()
    assert stored.status == "failed"
    assert stored.chunk_count == 0


def test_a_failed_document_still_appears_in_the_list(client):
    """The dashboard needs to show the failure rather than silently drop it."""
    from app.services.embeddings import EmbeddingError, set_embedding_provider

    class FailingProvider:
        def embed(self, texts):
            raise EmbeddingError("provider unavailable")

    alice = register(client, "alice@example.com")
    set_embedding_provider(FailingProvider())
    upload_text(client, alice["headers"], SAMPLE)

    listed = client.get("/documents", headers=alice["headers"]).json()

    assert len(listed) == 1
    assert listed[0]["status"] == "failed"


def test_owner_can_delete_their_document(client):
    alice = register(client, "alice@example.com")

    document_id = upload_file(
        client, alice["headers"], "alice.txt", SAMPLE.encode()
    ).json()["id"]

    assert client.delete(f"/documents/{document_id}", headers=alice["headers"]).status_code == 204
    assert client.get("/documents", headers=alice["headers"]).json() == []
