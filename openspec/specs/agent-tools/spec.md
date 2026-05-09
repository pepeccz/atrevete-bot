# Delta Spec: strict-tools-schema-fix

## Domain: agent/tools

## Context

`strict: True` is active in the tool-binding layer (configured in `agent/agent_factory.py`). OpenAI strict mode requires
`additionalProperties: false` on every object in the JSON Schema — open `dict[str, Any]`
fields violate this constraint and cause tool-call failures.

---

## MODIFIED Requirements

### Requirement: FR-1 — CustomerData typed model

`ManageCustomerSchema.data` MUST be typed as `CustomerData | None` instead of
`dict[str, Any] | None`. `CustomerData` MUST enumerate exactly the fields read by
`_create_customer` and `_update_customer`: `customer_id`, `first_name`, `last_name`,
`notes`. All fields MUST have `default=None`. No `dict[str, Any]` MAY appear at any
level. Internal helpers MUST use attribute access (`data.first_name`) instead of
`data.get("first_name")`.

#### Scenario: SCENARIO-1 — Partial update via typed model

- GIVEN a `manage_customer(action="update")` call where the LLM only provides `first_name`
- WHEN the tool is invoked with `data={"first_name": "Ana"}`
- THEN Pydantic constructs `CustomerData(first_name="Ana", last_name=None, notes=None, customer_id=None)`
- AND `_update_customer` reads `data.first_name == "Ana"`, `data.last_name is None`
- AND only `first_name` is updated in the database

#### Scenario: Create with full data

- GIVEN `manage_customer(action="create", data={"first_name": "Ana", "last_name": "Gómez"})`
- WHEN `_create_customer` executes
- THEN `data.first_name == "Ana"` and `data.last_name == "Gómez"`
- AND customer is persisted with correct name fields

---

### Requirement: FR-2 — QueryFilters typed model

`QueryInfoSchema.filters` MUST be typed as `QueryFilters | None` instead of
`dict[str, Any] | None`. `QueryFilters` MUST enumerate exactly the keys read by
`_get_services` (`category: str | None`) and `_get_faqs` (`keywords: list[str] | None`).
All fields MUST have `default=None`. The existing `parse_filters` validator MUST be
preserved or adapted to accept `QueryFilters | str | None` and handle JSON-string
deserialization from LLMs that serialize objects as strings.

#### Scenario: SCENARIO-2 — Category filter passes correctly

- GIVEN `query_info(type="services", filters={"category": "Peluquería"})`
- WHEN the tool is invoked
- THEN `filters.category == "Peluquería"` is accessible in `_get_services`
- AND services are filtered to `ServiceCategory.HAIRDRESSING`

#### Scenario: Keywords filter passes correctly

- GIVEN `query_info(type="faqs", filters={"keywords": ["hours", "parking"]})`
- WHEN the tool is invoked
- THEN `filters.keywords == ["hours", "parking"]` in `_get_faqs`
- AND only matching FAQs are returned

#### Scenario: JSON-string filter still works

- GIVEN `query_info(type="services", filters='{"category": "Peluquería"}')`
- WHEN `parse_filters` validator runs
- THEN the string is parsed to `QueryFilters(category="Peluquería")`
- AND execution proceeds without error

---

### Requirement: FR-3 — book() function signature defaults

The `book()` function MUST have `= None` defaults for `last_name` and `notes` parameters
to match the `default=None` already declared in `BookSchema`. `BookSchema` itself MUST
remain unchanged.

#### Scenario: SCENARIO-3 — book called without optional params

- GIVEN a `book()` invocation that omits `last_name` and `notes`
- WHEN the function is called (either via tool invocation or directly in tests)
- THEN `last_name` receives `None` and `notes` receives `None`
- AND no `TypeError` is raised

---

## Non-Functional Requirements

### NFR-1 — No behavior change

All fields, descriptions, and validation logic MUST remain identical. No new fields
MUST be added. No existing fields MUST be removed. Existing tests that pass dicts
for `data` or `filters` MUST continue to work (Pydantic coerces dicts to models).

### NFR-2 — Strict mode schema compliance

After this change, `ManageCustomerSchema.model_json_schema()` and
`QueryInfoSchema.model_json_schema()` MUST NOT contain any object without
`additionalProperties: false`. The OpenAI API MUST accept both schemas under
`strict: true` without validation errors.

#### Scenario: SCENARIO-4 — Strict mode schema validation

- GIVEN the updated tool schemas are serialized to JSON Schema
- WHEN submitted to the OpenAI API with `strict: true`
- THEN the API accepts the schemas without returning a schema validation error
- AND the LLM is able to call all three tools in conversation flows

---

## Summary

| Requirement | Type | File | Scenarios |
|-------------|------|------|-----------|
| FR-1: CustomerData model | Modified | `agent/tools/customer_tools.py` | 2 |
| FR-2: QueryFilters model | Modified | `agent/tools/info_tools.py` | 3 |
| FR-3: book() defaults | Modified | `agent/tools/booking_tools.py` | 1 |
| NFR-1: No behavior change | Non-functional | All 3 files | — |
| NFR-2: Strict compliance | Non-functional | All 3 files | 1 |
