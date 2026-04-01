# Design: strict-tools-schema-fix

**Status**: ready  
**Change**: Replace `dict[str, Any]` with typed Pydantic models in tool schemas for OpenAI strict mode compatibility  
**Files touched**: 3 (`customer_tools.py`, `info_tools.py`, `booking_tools.py`)

---

## Technical Approach

OpenAI strict mode (`strict: True` in `base.py:487`) rejects schemas containing `dict[str, Any]` because `additionalProperties` must be `false` and all properties must be explicitly declared. The fix replaces the two offending `dict` fields with flat Pydantic `BaseModel` subclasses whose properties mirror exactly what the existing code reads. This is a mechanical refactor — no behavioral change, no new features.

For `booking_tools.py`, the `BookSchema` already declares `last_name` and `notes` with `default=None`, but the `book()` function signature omits the `= None` defaults. Strict mode requires the function signature to match the schema defaults, otherwise the LLM-generated call may omit these optional fields and Python raises `TypeError`.

The `parse_filters` validator in `QueryInfoSchema` currently deserializes JSON strings into `dict`. After migration it must deserialize into `QueryFilters` instead. Since `QueryFilters` is a Pydantic model, we parse the JSON string with `QueryFilters.model_validate_json(v)` for strings and `QueryFilters.model_validate(v)` for dicts.

---

## Change 1: `CustomerData` model — `customer_tools.py`

### New model (insert before `ManageCustomerSchema`, ~line 74)

```python
class CustomerData(BaseModel):
    """Typed data payload for customer create/update actions."""
    customer_id: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    notes: str | None = None
```

### Schema change

```python
# BEFORE (line 90-97)
data: dict[str, Any] | None = Field(
    default=None,
    description=(...),
)

# AFTER
data: CustomerData | None = Field(
    default=None,
    description=(
        "Additional data for the action:\n"
        "For 'create': {first_name: str (required), last_name: str (optional), notes: str (optional)}\n"
        "For 'update': {customer_id: str (optional), first_name: str (optional), last_name: str (optional), notes: str (optional)}"
    ),
)
```

### Function signature change (line 114)

```python
# BEFORE
async def manage_customer(
    action: Literal["get", "create", "update"], phone: str, data: dict[str, Any] | None = None
) -> dict[str, Any]:

# AFTER
async def manage_customer(
    action: Literal["get", "create", "update"], phone: str, data: CustomerData | None = None
) -> dict[str, Any]:
```

### Internal function signature changes

```python
# BEFORE (lines 261, 320)
async def _create_customer(phone: str, data: dict[str, Any]) -> dict[str, Any]:
async def _update_customer(phone: str, data: dict[str, Any]) -> dict[str, Any]:

# AFTER
async def _create_customer(phone: str, data: CustomerData) -> dict[str, Any]:
async def _update_customer(phone: str, data: CustomerData) -> dict[str, Any]:
```

### Call-site changes in `_create_customer`

| Line | Before | After |
|------|--------|-------|
| 272 | `first_name = data.get("first_name")` | `first_name = data.first_name` |
| 277 | `last_name = data.get("last_name", "")` | `last_name = data.last_name or ""` |
| 278 | `notes = data.get("notes")` | `notes = data.notes` |

### Call-site changes in `_update_customer`

| Line | Before | After |
|------|--------|-------|
| 328 | `customer_id_str = data.get("customer_id")` | `customer_id_str = data.customer_id` |
| 329 | `first_name = data.get("first_name")` | `first_name = data.first_name` |
| 330 | `last_name = data.get("last_name")` | `last_name = data.last_name` |
| 331 | `notes = data.get("notes")` | `notes = data.notes` |

### Import cleanup

Remove `Any` from `from typing import Any, Literal` → `from typing import Literal` (confirmed: `Any` is only used in `dict[str, Any]` for `data` param and return types; return type annotations `-> dict[str, Any]` still need `Any`, so **keep the import**).

**Correction**: `Any` is still used in return type annotations (`-> dict[str, Any]`) on lines 115, 211, 261, 320, 451. **Do NOT remove the import.**

---

## Change 2: `QueryFilters` model — `info_tools.py`

### New model (insert before `QueryInfoSchema`, ~line 37)

```python
class QueryFilters(BaseModel):
    """Typed filter payload for query_info tool."""
    category: str | None = None
    keywords: list[str] | None = None
```

> Note: `keywords` is `list[str]` because `_get_faqs` iterates over it with `any(kw in faq_keywords for kw in requested_keywords)`.

### Schema change

```python
# BEFORE (line 50-57)
filters: dict[str, Any] | None = Field(
    default=None,
    description=(...),
)

# AFTER
filters: QueryFilters | None = Field(
    default=None,
    description=(
        "Optional filters for the query:\n"
        "For 'services': {category: 'Peluquería' | 'Estética'}\n"
        "For 'faqs': {keywords: ['hours', 'parking', 'address']}"
    ),
)
```

### Validator migration (`parse_filters`, lines 70-93)

```python
# BEFORE
@field_validator("filters", mode="before")
@classmethod
def parse_filters(cls, v):
    if v is None:
        return None
    if isinstance(v, str):
        try:
            return json.loads(v)
        except json.JSONDecodeError as e:
            raise ValueError(...)
    if isinstance(v, dict):
        return v
    raise ValueError(...)

# AFTER
@field_validator("filters", mode="before")
@classmethod
def parse_filters(cls, v):
    """Parse filters: accept dict, JSON string, or QueryFilters instance."""
    if v is None:
        return None
    if isinstance(v, QueryFilters):
        return v
    if isinstance(v, str):
        try:
            return QueryFilters.model_validate_json(v)
        except Exception as e:
            raise ValueError(
                f"filters must be a valid JSON string or dict, got invalid JSON: {e}"
            )
    if isinstance(v, dict):
        return QueryFilters.model_validate(v)
    raise ValueError(f"filters must be a dict or JSON string, got {type(v).__name__}")
```

### Function signature change (line 99)

```python
# BEFORE
async def query_info(
    type: Literal["services", "faqs", "hours", "location"],
    filters: dict[str, Any] | None = None,
    max_results: int = 10,
) -> dict[str, Any]:

# AFTER
async def query_info(
    type: Literal["services", "faqs", "hours", "location"],
    filters: QueryFilters | None = None,
    max_results: int = 10,
) -> dict[str, Any]:
```

### Internal function signature changes

The `_get_services` and `_get_faqs` function signatures also need updating (they receive `filters` as a parameter from `query_info`):

```python
# BEFORE (find actual signatures)
async def _get_services(filters: dict[str, Any] | None, max_results: int) -> dict[str, Any]:
async def _get_faqs(filters: dict[str, Any] | None, max_results: int) -> dict[str, Any]:

# AFTER
async def _get_services(filters: QueryFilters | None, max_results: int) -> dict[str, Any]:
async def _get_faqs(filters: QueryFilters | None, max_results: int) -> dict[str, Any]:
```

### Call-site changes in `_get_services`

| Line | Before | After |
|------|--------|-------|
| 204 | `if filters and "category" in filters:` | `if filters and filters.category:` |
| 205 | `category_value = filters["category"]` | `category_value = filters.category` |
| 234 | `filters.get('category')` (logger) | `filters.category` |

### Call-site changes in `_get_faqs`

| Line | Before | After |
|------|--------|-------|
| 282 | `if filters and "keywords" in filters:` | `if filters and filters.keywords:` |
| 283 | `requested_keywords = filters["keywords"]` | `requested_keywords = filters.keywords` |
| 303 | `filters.get('keywords')` (logger) | `filters.keywords` |

### Import cleanup

Remove `Any` from `from typing import Any, Literal`. Check: `Any` is used in return types `-> dict[str, Any]` throughout the file. **Keep the import.**

---

## Change 3: `book()` signature defaults — `booking_tools.py`

### Function signature change (lines 114-115)

```python
# BEFORE
async def book(
    customer_id: str,
    first_name: str,
    last_name: str | None,      # ← missing = None
    notes: str | None,           # ← missing = None
    services: list[str],
    ...

# AFTER
async def book(
    customer_id: str,
    first_name: str,
    last_name: str | None = None,   # ← added default
    notes: str | None = None,       # ← added default
    services: list[str],
    ...
```

> `BookSchema` already has `default=None` on both fields (lines 37-43). This change aligns the function signature to match, preventing `TypeError` when the LLM omits optional params.

---

## Backward Compatibility

- **Zero behavioral change**: The typed models contain exactly the same fields that existing code reads. No new fields, no removed fields.
- **Validator preserved**: `parse_filters` still handles JSON strings from LLMs, but now returns `QueryFilters` instead of `dict`.
- **Return types unchanged**: All functions still return `dict[str, Any]` — only input schemas change.
- **No migration needed**: No database changes, no config changes, no API contract changes.
- **LLM compatibility**: The generated JSON schema will have `additionalProperties: false` with all properties explicitly listed — this is what strict mode requires.

---

## Test Strategy

Existing tests for `manage_customer`, `query_info`, and `book` should pass without modification since behavior is unchanged. Add targeted unit tests for:

1. **`CustomerData` construction**: verify `CustomerData(first_name="Ana")` works and unset fields default to `None`.
2. **`QueryFilters` construction**: verify `QueryFilters(category="Peluquería")` and `QueryFilters(keywords=["hours"])`.
3. **`parse_filters` validator**: verify JSON string `'{"category": "Peluquería"}'` parses into `QueryFilters`, `None` stays `None`, invalid JSON raises `ValueError`.
4. **Strict schema generation**: call `ManageCustomerSchema.model_json_schema()` and `QueryInfoSchema.model_json_schema()` and assert no `additionalProperties: true` appears anywhere in the tree.

All tests are unit-level, no database or LLM required.
