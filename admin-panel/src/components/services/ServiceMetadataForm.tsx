"use client";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Label } from "@/components/ui/label";

const AUDIENCE_OPTIONS = [
  { value: "", label: "Sin especificar" },
  { value: "adult_female", label: "Señora" },
  { value: "adult_male", label: "Caballero" },
  { value: "child_female", label: "Niña" },
  { value: "child_male", label: "Niño" },
  { value: "unisex", label: "Unisex" },
] as const;

interface ServiceMetadataFormProps {
  value: string | null;
  onChange: (value: string | null) => void;
  disabled?: boolean;
}

export function ServiceMetadataForm({
  value,
  onChange,
  disabled = false,
}: ServiceMetadataFormProps) {
  return (
    <div className="space-y-2">
      <Label className="text-sm font-medium">Audiencia</Label>
      <Select
        disabled={disabled}
        value={value ?? ""}
        onValueChange={(v) => onChange(v === "" ? null : v)}
      >
        <SelectTrigger>
          <SelectValue placeholder="Sin especificar" />
        </SelectTrigger>
        <SelectContent>
          {AUDIENCE_OPTIONS.map((opt) => (
            <SelectItem key={opt.value} value={opt.value}>
              {opt.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
