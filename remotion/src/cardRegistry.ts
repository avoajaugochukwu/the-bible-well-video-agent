// Server/render-safe card registry (React-free) — the single source of
// truth for per-card-kind family + on-screen duration. Mirrors the reference
// project's lib/cards/registry.ts vs remotion/cards/registry.tsx split: this
// file is JSX-free so it's safe to import from anywhere; src/cards/registry.tsx
// is the React-component counterpart.
import type {PlacedCard} from './cardTypes';
import {
	PHOTO_TITLE_DURATION_SEC,
	PHOTO_CAPTION_DURATION_SEC,
	BIG_STAT_DURATION_SEC,
	OPENING_TITLE_DURATION_SEC,
	PULL_QUOTE_DURATION_SEC,
	YEAR_CARD_DURATION_SEC,
} from './cardDurations';

// "summary" cards anchor/take over the frame; "moment" cards are lightweight
// overlays that coexist with the underlying scene. Render order in
// HeritageScenes puts summary first, moment second, so moments stack on top.
export type CardFamily = 'summary' | 'moment';

// The tail-guard/duration lookup only ever needs `kind`.
type CardDurationArg = Pick<PlacedCard, 'kind'>;

type CardSpec = {
	family: CardFamily;
	duration: (card: CardDurationArg) => number;
};

export const CARDS: Record<PlacedCard['kind'], CardSpec> = {
	'photo-title': {family: 'moment', duration: () => PHOTO_TITLE_DURATION_SEC},
	'photo-caption': {family: 'moment', duration: () => PHOTO_CAPTION_DURATION_SEC},
	'big-stat': {family: 'moment', duration: () => BIG_STAT_DURATION_SEC},
	'opening-title': {family: 'summary', duration: () => OPENING_TITLE_DURATION_SEC},
	'pull-quote': {family: 'summary', duration: () => PULL_QUOTE_DURATION_SEC},
	'year-card': {family: 'summary', duration: () => YEAR_CARD_DURATION_SEC},
};
