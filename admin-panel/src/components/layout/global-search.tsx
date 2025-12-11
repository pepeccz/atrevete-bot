"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Search, User, Calendar, Scissors, Users } from "lucide-react";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import api from "@/lib/api";
import type { GlobalSearchResponse, SearchResultItem } from "@/lib/types";

// Debounce hook
function useDebounce<T>(value: T, delay: number): T {
  const [debouncedValue, setDebouncedValue] = useState<T>(value);

  useEffect(() => {
    const handler = setTimeout(() => {
      setDebouncedValue(value);
    }, delay);

    return () => {
      clearTimeout(handler);
    };
  }, [value, delay]);

  return debouncedValue;
}

const typeIcons = {
  customer: User,
  appointment: Calendar,
  service: Scissors,
  stylist: Users,
};

const typeLabels = {
  customer: "Clientes",
  appointment: "Citas",
  service: "Servicios",
  stylist: "Estilistas",
};

function SearchResultGroup({
  type,
  items,
  onSelect,
}: {
  type: keyof typeof typeLabels;
  items: SearchResultItem[];
  onSelect: (item: SearchResultItem) => void;
}) {
  const Icon = typeIcons[type];

  if (items.length === 0) return null;

  return (
    <div className="mb-4">
      <div className="flex items-center gap-2 px-2 py-1 text-xs font-semibold text-muted-foreground uppercase">
        <Icon className="h-3 w-3" />
        {typeLabels[type]}
      </div>
      {items.map((item) => (
        <button
          key={item.id}
          onClick={() => onSelect(item)}
          className="w-full flex flex-col items-start px-2 py-2 rounded-md hover:bg-accent text-left"
        >
          <span className="font-medium text-sm">{item.title}</span>
          {item.subtitle && (
            <span className="text-xs text-muted-foreground">{item.subtitle}</span>
          )}
        </button>
      ))}
    </div>
  );
}

export function GlobalSearch() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<GlobalSearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const router = useRouter();

  const debouncedQuery = useDebounce(query, 300);

  useEffect(() => {
    if (debouncedQuery.length < 2) {
      setResults(null);
      return;
    }

    const search = async () => {
      setLoading(true);
      try {
        const data = await api.globalSearch(debouncedQuery);
        setResults(data);
      } catch (error) {
        console.error("Search error:", error);
        setResults(null);
      } finally {
        setLoading(false);
      }
    };

    search();
  }, [debouncedQuery]);

  const handleSelect = useCallback(
    (item: SearchResultItem) => {
      setOpen(false);
      setQuery("");
      router.push(item.url);
    },
    [router]
  );

  // Keyboard shortcut (Ctrl+K / Cmd+K)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setOpen(true);
        setTimeout(() => inputRef.current?.focus(), 0);
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, []);

  const hasResults = results && results.total > 0;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <div className="relative hidden md:block">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            ref={inputRef}
            type="search"
            placeholder="Buscar... (Ctrl+K)"
            className="w-64 pl-8"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onFocus={() => setOpen(true)}
          />
        </div>
      </PopoverTrigger>
      <PopoverContent
        className="w-80 p-0"
        align="start"
        onOpenAutoFocus={(e) => e.preventDefault()}
      >
        {loading && (
          <div className="p-4 text-center text-sm text-muted-foreground">
            Buscando...
          </div>
        )}

        {!loading && query.length >= 2 && !hasResults && (
          <div className="p-4 text-center text-sm text-muted-foreground">
            No se encontraron resultados para &quot;{query}&quot;
          </div>
        )}

        {!loading && hasResults && (
          <ScrollArea className="max-h-96">
            <div className="p-2">
              <SearchResultGroup
                type="customer"
                items={results.customers}
                onSelect={handleSelect}
              />
              <SearchResultGroup
                type="appointment"
                items={results.appointments}
                onSelect={handleSelect}
              />
              <SearchResultGroup
                type="service"
                items={results.services}
                onSelect={handleSelect}
              />
              <SearchResultGroup
                type="stylist"
                items={results.stylists}
                onSelect={handleSelect}
              />
            </div>
          </ScrollArea>
        )}

        {query.length < 2 && (
          <div className="p-4 text-center text-sm text-muted-foreground">
            Escribe al menos 2 caracteres para buscar
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}
