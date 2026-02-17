"""
Application configuration from environment variables.
"""
import os
from typing import List

from dotenv import load_dotenv

load_dotenv()


def _parse_table_names(value: str | None) -> List[str]:
    """Parse AIRTABLE_TABLE_NAMES (comma-separated) into a list of trimmed strings."""
    if not value or not value.strip():
        return []
    return [name.strip() for name in value.split(",") if name.strip()]


# Supabase (API auth: either JWT Secret for local verify, or URL+Key for auth.getUser)
SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY: str = os.getenv("SUPABASE_KEY", "")  # anon (publishable) or service (secret)
SUPABASE_JWT_SECRET: str = os.getenv("SUPABASE_JWT_SECRET", "")  # optional; if set, used for fast local JWT verify

# Airtable
AIRTABLE_API_KEY: str = os.getenv("AIRTABLE_API_KEY", "")
AIRTABLE_BASE_ID: str = os.getenv("AIRTABLE_BASE_ID", "")
AIRTABLE_TABLE_NAMES: List[str] = _parse_table_names(os.getenv("AIRTABLE_TABLE_NAMES", ""))
