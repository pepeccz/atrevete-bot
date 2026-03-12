# Admin Panel Component Guidelines

This directory contains the Atrévete Bot admin interface built with Next.js 15 (App Router).

> **Architecture**: Next.js 15.0.3 + React 18.3.1 + Tailwind CSS. This is the Next.js frontend (port 3001), NOT Django Admin (port 8001).

---

## Auto-invoke Skills

When performing these actions, ALWAYS invoke the corresponding skill FIRST:

| Action | Skill |
|--------|-------|
| Creating React components | `atrevete-admin` |
| Creating UI components | `atrevete-admin` |
| Working with Next.js | `atrevete-admin` |
| Styling with Tailwind | `tailwind-4` |
| TypeScript patterns | `typescript` |

---

## Directory Structure

```
admin-panel/
├── src/
│   ├── app/                     # Next.js App Router
│   │   ├── layout.tsx           # Root layout with providers
│   │   ├── page.tsx             # Login page (redirect to dashboard)
│   │   ├── login/page.tsx       # Login form
│   │   └── (authenticated)/     # Protected routes group
│   │       ├── layout.tsx       # Auth guard layout
│   │       ├── dashboard/page.tsx
│   │       ├── appointments/page.tsx
│   │       ├── customers/page.tsx
│   │       ├── stylists/page.tsx
│   │       ├── services/page.tsx
│   │       ├── calendar/page.tsx
│   │       ├── settings/page.tsx
│   │       └── ...
│   │
│   ├── components/              # React components
│   │   ├── ui/                  # shadcn/ui components
│   │   ├── layout/              # Layout components (sidebar, header)
│   │   ├── forms/               # Form components
│   │   └── data-table/          # Data table components
│   │
│   ├── contexts/                # React contexts
│   │   ├── auth-context.tsx     # Authentication state
│   │   └── sidebar-context.tsx  # Sidebar state
│   │
│   ├── hooks/                   # Custom React hooks
│   │   └── use-api.ts
│   │
│   └── lib/                     # Utilities
│       ├── api.ts               # API client functions
│       ├── auth.ts              # JWT auth utilities
│       ├── types.ts             # TypeScript types
│       └── utils.ts             # Helper functions
│
├── package.json
├── tailwind.config.ts
└── tsconfig.json
```

---

## Architecture

### Next.js 15 App Router

- **Framework**: Next.js 15.0.3 with App Router
- **React**: 18.3.1 with Server Components by default
- **Styling**: Tailwind CSS 3.4.15
- **UI Library**: shadcn/ui + Radix UI primitives
- **State**: React Context for auth/sidebar
- **HTTP**: Native fetch with async/await

### Port Configuration

```
Next.js Admin Panel: http://localhost:3001
FastAPI Backend:     http://localhost:8000
```

**IMPORTANT**: This is the Next.js frontend. Do NOT confuse with Django Admin on port 8001.

---

## Page Patterns

### Route Groups

```typescript
// app/(authenticated)/layout.tsx
"use client";

export default function AuthenticatedLayout({ children }) {
  const { isAuthenticated, isLoading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.replace("/login");
    }
  }, [isAuthenticated, isLoading, router]);

  if (isLoading) return <LoadingSpinner />;
  if (!isAuthenticated) return null;

  return (
    <div className="flex h-screen">
      <Sidebar />
      <main className="flex-1 overflow-y-auto">{children}</main>
    </div>
  );
}
```

### Server Component (Data Fetching)

```typescript
// app/(authenticated)/dashboard/page.tsx
import { getDashboardStats } from "@/lib/api";

export default async function DashboardPage() {
  const stats = await getDashboardStats();

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold">Dashboard</h1>
      <StatsCards stats={stats} />
    </div>
  );
}
```

### Client Component (Interactivity)

```typescript
"use client";

import { useState } from "react";

export default function CustomerForm() {
  const [name, setName] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    await createCustomer({ name });
  };

  return <form onSubmit={handleSubmit}>...</form>;
}
```

---

## Component Patterns

### UI Components (shadcn/ui)

```typescript
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardHeader, CardContent } from "@/components/ui/card";

export default function MyComponent() {
  return (
    <Card>
      <CardHeader>Título</CardHeader>
      <CardContent>
        <Input placeholder="Nombre" />
        <Button>Guardar</Button>
      </CardContent>
    </Card>
  );
}
```

### Data Table with TanStack

```typescript
import { useReactTable, getCoreRowModel } from "@tanstack/react-table";

export function DataTable({ data, columns }) {
  const table = useReactTable({
    data,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <table>
      <thead>
        {table.getHeaderGroups().map((headerGroup) => (
          <tr key={headerGroup.id}>
            {headerGroup.headers.map((header) => (
              <th key={header.id}>{header.column.columnDef.header}</th>
            ))}
          </tr>
        ))}
      </thead>
      <tbody>
        {table.getRowModel().rows.map((row) => (
          <tr key={row.id}>
            {row.getVisibleCells().map((cell) => (
              <td key={cell.id}>{cell.getValue()}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
```

---

## API Client Patterns

### Basic Fetch Wrapper

```typescript
// lib/api.ts
const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function apiRequest(endpoint: string, options: RequestInit = {}) {
  const token = localStorage.getItem("token");

  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      ...options.headers,
    },
  });

  if (!response.ok) {
    throw new Error(`API error: ${response.status}`);
  }

  return response.json();
}

export const getCustomers = () => apiRequest("/api/admin/customers");
export const createCustomer = (data: any) =>
  apiRequest("/api/admin/customers", {
    method: "POST",
    body: JSON.stringify(data),
  });
```

---

## State Management

### Auth Context

```typescript
// contexts/auth-context.tsx
"use client";

import { createContext, useContext, useState, useEffect } from "react";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem("token");
    setIsAuthenticated(!!token);
    setIsLoading(false);
  }, []);

  const login = (token: string) => {
    localStorage.setItem("token", token);
    setIsAuthenticated(true);
  };

  const logout = () => {
    localStorage.removeItem("token");
    setIsAuthenticated(false);
  };

  return (
    <AuthContext.Provider value={{ isAuthenticated, isLoading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
```

---

## Tailwind Patterns

### Utility Classes

```typescript
// Use Tailwind for all styling
<div className="flex items-center justify-between p-4 bg-white rounded-lg shadow">
  <h1 className="text-xl font-semibold text-gray-900">Título</h1>
  <Button className="bg-primary hover:bg-primary/90">Acción</Button>
</div>
```

### Custom Colors (tailwind.config.ts)

```typescript
import type { Config } from "tailwindcss";

const config: Config = {
  theme: {
    extend: {
      colors: {
        primary: {
          DEFAULT: "#7C3AED",
          foreground: "#FFFFFF",
        },
      },
    },
  },
};

export default config;
```

---

## Critical Rules

1. **ALWAYS use Server Components** by default (data fetching)
2. **ONLY use "use client"** when you need interactivity (forms, events)
3. **ALWAYS use Tailwind** for styling — no CSS modules
4. **ALWAYS use async/await** for data fetching
5. **ALWAYS type API responses** with TypeScript interfaces
6. **NEVER store secrets** in client-side code
7. **NEVER use `var()` in className** — use Tailwind utilities only

---

## Resources

- [Root AGENTS.md](../AGENTS.md) — Repository governance
- [atrevete-admin skill](../skills/atrevete-admin/SKILL.md) — Detailed patterns
- [nextjs-15 skill](../skills/nextjs-15/SKILL.md) — Next.js patterns
- [tailwind-4 skill](../skills/tailwind-4/SKILL.md) — Tailwind patterns
- `admin-panel/src/app/` — Page components
- `admin-panel/src/components/` — Reusable components

**Last Updated**: March 2026

### Auto-invoke Skills

When performing these actions, ALWAYS invoke the corresponding skill FIRST:

| Action | Skill |
|--------|-------|
| Creating React components | `atrevete-admin` |
| Creating UI components | `atrevete-admin` |
| Working on Next.js | `atrevete-admin` |
| Working on admin-panel/ | `atrevete-admin` |
