/**
 * stylist-colors.ts
 *
 * Derives a { solid, soft, text } palette from a stylist's stored hex color.
 * Pure TypeScript, no external dependencies.
 * Memoized per page session via module-scope Map (cleared on full reload).
 *
 * Design spec: admin-panel-redesign design §3
 */

export interface StylistPalette {
  /** The input hex (or fallback if invalid). */
  solid: string;
  /** Pastel background variant, ~92% L in HSL. */
  soft: string;
  /** Dark text variant for use on soft background, ~28% L in HSL. */
  text: string;
}

// Fallback palette for invalid / grayscale inputs
const FALLBACK: StylistPalette = {
  solid: "#928679",
  soft: "#f0ece6",
  text: "#3d3833",
};

const HEX_REGEX = /^#?([0-9a-fA-F]{6})$/;

// Module-scope memoization cache (per page session)
const cache = new Map<string, StylistPalette>();

// ─── Colour math helpers ──────────────────────────────────────────────────────

interface HSL {
  h: number; // 0-360
  s: number; // 0-100
  l: number; // 0-100
}

function hexToHsl(hex: string): HSL {
  const m = hex.match(/([0-9a-fA-F]{2})/g)!;
  const r = parseInt(m[0], 16) / 255;
  const g = parseInt(m[1], 16) / 255;
  const b = parseInt(m[2], 16) / 255;

  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const delta = max - min;

  let h = 0;
  if (delta !== 0) {
    if (max === r) h = ((g - b) / delta + (g < b ? 6 : 0)) / 6;
    else if (max === g) h = ((b - r) / delta + 2) / 6;
    else h = ((r - g) / delta + 4) / 6;
  }

  const l = (max + min) / 2;
  const s = delta === 0 ? 0 : delta / (1 - Math.abs(2 * l - 1));

  return { h: Math.round(h * 360), s: Math.round(s * 100), l: Math.round(l * 100) };
}

function hslToHex({ h, s, l }: HSL): string {
  const sNorm = s / 100;
  const lNorm = l / 100;
  const a = sNorm * Math.min(lNorm, 1 - lNorm);
  const f = (n: number) => {
    const k = (n + h / 30) % 12;
    const color = lNorm - a * Math.max(Math.min(k - 3, 9 - k, 1), -1);
    return Math.round(255 * color)
      .toString(16)
      .padStart(2, "0");
  };
  return `#${f(0)}${f(8)}${f(4)}`;
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

function relativeLuminance(hex: string): number {
  const m = hex.match(/([0-9a-fA-F]{2})/g)!;
  const toLinear = (c: number) =>
    c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  const r = toLinear(parseInt(m[0], 16) / 255);
  const g = toLinear(parseInt(m[1], 16) / 255);
  const b = toLinear(parseInt(m[2], 16) / 255);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrastRatio(fg: string, bg: string): number {
  const l1 = relativeLuminance(fg);
  const l2 = relativeLuminance(bg);
  const lighter = Math.max(l1, l2);
  const darker = Math.min(l1, l2);
  return (lighter + 0.05) / (darker + 0.05);
}

// ─── Public API ───────────────────────────────────────────────────────────────

/**
 * Derives a three-variant palette from a hex colour.
 *
 * @param hex - Any 6-digit hex string, with or without `#` prefix.
 * @returns `{ solid, soft, text }` — all values are `#rrggbb` hex strings.
 */
export function deriveStylistPalette(hex: string): StylistPalette {
  // Normalise
  const normalized = hex.trim();
  const match = normalized.match(HEX_REGEX);

  if (!match) return FALLBACK;

  const cleanHex = `#${match[1].toLowerCase()}`;

  // Cache hit
  const cached = cache.get(cleanHex);
  if (cached) return cached;

  const hsl = hexToHsl(cleanHex);
  let { h, s } = hsl;

  // Detect near-grayscale: boost to warm hue for variant generation
  if (s < 8) {
    h = 35;
    s = 35;
  }

  // Soft: ~92% lightness, saturation clamped to stay pastel
  const softHsl: HSL = { h, s: clamp(s, 25, 55), l: 92 };
  const softHex = hslToHex(softHsl);

  // Text: ~28% lightness, saturation boosted for readability
  let textL = 28;
  let textHex = hslToHex({ h, s: clamp(s, 40, 80), l: textL });

  // WCAG AA verification: contrast of text against soft must be >= 4.5
  // Up to 3 attempts, darkening by 4 L each time
  for (let attempt = 0; attempt < 3; attempt++) {
    if (contrastRatio(textHex, softHex) >= 4.5) break;
    textL = Math.max(4, textL - 4);
    textHex = hslToHex({ h, s: clamp(s, 40, 80), l: textL });
  }

  // Final safety fallback if contrast still insufficient
  if (contrastRatio(textHex, softHex) < 4.5) {
    textHex = "#1a1714";
  }

  const palette: StylistPalette = {
    solid: cleanHex,
    soft: softHex,
    text: textHex,
  };

  cache.set(cleanHex, palette);
  return palette;
}
