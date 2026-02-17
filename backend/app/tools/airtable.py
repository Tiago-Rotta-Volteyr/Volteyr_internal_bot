"""
Airtable tool: list, search, or query records with optional sort (e.g. "who paid the most" → sort by amount desc).
"""

from typing import Literal, Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field, field_validator

from app.core.config import AIRTABLE_API_KEY, AIRTABLE_BASE_ID, AIRTABLE_TABLE_NAMES
from app.tools.utils import get_primary_field_name, get_table_field_names


def _get_valid_table_names() -> list[str]:
    """Return list of allowed table names for validation and description."""
    return list(AIRTABLE_TABLE_NAMES) if AIRTABLE_TABLE_NAMES else []


class SearchAirtableInput(BaseModel):
    """Input for search_airtable tool. Use the DATABASE SCHEMA to choose table_name and sort_by field names."""

    query: str = Field(
        description="Search term, or leave empty to list records (optionally sorted). For 'who paid the most' use empty query + sort_by=amount field (e.g. CTV) + sort_direction='desc'."
    )
    table_name: str = Field(
        description=f"Target table. Must be one of: {', '.join(_get_valid_table_names()) or 'none configured'}"
    )
    sort_by: Optional[str] = Field(
        default=None,
        description="Field name to sort by (must exist in the table schema, e.g. 'CTV', 'Nom', 'Date'). Use for max/min questions: 'who paid the most' → sort_by='CTV', sort_direction='desc'."
    )
    sort_direction: Optional[Literal["asc", "desc"]] = Field(
        default=None,
        description="'desc' for highest first (e.g. who paid the most), 'asc' for lowest first. Required when sort_by is set."
    )
    max_records: Optional[int] = Field(
        default=None,
        description="Max number of records to return. For 'the one who paid the most' use 1; for top 5 use 5. Default 100 when listing, 10 when searching."
    )

    @field_validator("table_name")
    @classmethod
    def table_must_be_configured(cls, v: str) -> str:
        valid = _get_valid_table_names()
        if not valid:
            return v
        if v in valid:
            return v
        v_lower = (v or "").strip().lower()
        for name in valid:
            if name.lower() == v_lower:
                return name
        raise ValueError(f"table_name must be one of: {', '.join(valid)}")


def _is_list_all_intent(query: str) -> bool:
    """True if the user wants to list all records (no search filter)."""
    q = (query or "").strip().lower()
    if not q:
        return True
    return q in ("*", "all", "tous", "toutes", "liste", "list")

def _build_sort_param(sort_by: Optional[str], sort_direction: Optional[str]) -> Optional[list]:
    """Build pyairtable sort list: ['Field'] for asc, ['-Field'] for desc."""
    if not sort_by or not sort_by.strip():
        return None
    direction = (sort_direction or "asc").strip().lower()
    prefix = "-" if direction == "desc" else ""
    return [f"{prefix}{sort_by.strip()}"]


@tool(args_schema=SearchAirtableInput)
def search_airtable(
    query: str,
    table_name: str,
    sort_by: Optional[str] = None,
    sort_direction: Optional[Literal["asc", "desc"]] = None,
    max_records: Optional[int] = None,
) -> str:
    """
    Query Airtable: list records, search by text, or get top/bottom by a field (sort).
    Use the DATABASE SCHEMA to pick the right table and field names.
    - List all: query='', table_name='Client'.
    - Who paid the most: query='', table_name='Client', sort_by='CTV', sort_direction='desc', max_records=1.
    - Search by name: query='Dupont', table_name='Client'.
    """
    if not AIRTABLE_API_KEY or not AIRTABLE_BASE_ID:
        return "Error: Airtable is not configured (missing AIRTABLE_API_KEY or AIRTABLE_BASE_ID)."
    valid_tables = _get_valid_table_names()
    if table_name not in valid_tables:
        return f"Error: table_name must be one of: {', '.join(valid_tables)}."

    try:
        from pyairtable import Api

        api = Api(AIRTABLE_API_KEY)
        table = api.table(AIRTABLE_BASE_ID, table_name)
    except Exception as e:
        return f"Error connecting to Airtable: {e}"

    sort_param = _build_sort_param(sort_by, sort_direction or "asc")
    limit = max_records if max_records is not None and max_records > 0 else None

    # List (with optional sort): empty query → get records, optionally sorted
    if _is_list_all_intent(query):
        try:
            kwargs = {"max_records": limit or 100}
            if sort_param:
                kwargs["sort"] = sort_param
            records = table.all(**kwargs)
            if not records:
                return f"No records in table '{table_name}' (base is empty for this table)."
            return str([r.get("fields", {}) for r in records])
        except Exception as e:
            fields_hint = get_table_field_names(table_name)
            hint = f" Available fields for table '{table_name}': {fields_hint}." if fields_hint else ""
            return f"Error listing table: {e}.{hint}"

    # Text search (sort not supported with formula in same way; we could fetch then sort in Python if needed)
    primary_field = get_primary_field_name(table_name)
    if not primary_field:
        try:
            kwargs = {"max_records": limit or 50}
            if sort_param:
                kwargs["sort"] = sort_param
            records = table.all(**kwargs)
            query_lower = query.strip().lower()
            matches = []
            for r in records:
                fields = r.get("fields") or {}
                for val in fields.values():
                    if val and isinstance(val, str) and query_lower in val.lower():
                        matches.append(fields)
                        break
            if not matches:
                return f"No records matching '{query}' in table '{table_name}'."
            return str(matches[: limit or 10])
        except Exception as e:
            fields_hint = get_table_field_names(table_name)
            hint = f" Available fields: {fields_hint}." if fields_hint else ""
            return f"Error searching table: {e}.{hint}"

    safe_query = query.strip().replace("'", "\\'")
    formula = f"SEARCH(LOWER('{safe_query}'), LOWER({{{primary_field}}}))"
    try:
        kwargs = {"formula": formula, "max_records": limit or 20}
        if sort_param:
            kwargs["sort"] = sort_param
        records = table.all(**kwargs)
    except Exception as e:
        fields_hint = get_table_field_names(table_name)
        hint = f" Available fields for table '{table_name}': {fields_hint}." if fields_hint else ""
        return f"Error running search: {e}.{hint}"

    if not records:
        return f"No records matching '{query}' in table '{table_name}'."
    return str([r.get("fields", {}) for r in records[: limit or 10]])
