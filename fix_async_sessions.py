#!/usr/bin/env python3
"""
Fix incorrect 'async for' usage with get_async_session().

This script replaces:
    async for session in get_async_session():
with:
    async with get_async_session() as session:

And removes the 'finally: break' workaround.
"""

import re
from pathlib import Path

# Files to fix
FILES_TO_FIX = [
    "agent/prompts/__init__.py",
    "agent/tools/booking_tools.py",
    "agent/tools/calendar_tools.py",
    "agent/tools/customer_tools.py",
    "agent/tools/info_tools.py",
    "agent/tools/search_services.py",
    "agent/transactions/booking_transaction.py",
    "agent/validators/transaction_validators.py",
    "agent/workers/conversation_archiver.py",
    "shared/archive_retrieval.py",
    "database/seeds/faqs.py",
    "database/seeds/policies.py",
    "database/seeds/services.py",
    "api/main.py",
]


def fix_async_session_usage(content: str) -> tuple[str, int]:
    """
    Fix async session usage in file content.

    Returns:
        tuple: (fixed_content, num_replacements)
    """
    num_replacements = 0

    # Replace 'async for session in get_async_session():' with 'async with get_async_session() as session:'
    pattern = r'async for session in get_async_session\(\):'
    replacement = 'async with get_async_session() as session:'

    fixed_content, count = re.subn(pattern, replacement, content)
    num_replacements += count

    # Remove 'finally:\n        break  # Exit async for loop' patterns
    # This pattern matches the workaround that was added
    finally_pattern = r'\n        finally:\n            break  # Exit async for loop.*?\n'
    fixed_content = re.sub(finally_pattern, '\n', fixed_content)

    # Also remove simpler finally/break patterns
    finally_pattern2 = r'\n        finally:\n            break\n'
    fixed_content = re.sub(finally_pattern2, '\n', fixed_content)

    # Remove the "edge case" error handling that's no longer needed
    edge_case_pattern = r'\n    # Edge case: If async for loop exits without returning.*?\n    logger\.error\(\n.*?\n    \)\n    raise RuntimeError\(.*?\)\n'
    fixed_content = re.sub(edge_case_pattern, '', fixed_content, flags=re.DOTALL)

    return fixed_content, num_replacements


def main():
    """Fix all files."""
    total_replacements = 0

    for file_path in FILES_TO_FIX:
        path = Path(file_path)
        if not path.exists():
            print(f"⚠️  File not found: {file_path}")
            continue

        # Read original content
        with open(path, 'r', encoding='utf-8') as f:
            original_content = f.read()

        # Fix content
        fixed_content, num_replacements = fix_async_session_usage(original_content)

        if num_replacements > 0:
            # Write fixed content
            with open(path, 'w', encoding='utf-8') as f:
                f.write(fixed_content)

            print(f"✅ Fixed {file_path}: {num_replacements} replacements")
            total_replacements += num_replacements
        else:
            print(f"✓  No changes needed: {file_path}")

    print(f"\n🎉 Total files fixed: {len([p for p in FILES_TO_FIX if Path(p).exists()])}")
    print(f"🎉 Total replacements: {total_replacements}")


if __name__ == "__main__":
    main()
