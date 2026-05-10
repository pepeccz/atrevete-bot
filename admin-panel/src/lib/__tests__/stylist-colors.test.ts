/**
 * stylist-colors.test.ts
 *
 * Tests for deriveStylistPalette utility.
 * No test runner installed (vitest/jest absent from package.json devDeps).
 * These tests are written for Vitest API. To run them:
 *   npm install --save-dev vitest @vitest/coverage-v8
 *   npx vitest run src/lib/__tests__/stylist-colors.test.ts
 *
 * GAP: No test runner is currently configured in admin-panel/package.json.
 *      Tests are authored and validated by code review and TypeScript correctness.
 *      Add vitest to devDependencies to activate them.
 */

import { describe, it, expect } from "vitest";
import { deriveStylistPalette } from "../stylist-colors";

// Helper: parse an hsl() or hex string and return approximate lightness (0-100)
function approxLightness(color: string): number {
  // If hex
  if (color.startsWith("#")) {
    const r = parseInt(color.slice(1, 3), 16) / 255;
    const g = parseInt(color.slice(3, 5), 16) / 255;
    const b = parseInt(color.slice(5, 7), 16) / 255;
    const max = Math.max(r, g, b);
    const min = Math.min(r, g, b);
    return ((max + min) / 2) * 100;
  }
  throw new Error(`approxLightness: unsupported format ${color}`);
}

// WCAG relative luminance
function relativeLuminance(hex: string): number {
  const r = parseInt(hex.slice(1, 3), 16) / 255;
  const g = parseInt(hex.slice(3, 5), 16) / 255;
  const b = parseInt(hex.slice(5, 7), 16) / 255;
  const toLinear = (c: number) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  return 0.2126 * toLinear(r) + 0.7152 * toLinear(g) + 0.0722 * toLinear(b);
}

function contrastRatio(hex1: string, hex2: string): number {
  const l1 = relativeLuminance(hex1);
  const l2 = relativeLuminance(hex2);
  const lighter = Math.max(l1, l2);
  const darker = Math.min(l1, l2);
  return (lighter + 0.05) / (darker + 0.05);
}

describe("deriveStylistPalette", () => {
  describe("valid mid-range hex — brand gold #b8924b", () => {
    const palette = deriveStylistPalette("#b8924b");

    it("solid equals the input hex", () => {
      expect(palette.solid.toLowerCase()).toBe("#b8924b");
    });

    it("soft has lightness >= 88% (pastel background)", () => {
      expect(approxLightness(palette.soft)).toBeGreaterThanOrEqual(88);
    });

    it("text has lightness <= 40% (readable on soft background)", () => {
      expect(approxLightness(palette.text)).toBeLessThanOrEqual(40);
    });

    it("text passes WCAG AA against soft (contrast >= 4.5:1)", () => {
      expect(contrastRatio(palette.text, palette.soft)).toBeGreaterThanOrEqual(4.5);
    });
  });

  describe("pure white input #ffffff", () => {
    const palette = deriveStylistPalette("#ffffff");

    it("soft is computed without error (light input, soft can stay near-white)", () => {
      expect(palette.soft).toMatch(/^#[0-9a-fA-F]{6}$/);
    });

    it("text is clamped to dark enough value (lightness <= 40%)", () => {
      expect(approxLightness(palette.text)).toBeLessThanOrEqual(40);
    });

    it("text passes WCAG AA against soft", () => {
      expect(contrastRatio(palette.text, palette.soft)).toBeGreaterThanOrEqual(4.5);
    });
  });

  describe("pure black input #000000", () => {
    const palette = deriveStylistPalette("#000000");

    it("soft is lightened to >= 85% lightness", () => {
      expect(approxLightness(palette.soft)).toBeGreaterThanOrEqual(85);
    });

    it("text stays dark (<= 40%)", () => {
      expect(approxLightness(palette.text)).toBeLessThanOrEqual(40);
    });

    it("no error is thrown", () => {
      expect(() => deriveStylistPalette("#000000")).not.toThrow();
    });
  });

  describe("high-saturation yellow #ffff00 (WCAG stress)", () => {
    const palette = deriveStylistPalette("#ffff00");

    it("text passes WCAG AA against soft", () => {
      expect(contrastRatio(palette.text, palette.soft)).toBeGreaterThanOrEqual(4.5);
    });
  });

  describe("invalid / empty input falls back to grayscale palette", () => {
    it("returns fallback for empty string", () => {
      const p = deriveStylistPalette("");
      expect(p.solid).toBe("#928679");
    });

    it("returns fallback for non-hex string", () => {
      const p = deriveStylistPalette("not-a-color");
      expect(p.solid).toBe("#928679");
    });
  });

  describe("memoization", () => {
    it("returns the exact same object reference on second call (Map cache)", () => {
      const hex = "#3066d8";
      const first = deriveStylistPalette(hex);
      const second = deriveStylistPalette(hex);
      expect(first).toBe(second);
    });

    it("deterministic: both calls return identical values", () => {
      const p1 = deriveStylistPalette("#1ba8c4");
      const p2 = deriveStylistPalette("#1ba8c4");
      expect(p1.solid).toBe(p2.solid);
      expect(p1.soft).toBe(p2.soft);
      expect(p1.text).toBe(p2.text);
    });
  });

  describe("output shape", () => {
    it("always returns { solid, soft, text } keys", () => {
      const p = deriveStylistPalette("#3a9a4d");
      expect(typeof p.solid).toBe("string");
      expect(typeof p.soft).toBe("string");
      expect(typeof p.text).toBe("string");
    });

    it("all values are valid hex strings", () => {
      const p = deriveStylistPalette("#cc3a3a");
      const hexRegex = /^#[0-9a-fA-F]{6}$/;
      expect(p.solid).toMatch(hexRegex);
      expect(p.soft).toMatch(hexRegex);
      expect(p.text).toMatch(hexRegex);
    });
  });
});
