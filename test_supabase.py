import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_SECRET_KEY")
bucket = os.getenv("SUPABASE_STORAGE_BUCKET")

if not url or not key or not bucket:
    raise RuntimeError("Supabase environment variables are missing")

supabase = create_client(url, key)

print("Connecting to Supabase...")

buckets = supabase.storage.list_buckets()

for item in buckets:
    print("Bucket:", item.name)

if any(item.name == bucket for item in buckets):
    print("SUCCESS: Candidate documents bucket found!")
else:
    print("ERROR: Candidate documents bucket not found.")