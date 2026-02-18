"""
Helpers for tools: schema inspection (multi-table), primary field resolution,
link field config for resolving linked record IDs to display names.
"""
from typing import Any, List, Optional

from app.core.config import (
    AIRTABLE_BASE_ID,
    AIRTABLE_API_KEY,
    AIRTABLE_TABLE_NAMES,
    AIRTABLE_LINK_DISPLAY_FIELDS,
)


def get_table_schema() -> str:
    """
    Fetch schema for each table in AIRTABLE_TABLE_NAMES and return a single
    descriptive string for injection into the agent system prompt.
    Format:
        DATABASE SCHEMA:
        1. Table 'Clients': Fields [Name, Status, Email]
        2. Table 'Projets': Fields [Project_Name, Client_Link, Deadline]
        ...
    """
    if not AIRTABLE_TABLE_NAMES:
        return "DATABASE SCHEMA:\n(No tables configured. Set AIRTABLE_TABLE_NAMES in .env.)"

    if not AIRTABLE_API_KEY or not AIRTABLE_BASE_ID:
        return (
            "DATABASE SCHEMA:\n"
            "(Airtable not configured. Set AIRTABLE_API_KEY and AIRTABLE_BASE_ID.)"
        )

    try:
        from pyairtable import Api

        api = Api(AIRTABLE_API_KEY)
        base = api.base(AIRTABLE_BASE_ID)
        schema = base.schema()
    except Exception as e:
        return f"DATABASE SCHEMA:\n(Error loading Airtable schema: {e})"

    lines = [
        "DATABASE SCHEMA (use these exact table and field names in the Airtable tool):",
        "",
    ]
    for i, table_name in enumerate(AIRTABLE_TABLE_NAMES, start=1):
        try:
            table_schema = schema.table(table_name)
            # Include field type so the agent knows which field is amount/number for sort (e.g. CTV)
            field_desc = [f"{f.name} ({f.type})" for f in table_schema.fields]
            lines.append(f"{i}. Table '{table_name}': {field_desc}")
        except Exception:
            lines.append(f"{i}. Table '{table_name}': Fields []")

    return "\n".join(lines)


def get_table_field_names(table_name: str) -> List[str]:
    """Return list of field names for the table (for error messages / self-correction)."""
    if not AIRTABLE_API_KEY or not AIRTABLE_BASE_ID:
        return []
    try:
        from pyairtable import Api

        api = Api(AIRTABLE_API_KEY)
        base = api.base(AIRTABLE_BASE_ID)
        schema = base.schema()
        table_schema = schema.table(table_name)
        return [f.name for f in table_schema.fields]
    except Exception:
        return []


def get_primary_field_name(table_name: str) -> Optional[str]:
    """
    Return the primary field name for the given table (for SEARCH formula).
    Returns None if table not found or schema unavailable.
    """
    if not AIRTABLE_API_KEY or not AIRTABLE_BASE_ID:
        return None
    try:
        from pyairtable import Api

        api = Api(AIRTABLE_API_KEY)
        base = api.base(AIRTABLE_BASE_ID)
        schema = base.schema()
        table_schema = schema.table(table_name)
        primary_id = table_schema.primary_field_id
        for f in table_schema.fields:
            if f.id == primary_id:
                return f.name
        # Fallback: first field
        if table_schema.fields:
            return table_schema.fields[0].name
        return None
    except Exception:
        return None


def get_link_fields_config(table_name: str) -> List[dict[str, Any]]:
    """
    Return config for link fields in the given table: for each field of type
    multipleRecordLinks, return {field_name, linked_table_name, display_field}.
    display_field is the field to show from the linked record (from
    AIRTABLE_LINK_DISPLAY_FIELDS or primary field of linked table).
    """
    if not AIRTABLE_API_KEY or not AIRTABLE_BASE_ID:
        return []
    try:
        from pyairtable import Api

        api = Api(AIRTABLE_API_KEY)
        base = api.base(AIRTABLE_BASE_ID)
        schema = base.schema()
        # Build table_id -> table name (schema.tables = list of TableSchema with id, name)
        table_id_to_name: dict[str, str] = {}
        for t in schema.tables:
            table_id_to_name[t.id] = t.name
        table_schema = schema.table(table_name)
        result: List[dict[str, Any]] = []
        for f in table_schema.fields:
            if getattr(f, "type", None) != "multipleRecordLinks":
                continue
            options = getattr(f, "options", None)
            linked_table_id = getattr(options, "linked_table_id", None) if options else None
            if not linked_table_id:
                continue
            linked_table_name = table_id_to_name.get(linked_table_id)
            if not linked_table_name:
                continue
            display_field = (
                AIRTABLE_LINK_DISPLAY_FIELDS.get(linked_table_name)
                or get_primary_field_name(linked_table_name)
                or "Name"
            )
            result.append({
                "field_name": f.name,
                "linked_table_name": linked_table_name,
                "display_field": display_field,
            })
        return result
    except Exception:
        return []
