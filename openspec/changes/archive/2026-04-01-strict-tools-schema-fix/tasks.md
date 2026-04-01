# Tasks: strict-tools-schema-fix

**Status**: ready  
**Change**: Replace `dict[str, Any]` with typed Pydantic models in tool schemas for OpenAI strict mode compatibility  
**Generated from**: spec.md + design.md  
**Files touched**: 4 (`customer_tools.py`, `info_tools.py`, `booking_tools.py`, `tests/unit/test_strict_tools_schema.py`)

---

## Dependency Graph

```
Phase 1 (T1.x)   Phase 2 (T2.x)   Phase 3 (T3.x)
     │                 │                 │
     └────────────────┬┘                 │
                      ▼                  │
               Phase 4 (T4.x) ◄─────────┘
```

Phases 1–3 are independent. Phase 4 (tests) depends on all three.

---

## Phase 1: `customer_tools.py` — CustomerData model

**File**: `agent/tools/customer_tools.py`  
**Goal**: Replace `dict[str, Any]` with `CustomerData(BaseModel)` throughout the customer tool.

---

### T1.1 — Add `CustomerData` model before `ManageCustomerSchema`

- **File**: `agent/tools/customer_tools.py`
- **Line reference**: Insert before line 74 (`class ManageCustomerSchema`)
- **Action**: Add the following class definition immediately before `ManageCustomerSchema`:

  ```python
  class CustomerData(BaseModel):
      """Typed data payload for customer create/update actions."""

      customer_id: str | None = None
      first_name: str | None = None
      last_name: str | None = None
      notes: str | None = None
  ```

- **Verify**: `CustomerData(first_name="Ana")` constructs without error; `CustomerData(first_name="Ana").last_name is None` is `True`; `CustomerData.model_json_schema()` does NOT contain `"additionalProperties": true`.
- **Size**: XS
- **Dependencies**: None

---

### T1.2 — Replace `data: dict[str, Any] | None` in `ManageCustomerSchema`

- **File**: `agent/tools/customer_tools.py`
- **Line reference**: Lines 90–97 (`data: dict[str, Any] | None = Field(...)`)
- **Action**: Replace the `data` field type annotation and update its description:

  ```python
  # BEFORE (lines 90-97)
  data: dict[str, Any] | None = Field(
      default=None,
      description=(
          "Additional data for the action:\n"
          "For 'create': {'first_name': str, 'last_name': str (optional), 'notes': str (optional)}\n"
          "For 'update': {'customer_id': str, 'first_name': str (optional), 'last_name': str (optional), 'notes': str (optional)}"
      ),
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

- **Verify**: `ManageCustomerSchema.model_fields["data"].annotation` resolves to `CustomerData | None`; `ManageCustomerSchema.model_json_schema()` has no `"type": "object"` entry lacking `"additionalProperties"`.
- **Size**: XS
- **Dependencies**: T1.1

---

### T1.3 — Update `manage_customer` function signature (line 114)

- **File**: `agent/tools/customer_tools.py`
- **Line reference**: Line 114 (function parameter `data: dict[str, Any] | None = None`)
- **Action**: Change the type annotation on `data` parameter:

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

- **Verify**: Function still accepts `data={"first_name": "Ana"}` (Pydantic coerces dict to `CustomerData`); signature type hint is `CustomerData | None`.
- **Size**: XS
- **Dependencies**: T1.1

---

### T1.4 — Update `_create_customer` signature and internal `.get()` calls

- **File**: `agent/tools/customer_tools.py`
- **Line reference**: Lines 261 (signature), 272 (`data.get("first_name")`), 277 (`data.get("last_name", "")`), 278 (`data.get("notes")`)
- **Action**:
  1. Change signature: `async def _create_customer(phone: str, data: dict[str, Any]) -> dict[str, Any]:` → `async def _create_customer(phone: str, data: CustomerData) -> dict[str, Any]:`
  2. Line 272: `first_name = data.get("first_name")` → `first_name = data.first_name`
  3. Line 277: `last_name = data.get("last_name", "")` → `last_name = data.last_name or ""`
  4. Line 278: `notes = data.get("notes")` → `notes = data.notes`

- **Verify**: `_create_customer` with `CustomerData(first_name="Ana")` resolves `first_name="Ana"`, `last_name=""`, `notes=None`. No AttributeError raised.
- **Size**: S
- **Dependencies**: T1.1

---

### T1.5 — Update `_update_customer` signature and internal `.get()` calls

- **File**: `agent/tools/customer_tools.py`
- **Line reference**: Lines 320 (signature), 328 (`data.get("customer_id")`), 329 (`data.get("first_name")`), 330 (`data.get("last_name")`), 331 (`data.get("notes")`)
- **Action**:
  1. Change signature: `async def _update_customer(phone: str, data: dict[str, Any]) -> dict[str, Any]:` → `async def _update_customer(phone: str, data: CustomerData) -> dict[str, Any]:`
  2. Line 328: `customer_id_str = data.get("customer_id")` → `customer_id_str = data.customer_id`
  3. Line 329: `first_name = data.get("first_name")` → `first_name = data.first_name`
  4. Line 330: `last_name = data.get("last_name")` → `last_name = data.last_name`
  5. Line 331: `notes = data.get("notes")` → `notes = data.notes`

- **Verify**: `_update_customer` with `CustomerData(first_name="Ana")` resolves all four attributes without `AttributeError`. The `any([first_name, last_name, notes])` guard on line 334 still works (attributes are `None` when not provided).
- **Size**: S
- **Dependencies**: T1.1

---

### T1.6 — Fix `manage_customer` call sites that pass `data or {}`

- **File**: `agent/tools/customer_tools.py`
- **Line reference**: Lines 199 (`data or {}`) and 201 (`data or {}`)
- **Action**: The `_create_customer` and `_update_customer` now accept `CustomerData`, not `dict`. The `data or {}` pattern passes an empty dict which Pydantic can coerce, but it's cleaner to pass a `CustomerData()` instance when `data` is `None`:

  ```python
  # BEFORE (lines 198-201)
  elif action == "create":
      return await _create_customer(phone, data or {})
  elif action == "update":
      return await _update_customer(phone, data or {})

  # AFTER
  elif action == "create":
      return await _create_customer(phone, data or CustomerData())
  elif action == "update":
      return await _update_customer(phone, data or CustomerData())
  ```

- **Verify**: Calling `manage_customer(action="create", phone="+34600000000")` without `data` no longer raises `TypeError`; `first_name` check in `_create_customer` still returns error if `data.first_name` is `None`.
- **Size**: XS
- **Dependencies**: T1.1, T1.4, T1.5

---

## Phase 2: `info_tools.py` — QueryFilters model

**File**: `agent/tools/info_tools.py`  
**Goal**: Replace `dict[str, Any]` with `QueryFilters(BaseModel)` throughout the info tool.

---

### T2.1 — Add `QueryFilters` model before `QueryInfoSchema`

- **File**: `agent/tools/info_tools.py`
- **Line reference**: Insert before line 37 (`class QueryInfoSchema`)
- **Action**: Add the following class definition immediately before `QueryInfoSchema`:

  ```python
  class QueryFilters(BaseModel):
      """Typed filter payload for query_info tool."""

      category: str | None = None
      keywords: list[str] | None = None
  ```

- **Verify**: `QueryFilters(category="Peluquería")` constructs without error; `QueryFilters(category="Peluquería").keywords is None` is `True`; `QueryFilters.model_json_schema()` has no open dict / `additionalProperties: true`.
- **Size**: XS
- **Dependencies**: None

---

### T2.2 — Replace `filters: dict[str, Any] | None` in `QueryInfoSchema`

- **File**: `agent/tools/info_tools.py`
- **Line reference**: Lines 50–57 (`filters: dict[str, Any] | None = Field(...)`)
- **Action**: Replace the `filters` field type annotation and update its description:

  ```python
  # BEFORE (lines 50-57)
  filters: dict[str, Any] | None = Field(
      default=None,
      description=(
          "Optional filters for the query:\n"
          "For 'services': {'category': 'Peluquería' | 'Estética'}\n"
          "For 'faqs': {'keywords': ['hours', 'parking', 'address']}"
      ),
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

- **Verify**: `QueryInfoSchema.model_fields["filters"].annotation` resolves to `QueryFilters | None`; no `"additionalProperties": true` in the schema JSON.
- **Size**: XS
- **Dependencies**: T2.1

---

### T2.3 — Migrate `parse_filters` validator to return `QueryFilters`

- **File**: `agent/tools/info_tools.py`
- **Line reference**: Lines 70–93 (`@field_validator("filters", mode="before")`)
- **Action**: Replace the entire validator body:

  ```python
  # BEFORE (lines 70-93)
  @field_validator("filters", mode="before")
  @classmethod
  def parse_filters(cls, v):
      """
      Parse filters parameter to accept both dict and JSON string.

      This handles cases where LLMs incorrectly serialize the filters
      parameter as a JSON string instead of a native dict object.
      """
      if v is None:
          return None

      if isinstance(v, str):
          try:
              return json.loads(v)
          except json.JSONDecodeError as e:
              raise ValueError(
                  f"filters must be a valid JSON string or dict, got invalid JSON: {e}"
              )

      if isinstance(v, dict):
          return v

      raise ValueError(f"filters must be a dict or JSON string, got {type(v).__name__}")

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

  **Note**: The `json` import on line 12 is still required by other code — do NOT remove it.

- **Verify**: `QueryInfoSchema(type="services", filters='{"category": "Peluquería"}').filters` returns `QueryFilters(category="Peluquería")`; passing `None` returns `None`; invalid JSON string raises `ValueError`.
- **Size**: S
- **Dependencies**: T2.1

---

### T2.4 — Update `query_info` function signature (line 99)

- **File**: `agent/tools/info_tools.py`
- **Line reference**: Line 99 (`filters: dict[str, Any] | None = None`)
- **Action**:

  ```python
  # BEFORE (line 99)
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

- **Verify**: Function signature shows `QueryFilters | None` for `filters`; still callable with `filters=None`.
- **Size**: XS
- **Dependencies**: T2.1

---

### T2.5 — Update `_get_services` signature and call sites

- **File**: `agent/tools/info_tools.py`
- **Line reference**: Line 187 (signature), line 204 (`"category" in filters`), line 205 (`filters["category"]`), line 234 (`filters.get('category')` in logger)
- **Action**:
  1. Line 187: `async def _get_services(filters: dict[str, Any] | None, max_results: int = 10)` → `async def _get_services(filters: QueryFilters | None, max_results: int = 10)`
  2. Line 204: `if filters and "category" in filters:` → `if filters and filters.category:`
  3. Line 205: `category_value = filters["category"]` → `category_value = filters.category`
  4. Line 234 (logger f-string): `filters.get('category')` → `filters.category`

- **Verify**: `_get_services(QueryFilters(category="Peluquería"), 10)` routes to `ServiceCategory.HAIRDRESSING` branch; `_get_services(None, 10)` returns all services; logger line compiles without error.
- **Size**: S
- **Dependencies**: T2.1

---

### T2.6 — Update `_get_faqs` signature and call sites

- **File**: `agent/tools/info_tools.py`
- **Line reference**: Line 259 (signature), line 282 (`"keywords" in filters`), line 283 (`filters["keywords"]`), line 303 (`filters.get('keywords')` in logger)
- **Action**:
  1. Line 259: `async def _get_faqs(filters: dict[str, Any] | None, max_results: int = 10)` → `async def _get_faqs(filters: QueryFilters | None, max_results: int = 10)`
  2. Line 282: `if filters and "keywords" in filters:` → `if filters and filters.keywords:`
  3. Line 283: `requested_keywords = filters["keywords"]` → `requested_keywords = filters.keywords`
  4. Line 303 (logger f-string): `filters.get('keywords')` → `filters.keywords`

- **Verify**: `_get_faqs(QueryFilters(keywords=["hours"]), 10)` filters correctly; `_get_faqs(None, 10)` returns all FAQs; logger line compiles without error.
- **Size**: S
- **Dependencies**: T2.1

---

## Phase 3: `booking_tools.py` — book() signature defaults

**File**: `agent/tools/booking_tools.py`  
**Goal**: Add `= None` defaults to `last_name` and `notes` in `book()` function to prevent `TypeError` when LLM omits optional params.

---

### T3.1 — Add `= None` default to `last_name` and `notes` in `book()` signature

- **File**: `agent/tools/booking_tools.py`
- **Line reference**: Lines 114–115 (`last_name: str | None` and `notes: str | None`)
- **Action**: Add `= None` defaults to both optional parameters:

  ```python
  # BEFORE (lines 113-115)
  async def book(
      customer_id: str,
      first_name: str,
      last_name: str | None,
      notes: str | None,

  # AFTER
  async def book(
      customer_id: str,
      first_name: str,
      last_name: str | None = None,
      notes: str | None = None,
  ```

  `BookSchema` (lines 37–43) already has `default=None` — this change only aligns the function signature.

- **Verify**: `book.__wrapped__` (or direct call) with only `customer_id`, `first_name`, `services`, `stylist_id`, `start_time` does NOT raise `TypeError: book() missing required positional arguments`. Inspect signature: `last_name` and `notes` parameters have `default=None`.
- **Size**: XS
- **Dependencies**: None

---

## Phase 4: Tests

**File**: `tests/unit/test_strict_tools_schema.py` (new file)  
**Goal**: Unit-level tests for all new models and the regression fix. No database, no LLM.

---

### T4.1 — Test `CustomerData` model construction and defaults

- **File**: `tests/unit/test_strict_tools_schema.py`
- **Line reference**: New file — first test class
- **Action**: Write tests:
  - `CustomerData(first_name="Ana")` succeeds; `.last_name is None`, `.notes is None`, `.customer_id is None`
  - `CustomerData()` creates all-`None` instance
  - `CustomerData(first_name="Ana", last_name="Gómez", notes="VIP", customer_id="uuid")` populates all fields
  - `ManageCustomerSchema(action="create", phone="+34600000000", data={"first_name": "Ana"})` coerces dict to `CustomerData`
  - `ManageCustomerSchema(action="get", phone="+34600000000")` works with `data=None`
- **Verify**: All assertions pass; no imports of database or LLM modules required.
- **Size**: S
- **Dependencies**: T1.1, T1.2

---

### T4.2 — Test `QueryFilters` model construction and defaults

- **File**: `tests/unit/test_strict_tools_schema.py`
- **Line reference**: New file — second test class
- **Action**: Write tests:
  - `QueryFilters(category="Peluquería")` succeeds; `.keywords is None`
  - `QueryFilters(keywords=["hours", "parking"])` succeeds; `.category is None`
  - `QueryFilters()` creates all-`None` instance
- **Verify**: All assertions pass; model constructs without database.
- **Size**: XS
- **Dependencies**: T2.1

---

### T4.3 — Test `parse_filters` validator with all input forms

- **File**: `tests/unit/test_strict_tools_schema.py`
- **Line reference**: New file — third test class
- **Action**: Write tests covering all branches of `parse_filters`:
  - `None` → field is `None`
  - Valid JSON string `'{"category": "Peluquería"}'` → `QueryFilters(category="Peluquería")`
  - Valid JSON string `'{"keywords": ["hours"]}'` → `QueryFilters(keywords=["hours"])`
  - Dict `{"category": "Estética"}` → `QueryFilters(category="Estética")`
  - `QueryFilters` instance passed directly → returned unchanged
  - Invalid JSON string `'"broken'` → raises `ValueError` (via Pydantic `ValidationError`)
  - Wrong type (e.g., `123`) → raises `ValueError` (via Pydantic `ValidationError`)
- **Verify**: 7 assertions covering all branches; no DB required.
- **Size**: S
- **Dependencies**: T2.1, T2.3

---

### T4.4 — Regression test: `book()` called without `last_name`/`notes`

- **File**: `tests/unit/test_strict_tools_schema.py`
- **Line reference**: New file — fourth test
- **Action**: Write a test that inspects the `book` function signature to confirm `last_name` and `notes` have `default=None`:

  ```python
  import inspect
  from agent.tools.booking_tools import book

  def test_book_last_name_notes_have_defaults():
      # book is a LangChain @tool — the wrapped function is in .__wrapped__
      fn = book.func if hasattr(book, "func") else book
      sig = inspect.signature(fn)
      assert sig.parameters["last_name"].default is None
      assert sig.parameters["notes"].default is None
  ```

  Additionally test that `book` can be invoked via `BookSchema` without passing `last_name`/`notes`:
  ```python
  schema = BookSchema(
      customer_id="550e8400-e29b-41d4-a716-446655440000",
      first_name="Ana",
      services=["Corte de Caballero"],
      stylist_id="550e8400-e29b-41d4-a716-446655440001",
      start_time="2026-06-01T10:00:00+02:00",
  )
  assert schema.last_name is None
  assert schema.notes is None
  ```

- **Verify**: Tests pass without `TypeError`; no LLM or DB calls required.
- **Size**: S
- **Dependencies**: T3.1

---

### T4.5 — Strict schema compliance assertions

- **File**: `tests/unit/test_strict_tools_schema.py`
- **Line reference**: New file — fifth test class
- **Action**: Write tests that serialize the updated schemas and assert no open `dict` objects remain:

  ```python
  import json
  from agent.tools.customer_tools import ManageCustomerSchema
  from agent.tools.info_tools import QueryInfoSchema

  def _has_additional_properties_true(schema_dict: dict) -> bool:
      """Recursively check if any object in the schema allows additionalProperties."""
      if schema_dict.get("additionalProperties") is True:
          return True
      for value in schema_dict.values():
          if isinstance(value, dict) and _has_additional_properties_true(value):
              return True
      return False

  def test_manage_customer_schema_strict_compatible():
      schema = ManageCustomerSchema.model_json_schema()
      assert not _has_additional_properties_true(schema)

  def test_query_info_schema_strict_compatible():
      schema = QueryInfoSchema.model_json_schema()
      assert not _has_additional_properties_true(schema)
  ```

- **Verify**: Both schema assertions pass; `dict[str, Any]` fields would fail this check (confirming the fix is in place).
- **Size**: S
- **Dependencies**: T1.1, T1.2, T2.1, T2.2

---

## Summary Table

| Task | Phase | File | Action | Size | Depends On |
|------|-------|------|--------|------|-----------|
| T1.1 | 1 | `customer_tools.py` | Add `CustomerData` model (~line 73) | XS | — |
| T1.2 | 1 | `customer_tools.py` | Replace `data: dict[str, Any]` in `ManageCustomerSchema` (lines 90–97) | XS | T1.1 |
| T1.3 | 1 | `customer_tools.py` | Update `manage_customer()` param type (line 114) | XS | T1.1 |
| T1.4 | 1 | `customer_tools.py` | Update `_create_customer()` signature + 3 `.get()` calls (lines 261, 272, 277, 278) | S | T1.1 |
| T1.5 | 1 | `customer_tools.py` | Update `_update_customer()` signature + 4 `.get()` calls (lines 320, 328–331) | S | T1.1 |
| T1.6 | 1 | `customer_tools.py` | Fix `data or {}` call sites → `data or CustomerData()` (lines 199, 201) | XS | T1.1, T1.4, T1.5 |
| T2.1 | 2 | `info_tools.py` | Add `QueryFilters` model (~line 36) | XS | — |
| T2.2 | 2 | `info_tools.py` | Replace `filters: dict[str, Any]` in `QueryInfoSchema` (lines 50–57) | XS | T2.1 |
| T2.3 | 2 | `info_tools.py` | Migrate `parse_filters` validator (lines 70–93) | S | T2.1 |
| T2.4 | 2 | `info_tools.py` | Update `query_info()` param type (line 99) | XS | T2.1 |
| T2.5 | 2 | `info_tools.py` | Update `_get_services()` signature + 3 call sites (lines 187, 204, 205, 234) | S | T2.1 |
| T2.6 | 2 | `info_tools.py` | Update `_get_faqs()` signature + 3 call sites (lines 259, 282, 283, 303) | S | T2.1 |
| T3.1 | 3 | `booking_tools.py` | Add `= None` defaults to `last_name` + `notes` in `book()` (lines 114–115) | XS | — |
| T4.1 | 4 | `test_strict_tools_schema.py` | Test `CustomerData` model + dict coercion | S | T1.1, T1.2 |
| T4.2 | 4 | `test_strict_tools_schema.py` | Test `QueryFilters` model construction | XS | T2.1 |
| T4.3 | 4 | `test_strict_tools_schema.py` | Test `parse_filters` all branches (7 cases) | S | T2.1, T2.3 |
| T4.4 | 4 | `test_strict_tools_schema.py` | Regression: `book()` signature defaults + `BookSchema` coercion | S | T3.1 |
| T4.5 | 4 | `test_strict_tools_schema.py` | Strict schema compliance assertions (no `additionalProperties: true`) | S | T1.1, T1.2, T2.1, T2.2 |

**Total**: 18 tasks — 8 XS, 9 S, 0 M  
**Estimated apply time**: ~30–45 min (mechanical refactor, no logic changes)

---

## Implementation Notes

1. **Keep `Any` import**: `from typing import Any, Literal` — `Any` is still needed for `-> dict[str, Any]` return types throughout all three files. Do NOT remove it.
2. **No `json` import removal**: `info_tools.py` uses `json` import elsewhere — keep it even after removing `json.loads(v)` from `parse_filters` (actually the new `model_validate_json` doesn't use `json.loads` directly, but the import may still be needed for other things; verify before removing).
3. **Pydantic dict coercion**: Existing code or tests that pass raw `dict` for `data` or `filters` will continue to work — Pydantic automatically coerces dicts to the typed model. No callers need updating.
4. **Test file name**: Use `test_strict_tools_schema.py` (new file) — not `test_tool_schema_fix.py` which already exists with unrelated tests.
5. **LangChain `@tool` introspection**: When accessing the wrapped function's signature in T4.4, use `book.func` (LangChain's `StructuredTool` attribute) rather than `book.__wrapped__`.
