
import os
import uuid

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY")
BUCKET_NAME = os.getenv(
    "SUPABASE_STORAGE_BUCKET",
    "candidate-documents"
)

MAX_FILE_SIZE = 5 * 1024 * 1024


def get_supabase():
    if not SUPABASE_URL or not SUPABASE_SECRET_KEY:
        raise RuntimeError(
            "Supabase environment variables are missing"
        )

    return create_client(
        SUPABASE_URL,
        SUPABASE_SECRET_KEY
    )


def upload_pdf(file_bytes, document_type):
    """Upload a validated PDF to private Supabase Storage."""

    if document_type not in {"resumes", "certificates"}:
        raise ValueError("Invalid document type")

    if not file_bytes:
        raise ValueError("File is empty")

    if len(file_bytes) > MAX_FILE_SIZE:
        raise ValueError("Maximum file size is 5 MB")

    if not file_bytes.startswith(b"%PDF-"):
        raise ValueError("Only valid PDF files are allowed")

    storage_key = (
        f"{document_type}/{uuid.uuid4().hex}.pdf"
    )

    supabase = get_supabase()

    supabase.storage.from_(BUCKET_NAME).upload(
        path=storage_key,
        file=file_bytes,
        file_options={
            "content-type": "application/pdf",
            "upsert": "false"
        }
    )

    return storage_key


def get_signed_document_url(storage_key):
    """Generate a temporary URL for an authorized user."""

    supabase = get_supabase()

    result = supabase.storage.from_(
        BUCKET_NAME
    ).create_signed_url(
        path=storage_key,
        expires_in=60
    )

    return result["signedURL"]


def delete_document(storage_key):
    """Remove a document from Supabase Storage."""

    supabase = get_supabase()

    return supabase.storage.from_(
        BUCKET_NAME
    ).remove([storage_key])
