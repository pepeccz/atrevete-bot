"use client";

import { useState, KeyboardEvent } from "react";
import { X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

interface TagInputProps {
  value: string[];
  onChange: (tags: string[]) => void;
  placeholder?: string;
  suggestions?: string[];
  maxTags?: number;
  disabled?: boolean;
  className?: string;
}

export function TagInput({
  value,
  onChange,
  placeholder = "Agregar etiqueta...",
  suggestions,
  maxTags,
  disabled = false,
  className,
}: TagInputProps) {
  const [inputValue, setInputValue] = useState("");

  const availableSuggestions = suggestions
    ? suggestions.filter((s) => !value.includes(s))
    : null;

  const canAdd = !maxTags || value.length < maxTags;

  const addTag = (tag: string) => {
    const trimmed = tag.trim();
    if (!trimmed) return;
    if (value.includes(trimmed)) return;
    if (!canAdd) return;
    // If suggestions provided, only allow values from suggestions
    if (suggestions && !suggestions.includes(trimmed)) return;
    onChange([...value, trimmed]);
    setInputValue("");
  };

  const removeTag = (tag: string) => {
    onChange(value.filter((t) => t !== tag));
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      addTag(inputValue);
    } else if (e.key === "Backspace" && !inputValue && value.length > 0) {
      removeTag(value[value.length - 1]);
    }
  };

  return (
    <div className={cn("space-y-2", className)}>
      <div className="flex flex-wrap gap-1 min-h-[2rem]">
        {value.map((tag) => (
          <Badge key={tag} variant="secondary" className="gap-1 pr-1">
            {tag}
            {!disabled && (
              <button
                type="button"
                onClick={() => removeTag(tag)}
                className="ml-1 rounded-sm opacity-70 hover:opacity-100 focus:outline-none"
                aria-label={`Eliminar ${tag}`}
              >
                <X className="h-3 w-3" />
              </button>
            )}
          </Badge>
        ))}
      </div>
      {canAdd && !disabled && (
        <>
          {availableSuggestions !== null ? (
            // Suggestions mode: show remaining suggestions as clickable chips
            <div className="flex flex-wrap gap-1">
              {availableSuggestions.map((s) => (
                <Badge
                  key={s}
                  variant="outline"
                  className="cursor-pointer hover:bg-secondary"
                  onClick={() => addTag(s)}
                >
                  + {s}
                </Badge>
              ))}
              {availableSuggestions.length === 0 && (
                <span className="text-xs text-muted-foreground">
                  Todos los valores seleccionados
                </span>
              )}
            </div>
          ) : (
            // Free-text mode: show input
            <Input
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={placeholder}
              disabled={disabled}
            />
          )}
        </>
      )}
    </div>
  );
}
