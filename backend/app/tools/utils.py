"""
Helpers for tools: schema inspection (multi-table), primary field resolution,
link field config for resolving linked record IDs to display names.
Relations (links + lookups) are discovered automatically from the raw Airtable schema.
"""
import json
import logging
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from app.core.config import (
    AIRTABLE_BASE_ID,
    AIRTABLE_API_KEY,
    AIRTABLE_TABLE_NAMES,
    AIRTABLE_LINK_DISPLAY_FIELDS,
    AIRTABLE_LINK_FIELD_DISPLAY,
)

LOG = logging.getLogger(__name__)


def _fetch_raw_base_schema(base_id: str, api_key: str) -> Optional[Dict[str, Any]]:
    """Fetch full base schema as raw JSON from Metadata API. Returns None on error."""
    if not base_id or not api_key:
        return None
    url = f"https://api.airtable.com/v0/meta/bases/{base_id}/tables"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {api_key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        LOG.warning("_fetch_raw_base_schema failed: %s", e)
        return None


def fetch_all_tables_metadata(base_id: str, api_key: str) -> List[str]:
    """
    Fetch the list of table names from the Airtable Metadata API
    (GET https://api.airtable.com/v0/meta/bases/{baseId}/tables).
    Returns names only, e.g. ['Client', 'Projet', 'Facture'].

    If the API returns 403 (missing schema.bases:read scope) or any error occurs,
    falls back to AIRTABLE_TABLE_NAMES.
    """
    if not base_id or not api_key:
        return list(AIRTABLE_TABLE_NAMES) if AIRTABLE_TABLE_NAMES else []

    url = f"https://api.airtable.com/v0/meta/bases/{base_id}/tables"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {api_key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        tables = data.get("tables") or []
        return [t.get("name", "") for t in tables if t.get("name")]
    except urllib.error.HTTPError as e:
        if e.code == 403:
            LOG.warning(
                "Airtable Metadata API: scope schema.bases:read missing; "
                "falling back to AIRTABLE_TABLE_NAMES."
            )
        else:
            LOG.warning(
                "Airtable Metadata API error %s; falling back to AIRTABLE_TABLE_NAMES.",
                e.code,
            )
        return list(AIRTABLE_TABLE_NAMES) if AIRTABLE_TABLE_NAMES else []
    except Exception as e:
        LOG.warning(
            "fetch_all_tables_metadata failed: %s; falling back to AIRTABLE_TABLE_NAMES.",
            e,
        )
        return list(AIRTABLE_TABLE_NAMES) if AIRTABLE_TABLE_NAMES else []


def get_table_schema() -> str:
    """
    Fetch schema for each table (from Metadata API or AIRTABLE_TABLE_NAMES fallback)
    and return a single descriptive string for injection into the agent system prompt.
    """
    table_names = fetch_all_tables_metadata(AIRTABLE_BASE_ID, AIRTABLE_API_KEY)
    if not table_names:
        return (
            "DATABASE SCHEMA:\n"
            "(No tables. Configure AIRTABLE_TABLE_NAMES in .env or grant schema.bases:read.)"
        )

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
    for i, table_name in enumerate(table_names, start=1):
        try:
            table_schema = schema.table(table_name)
            field_desc = [f"{f.name} ({f.type})" for f in table_schema.fields]
            lines.append(f"{i}. Table '{table_name}': {field_desc}")
        except Exception:
            lines.append(f"{i}. Table '{table_name}': Fields []")

    return "\n".join(lines)


def get_table_schema_formatted(table_name: str) -> str:
    """
    Return schema for one table as "Nom de la colonne (Type)" per line, for injection into prompts.
    Returns empty string if table not found or Airtable not configured.
    """
    if not AIRTABLE_API_KEY or not AIRTABLE_BASE_ID:
        return ""
    try:
        from pyairtable import Api

        api = Api(AIRTABLE_API_KEY)
        base = api.base(AIRTABLE_BASE_ID)
        schema = base.schema()
        table_schema = schema.table(table_name)
        return "\n".join(f"{f.name} ({f.type})" for f in table_schema.fields)
    except Exception:
        return ""


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
            link_field_key = f"{table_name}.{f.name}"
            display_field = (
                AIRTABLE_LINK_FIELD_DISPLAY.get(link_field_key)
                or AIRTABLE_LINK_DISPLAY_FIELDS.get(linked_table_name)
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


def get_relations_schema() -> str:
    """
    Return a human-readable description of link and lookup fields, discovered
    automatically from the Airtable Metadata API. Includes:
    - multipleRecordLinks: display = primary field of linked table
    - multipleLookupValues: display = field from fieldIdInLinkedTable (e.g. Entreprise)
    """
    raw = _fetch_raw_base_schema(AIRTABLE_BASE_ID, AIRTABLE_API_KEY)
    if not raw:
        return _get_relations_schema_fallback()

    tables: List[Dict[str, Any]] = raw.get("tables") or []
    table_id_to_name: Dict[str, str] = {t["id"]: t["name"] for t in tables if t.get("id") and t.get("name")}

    # Build field_id -> field_name per table
    def field_id_to_name_map(tbl: Dict[str, Any]) -> Dict[str, str]:
        return {f["id"]: f["name"] for f in tbl.get("fields", []) if f.get("id") and f.get("name")}

    # Build link_field_id -> (table_id, linked_table_id) for all link fields
    link_field_to_linked: Dict[str, tuple[str, str]] = {}
    for tbl in tables:
        tid = tbl.get("id")
        if not tid:
            continue
        for f in tbl.get("fields", []):
            if f.get("type") != "multipleRecordLinks":
                continue
            opts = f.get("options") or {}
            lid = opts.get("linkedTableId")
            if lid:
                link_field_to_linked[f["id"]] = (tid, lid)

    lines: List[str] = []
    for tbl in tables:
        table_name = tbl.get("name") or "?"
        table_id = tbl.get("id")
        field_map = field_id_to_name_map(tbl)

        for f in tbl.get("fields", []):
            fname = f.get("name") or "?"
            ftype = f.get("type")
            opts = f.get("options") or {}

            if ftype == "multipleRecordLinks":
                linked_tid = opts.get("linkedTableId")
                if not linked_tid:
                    continue
                linked_name = table_id_to_name.get(linked_tid) or "?"
                link_key = f"{table_name}.{fname}"
                display = (
                    AIRTABLE_LINK_FIELD_DISPLAY.get(link_key)
                    or AIRTABLE_LINK_DISPLAY_FIELDS.get(linked_name)
                    or _primary_field_from_raw(tables, linked_tid)
                    or "Name"
                )
                lines.append(f"  • Table '{table_name}': champ '{fname}' (lien) → table '{linked_name}' (affiche '{display}')")

            elif ftype == "multipleLookupValues":
                record_link_id = opts.get("recordLinkFieldId")
                field_id_in_linked = opts.get("fieldIdInLinkedTable")
                if not record_link_id or not field_id_in_linked:
                    continue
                link_info = link_field_to_linked.get(record_link_id)
                if not link_info:
                    continue
                _source_tid, linked_tid = link_info
                if _source_tid != table_id:
                    continue
                linked_name = table_id_to_name.get(linked_tid) or "?"
                display = _resolve_field_name_in_table(tables, linked_tid, field_id_in_linked) or "?"
                lines.append(f"  • Table '{table_name}': champ '{fname}' (lookup) → table '{linked_name}' (affiche '{display}')")

    return "\n".join(lines) if lines else _get_relations_schema_fallback()


def _primary_field_from_raw(tables: List[Dict[str, Any]], table_id: str) -> Optional[str]:
    """Return primary field name for table_id from raw schema (camelCase keys)."""
    for tbl in tables:
        if tbl.get("id") != table_id:
            continue
        pid = tbl.get("primaryFieldId") or tbl.get("primary_field_id")
        for f in tbl.get("fields", []):
            if f.get("id") == pid:
                return f.get("name")
        if tbl.get("fields"):
            return tbl["fields"][0].get("name")
        return None
    return None


def _resolve_field_name_in_table(
    tables: List[Dict[str, Any]], table_id: str, field_id: str
) -> Optional[str]:
    """Return field name for field_id in the given table."""
    for tbl in tables:
        if tbl.get("id") != table_id:
            continue
        for f in tbl.get("fields", []):
            if f.get("id") == field_id:
                return f.get("name")
        return None
    return None


def get_link_and_lookup_field_names(table_name: str) -> set[str]:
    """
    Return the set of field names that are multipleRecordLinks or multipleLookupValues.
    Used to apply FIND() instead of = when filtering by these fields (FIND works for link/lookup).
    """
    raw = _fetch_raw_base_schema(AIRTABLE_BASE_ID, AIRTABLE_API_KEY)
    if not raw:
        return set()
    for tbl in raw.get("tables") or []:
        if tbl.get("name") != table_name:
            continue
        result: set[str] = set()
        for f in tbl.get("fields") or []:
            if f.get("type") in ("multipleRecordLinks", "multipleLookupValues"):
                if f.get("name"):
                    result.add(f["name"])
        return result
    return set()


def _get_relations_schema_fallback() -> str:
    """Fallback when raw schema unavailable: use get_link_fields_config (pyairtable)."""
    table_names = fetch_all_tables_metadata(AIRTABLE_BASE_ID, AIRTABLE_API_KEY)
    if not table_names:
        return ""
    lines: List[str] = []
    for table_name in table_names:
        for cfg in get_link_fields_config(table_name):
            fn = cfg.get("field_name") or "?"
            ln = cfg.get("linked_table_name") or "?"
            disp = cfg.get("display_field") or "?"
            lines.append(f"  • Table '{table_name}': champ '{fn}' → table '{ln}' (affiche '{disp}')")
    return "\n".join(lines) if lines else ""
