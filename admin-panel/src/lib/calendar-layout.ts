/**
 * calendar-layout.ts — Pure layout calculations for the per-stylist day view.
 *
 * positionForAppointment  — converts start/duration to absolute top+height px
 * splitOverlapping        — assigns sub-column positions for overlapping appointments
 */

export interface PositionedItem {
  top: number;   // px
  height: number; // px
}

/**
 * Computes absolute pixel position for an appointment card inside a day column.
 *
 * @param startMinFromMidnight  Minutes from midnight for appointment start
 * @param durationMin           Duration in minutes
 * @param gridStartMin          Grid start in minutes from midnight (e.g. 9*60 = 540)
 * @param slotMin               Grid slot size in minutes (e.g. 15)
 * @param slotPx                Pixel height per slot (e.g. 24)
 */
export function positionForAppointment(
  startMinFromMidnight: number,
  durationMin: number,
  gridStartMin: number,
  slotMin: number,
  slotPx: number
): PositionedItem {
  const pxPerMin = slotPx / slotMin;
  const top = (startMinFromMidnight - gridStartMin) * pxPerMin;
  const height = Math.max(durationMin * pxPerMin, slotPx); // minimum 1 slot height
  return { top, height };
}

// ---------------------------------------------------------------------------
// Overlap splitting
// ---------------------------------------------------------------------------

/** Minimal item shape for overlap calculations */
export interface OverlapItem {
  id: string;
  startMin: number; // minutes from midnight
  endMin: number;   // minutes from midnight
}

/** Same item with sub-column assignment */
export interface PlacedItem extends OverlapItem {
  subColumn: number;
  totalSubColumns: number;
}

/**
 * Given an array of items in a single stylist column, groups overlapping
 * appointments into visual sub-columns so they don't cover each other.
 *
 * Algorithm:
 *   1. Sort by startMin ASC (ties: longer duration first).
 *   2. Greedy lane assignment — for each item find the first lane whose last
 *      end ≤ this item's start.  If none exists, open a new lane.
 *   3. Walk items in a second pass to compute totalSubColumns = max(lane)+1
 *      within each overlap cluster.
 *
 * Returns a new array of PlacedItem (original order is NOT preserved).
 * If items is empty, returns [].
 */
export function splitOverlapping(items: OverlapItem[]): PlacedItem[] {
  if (items.length === 0) return [];

  // Sort by start; break ties by longer duration first (fills more space first)
  const sorted = [...items].sort((a, b) => {
    if (a.startMin !== b.startMin) return a.startMin - b.startMin;
    return (b.endMin - b.startMin) - (a.endMin - a.startMin);
  });

  // Each lane holds the latest endMin seen in that lane
  const laneEnds: number[] = [];
  const placements: { item: OverlapItem; lane: number }[] = [];

  for (const item of sorted) {
    let placed = false;
    for (let l = 0; l < laneEnds.length; l++) {
      if (laneEnds[l] <= item.startMin) {
        laneEnds[l] = item.endMin;
        placements.push({ item, lane: l });
        placed = true;
        break;
      }
    }
    if (!placed) {
      laneEnds.push(item.endMin);
      placements.push({ item, lane: laneEnds.length - 1 });
    }
  }

  // Second pass — build overlap clusters and compute totalSubColumns per cluster.
  // A cluster is any set of items where at least one pair overlaps.
  // Simpler approach: for each item, totalSubColumns = max lane index of all items
  // that overlap with it + 1.
  const result: PlacedItem[] = placements.map(({ item, lane }) => {
    // Find all items that overlap with this one
    const overlapping = placements.filter(({ item: other }) => {
      if (other === item) return false;
      return other.startMin < item.endMin && other.endMin > item.startMin;
    });
    const maxLane = overlapping.reduce((max, { lane: l }) => Math.max(max, l), lane);
    return {
      ...item,
      subColumn: lane,
      totalSubColumns: maxLane + 1,
    };
  });

  return result;
}
