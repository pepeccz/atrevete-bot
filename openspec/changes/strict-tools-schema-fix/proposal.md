# Proposal: strict-tools-schema-fix

## Intent

Two tool schemas are incompatible with OpenAI's `strict: True` mode (already live in `base.py:487`). Strict mode requires `additionalProperties: false` on every object in the JSON Schema, which means open-ended `dict[str, Any]` fields are rejected. The LLM may silently refuse to call these tools or produce malformed tool calls, causing booking and information flows to break unpredictably.

The fix: replace the two `dict[str, Any]` fields with typed Pydantic models that enumerate exactly the keys the code actually reads.

## Scope

### In Scope

| File | Field | Risk | Change |
|------|-------|------|--------|
| `agent/tools/customer_tools.py` | `ManageCustomerSchema.data: dict[str, Any] \| None` (line 90) | **HIGH** — blocks customer creation/update | Replace with typed `CustomerData` model covering `first_name`, `last_name`, `customer_id`, `notes` |
| `agent/tools/info_tools.py` | `QueryInfoSchema.filters: dict[str, Any] \| None` (line 50) | **MEDIUM-HIGH** — blocks filtered info queries | Replace with typed `QueryFilters` model covering `category`, `keywords` |
| `agent/tools/booking_tools.py` | `book()` function signature (line 111–118) | **LOW** — cosmetic inconsistency | Add `= None` defaults to `last_name` and `notes` params to match `BookSchema` |

### Out of Scope

- **FallbackChain / DeepSeek / Llama models** — `FallbackChain` is NOT wired to `_run_agentic_loop()`, no active risk from models that don't support strict mode
- **`search_services.py`** — nullable `Literal` types are supported by GPT-4.1-mini in strict mode
- **`availability_tools.py`** — all `Optional` fields already have `default=None`
- **`escalation_tools.py`** — `_`-prefixed injected params are intentional and outside the schema sent to the LLM
- **Mode nodes, routing, prompts** — no changes needed; the fix is purely at the schema level
- **Model changes** — stays on GPT-4.1-mini via OpenRouter

## Approach

### 1. `CustomerData` typed model (customer_tools.py)

Replace `data: dict[str, Any] | None` with a Pydantic model that covers only the fields that `_create_customer()` and `_update_customer()` actually read:

```python
class CustomerData(BaseModel):
    """Typed payload for manage_customer create/update actions."""
    customer_id: str | None = Field(
        default=None,
        description="Customer UUID (required for 'update' when phone lookup is not desired)"
    )
    first_name: str | None = Field(
        default=None,
        description="Customer's first name (required for 'create', optional for 'update')"
    )
    last_name: str | None = Field(
        default=None,
        description="Customer's last name"
    )
    notes: str | None = Field(
        default=None,
        description="Free-text notes about the customer"
    )
```

The internal helpers (`_create_customer`, `_update_customer`) currently call `data.get("key")` — these become `data.key` attribute access on the typed model. The `_get_customer` action ignores `data` entirely, so `data: CustomerData | None = None` remains optional.

**Why NOT `preferred_stylist_id` and `tags`?** — The pre-researched context mentioned them as possible reads, but the actual code (`_create_customer` at lines 272–278, `_update_customer` at lines 328–334) only reads `first_name`, `last_name`, `notes`, and `customer_id`. Adding unused fields would bloat the schema and confuse the LLM.

### 2. `QueryFilters` typed model (info_tools.py)

Replace `filters: dict[str, Any] | None` with:

```python
class QueryFilters(BaseModel):
    """Typed filters for query_info tool."""
    category: str | None = Field(
        default=None,
        description="Service category filter: 'Peluquería'/'HAIRDRESSING' or 'Estética'/'AESTHETICS'"
    )
    keywords: list[str] | None = Field(
        default=None,
        description="Keywords to filter FAQs (e.g., ['hours', 'parking'])"
    )
```

The internal helpers read exactly: `filters["category"]` (line 205) and `filters["keywords"]` (line 283). The `parse_filters` validator handles JSON-string fallback, which will still be needed — the validator moves to accept `QueryFilters | str | None` and parse accordingly.

### 3. `book()` function signature defaults (booking_tools.py)

Add `= None` to function params that already have `default=None` in `BookSchema`:

```python
# Before (line 114-115):
async def book(
    ...,
    last_name: str | None,
    notes: str | None,
    ...
)

# After:
async def book(
    ...,
    last_name: str | None = None,
    notes: str | None = None,
    ...
)
```

This is cosmetic — `BookSchema` already declares `default=None` so the schema sent to OpenAI is correct — but it prevents potential issues if the function is ever called directly.

### Migration of `data.get()` → attribute access

In `_create_customer` and `_update_customer`, replace dict access:

```python
# Before:
first_name = data.get("first_name")
last_name = data.get("last_name", "")

# After:
first_name = data.first_name
last_name = data.last_name or ""
```

This is a straightforward search-and-replace within the two helper functions. The `or {}` fallback on `data` (`data or {}`) becomes `data or CustomerData()` (empty defaults).

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `agent/tools/customer_tools.py` | Modified | New `CustomerData` model, update `ManageCustomerSchema.data` type, update dict access in `_create_customer` / `_update_customer` |
| `agent/tools/info_tools.py` | Modified | New `QueryFilters` model, update `QueryInfoSchema.filters` type, update dict access in `_get_services` / `_get_faqs` |
| `agent/tools/booking_tools.py` | Modified | Add `= None` defaults to `last_name` and `notes` in function signature |
| `tests/unit/` | May need updates | Tests that construct `ManageCustomerSchema` or `QueryInfoSchema` with raw dicts need to pass typed models instead |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| LLM stops populating `data` field after schema change | Low | The field names and descriptions remain identical; only the type constraint changes from open dict to structured object |
| Existing tests break on typed model | Medium | Tests are easy to update — replace `data={"first_name": "X"}` with `data=CustomerData(first_name="X")` or keep dicts (Pydantic validates them) |
| `parse_filters` validator edge cases | Low | Keep the JSON-string parsing validator — some LLMs serialize objects as strings; move it to `QueryFilters` or keep at `QueryInfoSchema` level |
| Missing field in `CustomerData` that future code needs | Low | The model is in the same file; adding a field is a one-line change + migration is not needed (no DB impact) |

## Rollback Plan

Revert the three files to their previous versions. The `dict[str, Any]` fields are a strict superset of the typed models, so reverting is always safe. The only behavioral difference is that strict mode may produce occasional tool-call failures (the current state).

## Dependencies

- None — purely internal schema changes with no external service or migration dependency

## Success Criteria

- [ ] `ManageCustomerSchema` serializes to JSON Schema with `additionalProperties: false` on all nested objects
- [ ] `QueryInfoSchema` serializes to JSON Schema with `additionalProperties: false` on all nested objects
- [ ] `book()` function signature matches `BookSchema` defaults
- [ ] Existing unit tests pass (with any necessary type adjustments)
- [ ] Manual smoke test: LLM successfully calls `manage_customer(action="create", ...)` and `query_info(type="services", filters={...})` without schema validation errors
