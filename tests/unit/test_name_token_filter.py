"""
REMOVED: tests for GreetingMode._contains_customer_name_token().

This method was removed in the scope-realignment refactor.
GreetingMode no longer validates LLM responses for name leaks because
GREETING never sets customer_name and the LLM prompt already enforces
"NUNCA uses el nombre". No replacement tests needed.
"""
# No tests — the functionality was removed.
