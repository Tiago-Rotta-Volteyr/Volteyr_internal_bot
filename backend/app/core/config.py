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


def _parse_link_display_fields(value: str | None) -> dict[str, str]:
    """
    Parse AIRTABLE_LINK_DISPLAY_FIELDS (e.g. "Client:Entreprise,Projet:Nom") into
    { "Client": "Entreprise", "Projet": "Nom" }.
    """
    if not value or not value.strip():
        return {}
    out: dict[str, str] = {}
    for part in value.split(","):
        part = part.strip()
        if ":" in part:
            table_name, field_name = part.split(":", 1)
            out[table_name.strip()] = field_name.strip()
    return out


def _parse_link_field_display(value: str | None) -> dict[str, str]:
    """
    Parse AIRTABLE_LINK_FIELD_DISPLAY (e.g. "Projet.Client:Nom,Projet.Entreprise:Entreprise")
    into { "Projet.Client": "Nom", "Projet.Entreprise": "Entreprise" }.
    Used when a table has multiple link fields to the same table, each displaying a different
    column (e.g. Client=person names, Entreprise=company names).
    """
    if not value or not value.strip():
        return {}
    out: dict[str, str] = {}
    for part in value.split(","):
        part = part.strip()
        if ":" in part:
            key, display_field = part.rsplit(":", 1)
            out[key.strip()] = display_field.strip()
    return out


AIRTABLE_LINK_DISPLAY_FIELDS: dict[str, str] = _parse_link_display_fields(
    os.getenv("AIRTABLE_LINK_DISPLAY_FIELDS", "")
)
AIRTABLE_LINK_FIELD_DISPLAY: dict[str, str] = _parse_link_field_display(
    os.getenv("AIRTABLE_LINK_FIELD_DISPLAY", "")
)
