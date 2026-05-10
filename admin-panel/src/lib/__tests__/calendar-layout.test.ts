/**
 * calendar-layout.test.ts
 *
 * Unit tests for splitOverlapping and positionForAppointment.
 * Written for Vitest API (describe/it/expect).
 *
 * NOTE: Vitest is not yet installed as a devDependency in this project.
 * Tests are authored to spec and will run once the runner is added in Slice 5.
 * See admin-panel/src/lib/__tests__/stylist-colors.test.ts for the same pattern.
 */

import { describe, it, expect } from "vitest";
import { splitOverlapping, positionForAppointment, type OverlapItem } from "../calendar-layout";

// ---------------------------------------------------------------------------
// positionForAppointment
// ---------------------------------------------------------------------------
describe("positionForAppointment", () => {
  it("positions a 60-min appointment starting at grid start as top=0", () => {
    // grid starts at 9:00 (540 min), slot=15min, slotPx=24
    const pos = positionForAppointment(540, 60, 540, 15, 24);
    expect(pos.top).toBe(0);
    expect(pos.height).toBe(96); // 60 * (24/15) = 96
  });

  it("positions an appointment 30 min after grid start", () => {
    const pos = positionForAppointment(570, 30, 540, 15, 24);
    expect(pos.top).toBe(48); // 30 * 1.6 = 48
    expect(pos.height).toBe(48);
  });

  it("enforces minimum height of 1 slot", () => {
    // 5-min appointment in 15-min slots = less than 1 slot → clamp to slotPx
    const pos = positionForAppointment(540, 5, 540, 15, 24);
    expect(pos.height).toBe(24);
  });
});

// ---------------------------------------------------------------------------
// splitOverlapping
// ---------------------------------------------------------------------------
describe("splitOverlapping", () => {
  it("returns empty array for 0 items", () => {
    expect(splitOverlapping([])).toEqual([]);
  });

  it("single item gets subColumn 0 and totalSubColumns 1", () => {
    const items: OverlapItem[] = [{ id: "a", startMin: 540, endMin: 600 }];
    const result = splitOverlapping(items);
    expect(result).toHaveLength(1);
    expect(result[0].subColumn).toBe(0);
    expect(result[0].totalSubColumns).toBe(1);
  });

  it("two non-overlapping items — each gets their own single sub-column", () => {
    const items: OverlapItem[] = [
      { id: "a", startMin: 540, endMin: 600 }, // 9:00–10:00
      { id: "b", startMin: 600, endMin: 660 }, // 10:00–11:00
    ];
    const result = splitOverlapping(items);
    expect(result).toHaveLength(2);
    // Both should be in lane 0 since they don't overlap (b starts when a ends)
    result.forEach(r => {
      expect(r.totalSubColumns).toBe(1);
    });
  });

  it("two overlapping items — placed in subColumn 0 and 1", () => {
    const items: OverlapItem[] = [
      { id: "a", startMin: 540, endMin: 660 }, // 9:00–11:00
      { id: "b", startMin: 600, endMin: 720 }, // 10:00–12:00 — overlaps a
    ];
    const result = splitOverlapping(items);
    expect(result).toHaveLength(2);
    const lanes = result.map(r => r.subColumn).sort();
    expect(lanes).toEqual([0, 1]);
    result.forEach(r => {
      expect(r.totalSubColumns).toBe(2);
    });
  });

  it("three cascading overlaps handled correctly", () => {
    // a: 9–11, b: 10–12, c: 11:30–13 — a overlaps b, b overlaps c, but a doesn't overlap c
    const items: OverlapItem[] = [
      { id: "a", startMin: 540, endMin: 660 },  // 9:00–11:00
      { id: "b", startMin: 600, endMin: 720 },  // 10:00–12:00
      { id: "c", startMin: 690, endMin: 780 },  // 11:30–13:00
    ];
    const result = splitOverlapping(items);
    expect(result).toHaveLength(3);
    // a and b overlap → 2 lanes needed for them
    // c overlaps b but not a → c can reuse lane 0 (a has ended by 11:00 and c starts 11:30)
    const a = result.find(r => r.id === "a")!;
    const b = result.find(r => r.id === "b")!;
    const c = result.find(r => r.id === "c")!;
    // a and b should be in different lanes
    expect(a.subColumn).not.toBe(b.subColumn);
    // c can go in a's lane (lane 0) since a ends before c starts
    expect(c.subColumn).toBe(0);
    // within the a-b overlap cluster, both need 2 total sub-columns
    expect(a.totalSubColumns).toBe(2);
    expect(b.totalSubColumns).toBe(2);
  });

  it("does not mutate the input array", () => {
    const items: OverlapItem[] = [
      { id: "a", startMin: 540, endMin: 600 },
      { id: "b", startMin: 540, endMin: 600 },
    ];
    const original = JSON.stringify(items);
    splitOverlapping(items);
    expect(JSON.stringify(items)).toBe(original);
  });
});
