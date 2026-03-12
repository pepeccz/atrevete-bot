---
name: atrevete-admin
description: >
  Atrévete Bot admin panel patterns using Next.js 15, React 19, and Tailwind CSS.
  Trigger: When working on admin-panel/, React components, or UI elements.
  IMPORTANT: This is the Next.js admin panel (port 3001), NOT Django Admin (port 8001).
license: MIT
metadata:
  author: atrevete-bot
  version: "1.0"
  scope: [root, admin-panel]
  auto_invoke:
    - "Working on admin-panel/"
    - "Creating React components"
    - "Working on Next.js"
    - "Creating UI components"
---

## Admin Panel Overview

**CRITICAL:** This is the **Next.js Admin Panel** (port 3001), NOT Django Admin (port 8001).

Django Admin runs on port 8001 for database management.
Next.js Admin runs on port 3001 for modern React-based admin UI.

## Structure

```
admin-panel/
├── src/
│   ├── app/                      # Next.js 15 App Router
│   │   ├── layout.tsx            # Root layout (AuthProvider)
│   │   ├── page.tsx              # Redirect to /dashboard
│   │   ├── login/page.tsx        # Login page
│   │   ├── dashboard/page.tsx    # Dashboard with KPIs
│   │   ├── appointments/         # Appointment management
│   │   ├── customers/            # Customer management
│   │   ├── stylists/             # Stylist management
│   │   └── services/             # Service catalog
│   ├── components/
│   │   ├── ui/                   # shadcn/ui components
│   │   │   ├── button.tsx
│   │   │   ├── dialog.tsx
│   │   │   ├── table.tsx
│   │   │   └── ...
│   │   └── layout/               # Layout components
│   │       ├── sidebar.tsx
│   │       └── header.tsx
│   ├── contexts/
│   │   └── auth-context.tsx      # Authentication context
│   ├── hooks/
│   │   └── use-appointments.ts   # Data fetching hooks
│   ├── lib/
│   │   ├── api.ts                # API client
│   │   ├── types.ts              # TypeScript types
│   │   └── utils.ts              # Utility functions
│   └── styles/
│       └── globals.css           # Tailwind + custom styles
├── components.json               # shadcn/ui config
├── tailwind.config.ts            # Tailwind configuration
└── next.config.ts                # Next.js configuration
```

## External Skills Reference

**DO NOT duplicate** — reference these external skills:
- `nextjs-15/SKILL.md` — Next.js 15 App Router patterns
- `tailwind-4/SKILL.md` — Tailwind CSS styling patterns
- `typescript/SKILL.md` — TypeScript patterns

## Page Pattern (Client Component)

```tsx
"use client";

import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import { toast } from "sonner";
import type { Appointment } from "@/lib/types";

export default function AppointmentsPage() {
  const [appointments, setAppointments] = useState<Appointment[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  const fetchData = useCallback(async () => {
    try {
      setIsLoading(true);
      const response = await api.getAppointments();
      setAppointments(response.items);
    } catch (error) {
      console.error("Error fetching appointments:", error);
      toast.error("Error al cargar las citas");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-pulse text-muted-foreground">
          Cargando citas...
        </div>
      </div>
    );
  }

  return (
    <div className="container mx-auto py-6">
      <h1 className="text-2xl font-bold mb-6">Citas</h1>
      {/* Table or grid */}
    </div>
  );
}
```

## Dialog Form Pattern

```tsx
"use client";

import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";

interface CreateDialogProps {
  onSuccess?: () => void;
}

export function CreateAppointmentDialog({ onSuccess }: CreateDialogProps) {
  const [open, setOpen] = useState(false);
  const [isSaving, setIsSaving] = useState(false);

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setIsSaving(true);

    try {
      const formData = new FormData(e.currentTarget);
      await api.createAppointment({
        customer_id: formData.get("customer_id") as string,
        stylist_id: formData.get("stylist_id") as string,
        start_time: formData.get("start_time") as string,
      });

      toast.success("Cita creada correctamente");
      setOpen(false);
      onSuccess?.();
    } catch (error) {
      toast.error("Error al crear la cita");
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>Nueva Cita</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Crear Cita</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="customer_id">Cliente</Label>
            <Input id="customer_id" name="customer_id" required />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>
              Cancelar
            </Button>
            <Button type="submit" disabled={isSaving}>
              {isSaving ? "Guardando..." : "Guardar"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
```

## Table Pattern

```tsx
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";

function AppointmentsTable({ appointments }: { appointments: Appointment[] }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Cliente</TableHead>
          <TableHead>Estilista</TableHead>
          <TableHead>Fecha</TableHead>
          <TableHead>Estado</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {appointments.map((appt) => (
          <TableRow key={appt.id}>
            <TableCell>{appt.customer_name}</TableCell>
            <TableCell>{appt.stylist_name}</TableCell>
            <TableCell>{new Date(appt.start_time).toLocaleString()}</TableCell>
            <TableCell>
              <Badge variant={appt.status === "confirmed" ? "default" : "secondary"}>
                {appt.status}
              </Badge>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
```

## API Client Pattern

```typescript
// lib/api.ts
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export const api = {
  async getAppointments(): Promise<{ items: Appointment[] }> {
    const response = await fetch(`${API_BASE_URL}/api/admin/appointments`, {
      headers: {
        Authorization: `Bearer ${getToken()}`,
      },
    });
    if (!response.ok) throw new Error("Failed to fetch appointments");
    return response.json();
  },

  async createAppointment(data: CreateAppointmentInput): Promise<Appointment> {
    const response = await fetch(`${API_BASE_URL}/api/admin/appointments`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${getToken()}`,
      },
      body: JSON.stringify(data),
    });
    if (!response.ok) throw new Error("Failed to create appointment");
    return response.json();
  },
};
```

## Auth Context Pattern

```tsx
// contexts/auth-context.tsx
"use client";

import { createContext, useContext, useState, useEffect } from "react";

interface AuthContextType {
  user: User | null;
  isAuthenticated: boolean;
  login: (token: string) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => {
    const token = localStorage.getItem("admin_token");
    if (token) {
      // Validate token and set user
      validateToken(token).then(setUser);
    }
  }, []);

  const login = (token: string) => {
    localStorage.setItem("admin_token", token);
    validateToken(token).then(setUser);
  };

  const logout = () => {
    localStorage.removeItem("admin_token");
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, isAuthenticated: !!user, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within AuthProvider");
  return context;
};
```

## shadcn/ui Components

Install components via CLI:

```bash
npx shadcn add button dialog table input label badge
```

## Critical Rules

- **ALWAYS** use `"use client"` for pages with state/effects
- **ALWAYS** fetch data client-side with `useState` + `useEffect`
- **ALWAYS** use shadcn/ui components — NEVER native HTML
- **ALWAYS** use `toast` from Sonner — NEVER `alert()` or `confirm()`
- **ALWAYS** use Spanish for UI labels
- **ALWAYS** handle loading and error states
- **ALWAYS** provide toast feedback after mutations
- **ALWAYS** close dialogs on success: `setOpen(false)`
- **NEVER** use Server Components for data fetching (project uses Client Components)
- **NEVER** suggest Server Actions (project doesn't use them)

## Ports Reference

| Service | Port | Description |
|---------|------|-------------|
| Django Admin | 8001 | Legacy admin interface (database CRUD) |
| Next.js Admin | 3001 | Modern React admin panel |
| FastAPI | 8000 | API server |
| Agent | N/A | Background worker |

---

**Version**: 1.0
**Last Updated**: March 2026
