// Pure on-screen duration formulas for each card kind. Mirrors the timing
// constants used by the corresponding React components in src/cards/. Kept
// JSX-free so cardRegistry.ts can compute per-card duration without pulling
// in React.
//
// IF YOU CHANGE A TIMING CONSTANT IN A CARD COMPONENT, MIRROR IT HERE.

// ─── photo-title (src/cards/PhotoTitle.tsx) ──────────────────────────────
// Lightweight kinetic-type overlay. Fixed duration regardless of word/
// descriptor length. Mirrors the timing constants in the renderer.
const PHOTO_TITLE_IN_SEC = 0.4;
const PHOTO_TITLE_HOLD_SEC = 4.2;
const PHOTO_TITLE_OUT_SEC = 0.4;
export const PHOTO_TITLE_DURATION_SEC =
	PHOTO_TITLE_IN_SEC + PHOTO_TITLE_HOLD_SEC + PHOTO_TITLE_OUT_SEC;

// ─── photo-caption (src/cards/PhotoCaption.tsx) ──────────────────────────
// Lightweight contextual caption overlay. Fixed duration, same total as
// photo-title for consistency. Mirrors the timing constants in the renderer.
const PHOTO_CAPTION_IN_SEC = 0.4;
const PHOTO_CAPTION_HOLD_SEC = 4.2;
const PHOTO_CAPTION_OUT_SEC = 0.4;
export const PHOTO_CAPTION_DURATION_SEC =
	PHOTO_CAPTION_IN_SEC + PHOTO_CAPTION_HOLD_SEC + PHOTO_CAPTION_OUT_SEC;

// ─── big-stat (src/cards/BigStat.tsx) ────────────────────────────────────
// Big-figure callout. Fixed duration; the figure count-up runs inside.
const BIG_STAT_IN_SEC = 0.5;
const BIG_STAT_HOLD_SEC = 4.0;
const BIG_STAT_OUT_SEC = 0.5;
export const BIG_STAT_DURATION_SEC =
	BIG_STAT_IN_SEC + BIG_STAT_HOLD_SEC + BIG_STAT_OUT_SEC;

// ─── Heavy full-frame title cards (opening-title / pull-quote / year-card).
// Fixed durations; each component runs its staggered entrance, holds, then
// fades over the last OUT_SEC of the Sequence (so the rendered length
// always equals the value here — see src/cards/*). ────────────────────────
export const OPENING_TITLE_DURATION_SEC = 5;
export const PULL_QUOTE_DURATION_SEC = 5;
export const YEAR_CARD_DURATION_SEC = 5;
