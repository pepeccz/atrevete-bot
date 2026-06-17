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
import {
  Dialog,
  DialogContent,
  DialogTitle,
} from "@/components/ui/dialog";
import api from "@/lib/api";
import type { GlobalSearchResponse, SearchResultItem } from "@/lib/types";
import { useDebounce } from "@/hooks/use-debounce";
import { useMediaQuery } from "@/hooks/use-media-query";
import { useSidebar } from "@/contexts/sidebar-context";

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

/** Contenido de resultados de búsqueda compartido entre desktop y móvil */
function SearchResults({
  query,
  results,
  loading,
  onSelect,
}: {
  query: string;
  results: GlobalSearchResponse | null;
  loading: boolean;
  onSelect: (item: SearchResultItem) => void;
}) {
  const hasResults = results && results.total > 0;

  if (loading) {
    return (
      <div className="p-4 text-center text-sm text-muted-foreground">
        Buscando...
      </div>
    );
  }

  if (!loading && query.length >= 2 && !hasResults) {
    return (
      <div className="p-4 text-center text-sm text-muted-foreground">
        No se encontraron resultados para &quot;{query}&quot;
      </div>
    );
  }

  if (!loading && hasResults) {
    return (
      <ScrollArea className="max-h-96">
        <div className="p-2">
          <SearchResultGroup
            type="customer"
            items={results.customers}
            onSelect={onSelect}
          />
          <SearchResultGroup
            type="appointment"
            items={results.appointments}
            onSelect={onSelect}
          />
          <SearchResultGroup
            type="service"
            items={results.services}
            onSelect={onSelect}
          />
          <SearchResultGroup
            type="stylist"
            items={results.stylists}
            onSelect={onSelect}
          />
        </div>
      </ScrollArea>
    );
  }

  return (
    <div className="p-4 text-center text-sm text-muted-foreground">
      Escribe al menos 2 caracteres para buscar
    </div>
  );
}

export function GlobalSearch() {
  const [desktopOpen, setDesktopOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<GlobalSearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const mobileInputRef = useRef<HTMLInputElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const router = useRouter();

  const isMobile = useMediaQuery("(max-width: 767px)");
  const { isMobileSearchOpen, closeMobileSearch } = useSidebar();

  const debouncedQuery = useDebounce(query, 300);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      abortControllerRef.current?.abort();
    };
  }, []);

  // Reset query when mobile dialog closes
  useEffect(() => {
    if (!isMobileSearchOpen) {
      setQuery("");
      setResults(null);
    }
  }, [isMobileSearchOpen]);

  // Focus mobile input when dialog opens
  useEffect(() => {
    if (isMobileSearchOpen) {
      setTimeout(() => mobileInputRef.current?.focus(), 100);
    }
  }, [isMobileSearchOpen]);

  useEffect(() => {
    if (debouncedQuery.length < 2) {
      setResults(null);
      return;
    }

    // Cancel any in-flight request before starting a new one
    abortControllerRef.current?.abort();
    const controller = new AbortController();
    abortControllerRef.current = controller;

    const search = async () => {
      setLoading(true);
      try {
        const data = await api.globalSearch(debouncedQuery, controller.signal);
        // Only update state if this request was not aborted
        if (!controller.signal.aborted) {
          setResults(data);
        }
      } catch (error) {
        if (error instanceof Error && error.name === "AbortError") {
          // Petición cancelada — no hacer nada
          return;
        }
        console.error("Search error:", error);
        setResults(null);
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      }
    };

    search();
  }, [debouncedQuery]);

  const handleSelect = useCallback(
    (item: SearchResultItem) => {
      setDesktopOpen(false);
      closeMobileSearch();
      setQuery("");
      router.push(item.url);
    },
    [router, closeMobileSearch]
  );

  // Keyboard shortcut (Ctrl+K / Cmd+K) — solo en escritorio
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        if (!isMobile) {
          setDesktopOpen(true);
          setTimeout(() => inputRef.current?.focus(), 0);
        }
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [isMobile]);

  // ----- Móvil: Dialog a pantalla completa (AD9) -----
  if (isMobile) {
    return (
      <Dialog open={isMobileSearchOpen} onOpenChange={(open) => !open && closeMobileSearch()}>
        <DialogContent className="fixed inset-0 h-full max-w-full translate-x-0 translate-y-0 left-0 top-0 rounded-none flex flex-col p-0">
          <DialogTitle className="sr-only">Buscar</DialogTitle>
          <div className="flex items-center gap-2 p-4 border-b">
            <Search className="h-4 w-4 text-muted-foreground flex-shrink-0" />
            <Input
              ref={mobileInputRef}
              type="search"
              placeholder="Buscar clientes, citas, servicios..."
              className="flex-1 border-0 shadow-none focus-visible:ring-0 text-base"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
          <div className="flex-1 overflow-y-auto">
            <SearchResults
              query={query}
              results={results}
              loading={loading}
              onSelect={handleSelect}
            />
          </div>
        </DialogContent>
      </Dialog>
    );
  }

  // ----- Escritorio: Popover existente -----
  return (
    <Popover open={desktopOpen} onOpenChange={setDesktopOpen}>
      <PopoverTrigger asChild>
        <div className="relative hidden md:flex items-center w-44 lg:w-56 xl:w-72 h-9 rounded-[10px] border border-line bg-bg/60 px-3 gap-2 hover:bg-bg cursor-text">
          <Search className="h-4 w-4 text-ink-mute flex-shrink-0" />
          <Input
            ref={inputRef}
            type="search"
            placeholder="Buscar clientes, citas, servicios..."
            className="flex-1 h-7 border-0 bg-transparent p-0 text-[13px] placeholder:text-ink-mute focus-visible:ring-0 focus-visible:ring-offset-0 shadow-none"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onFocus={() => setDesktopOpen(true)}
          />
          <span className="hidden lg:flex items-center gap-1 flex-shrink-0">
            <kbd className="px-1.5 py-0.5 text-[10px] font-semibold text-ink-mute bg-white border border-line rounded">⌘</kbd>
            <kbd className="px-1.5 py-0.5 text-[10px] font-semibold text-ink-mute bg-white border border-line rounded">K</kbd>
          </span>
        </div>
      </PopoverTrigger>
      <PopoverContent
        className="w-80 p-0"
        align="start"
        onOpenAutoFocus={(e) => e.preventDefault()}
      >
        <SearchResults
          query={query}
          results={results}
          loading={loading}
          onSelect={handleSelect}
        />
      </PopoverContent>
    </Popover>
  );
}
