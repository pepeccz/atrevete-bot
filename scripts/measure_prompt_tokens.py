"""Measure static system prompt size for token-budget tracking."""
from agent.prompts.loader import load_system_prompt


def main() -> None:
    load_system_prompt.cache_clear()
    prompt = load_system_prompt()
    chars = len(prompt)
    tokens = chars // 4  # rough estimate
    print(f"chars: {chars}")
    print(f"tokens (chars/4): {tokens}")


if __name__ == "__main__":
    main()
