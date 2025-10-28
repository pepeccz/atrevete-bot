# 9. Frontend Architecture

The frontend for Atrévete Bot is minimal by design. Customer interactions occur exclusively via WhatsApp (handled by Chatwoot), and staff management uses Django Admin's auto-generated interface. No custom frontend application (React/Vue) is required for MVP.

## 9.1 Component Architecture

Django Admin uses auto-generated ModelAdmin forms. No custom frontend components required.

## 9.2 State Management Architecture

Django Admin uses server-side session management (built-in). No client-side state (React/Vue stores) required.

---
