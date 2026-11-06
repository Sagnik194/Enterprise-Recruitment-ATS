
from app.supabase_storage import (
    upload_pdf,
    get_signed_document_url,
    delete_document
)

# Small test-only PDF header.
# This tests the storage connection, not full PDF parsing.
test_pdf = b"%PDF-1.4\n%ATS test file\n"

storage_key = upload_pdf(
    test_pdf,
    "resumes"
)

print("Upload successful!")
print("Storage key:", storage_key)

signed_url = get_signed_document_url(storage_key)

print("Signed URL generated:", bool(signed_url))

delete_document(storage_key)

print("Test document deletion requested!")
