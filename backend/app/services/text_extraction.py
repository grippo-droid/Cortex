"""Turn an uploaded file into plain text, with the input validation that implies."""

import io
from pathlib import PurePosixPath

from pypdf import PdfReader
from pypdf.errors import PyPdfError

PLAIN_TEXT_EXTENSIONS = {".txt", ".md"}
PDF_EXTENSIONS = {".pdf"}
ALLOWED_EXTENSIONS = PLAIN_TEXT_EXTENSIONS | PDF_EXTENSIONS

MAX_FILENAME_LENGTH = 255


class UnsupportedFileTypeError(Exception):
    """The extension is not on the allow-list."""


class ExtractionError(Exception):
    """The file matched an allowed type but no text could be read from it."""


def sanitise_filename(raw: str) -> str:
    """Reduce a client-supplied filename to a bare, bounded name.

    The client controls this string, and it ends up in the database, in vector
    store metadata, and rendered in the dashboard. Directory components are
    stripped so it can never be read as a path, and both separators are handled
    because a Windows client will happily send backslashes.
    """
    name = raw.replace("\\", "/").rsplit("/", 1)[-1]
    name = name.replace("\x00", "").strip()

    if not name or name in {".", ".."}:
        raise ExtractionError("The uploaded file has no usable filename.")

    if len(name) > MAX_FILENAME_LENGTH:
        suffix = PurePosixPath(name).suffix[:32]
        name = name[: MAX_FILENAME_LENGTH - len(suffix)] + suffix

    return name


def extension_of(filename: str) -> str:
    return PurePosixPath(filename).suffix.lower()


def ensure_supported(filename: str) -> str:
    """Validate the extension server-side.

    Deliberately keyed off the filename rather than the declared content type,
    which the client can set to anything it likes.
    """
    extension = extension_of(filename)

    if extension not in ALLOWED_EXTENSIONS:
        raise UnsupportedFileTypeError(
            f"Unsupported file type '{extension or 'unknown'}'. "
            f"Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}."
        )

    return extension


def _extract_pdf(data: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(data))

        if reader.is_encrypted:
            # An empty-password decrypt covers PDFs that are "encrypted" only
            # with an owner password, which is common and harmless.
            try:
                if reader.decrypt("") == 0:
                    raise ExtractionError(
                        "This PDF is password protected and cannot be read."
                    )
            except PyPdfError as exc:
                raise ExtractionError(
                    "This PDF is password protected and cannot be read."
                ) from exc

        pages = [page.extract_text() or "" for page in reader.pages]
    except ExtractionError:
        raise
    except Exception as exc:
        # pypdf raises a wide range of types on malformed input; none of them
        # should surface as a 500.
        raise ExtractionError("This PDF could not be read. It may be corrupt.") from exc

    text = "\n\n".join(page.strip() for page in pages if page.strip())

    if not text.strip():
        raise ExtractionError(
            "No text could be extracted from this PDF. Scanned documents need "
            "OCR, which is not supported."
        )

    return text


def extract_text(filename: str, data: bytes) -> str:
    """Extract plain text from an uploaded file's bytes."""
    extension = ensure_supported(filename)

    if extension in PDF_EXTENSIONS:
        return _extract_pdf(data)

    # A .txt file is not guaranteed to be UTF-8. Replacing undecodable bytes
    # keeps a mostly-readable document usable instead of failing the upload.
    text = data.decode("utf-8", errors="replace")

    if not text.strip():
        raise ExtractionError("The uploaded file is empty.")

    return text
