import { Badge } from "@/components/ui/badge";
import type { ServiceCategory } from "@/lib/types";

const CATEGORY_VARIANTS: Record<ServiceCategory, "default" | "secondary" | "info"> = {
  HAIRDRESSING: "default",
  AESTHETICS: "secondary",
  BOTH: "info",
};

const CATEGORY_LABELS: Record<ServiceCategory, string> = {
  HAIRDRESSING: "Peluquería",
  AESTHETICS: "Estética",
  BOTH: "Ambos",
};

interface CategoryBadgeProps {
  category: ServiceCategory;
}

export function CategoryBadge({ category }: CategoryBadgeProps) {
  return (
    <Badge variant={CATEGORY_VARIANTS[category]}>
      {CATEGORY_LABELS[category]}
    </Badge>
  );
}
