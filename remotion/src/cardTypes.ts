// Shape produced by the Python planning stage (director) — matches that
// contract exactly. `kind` discriminates; camelCase fields.
export type StatDirection = 'up' | 'down' | 'neutral';

export type PlacedCard =
	| {kind: 'photo-title'; id: string; startSec: number; word: string; descriptor?: string}
	| {kind: 'photo-caption'; id: string; startSec: number; text: string}
	| {kind: 'big-stat'; id: string; startSec: number; figure: string; label: string; direction?: StatDirection}
	| {kind: 'opening-title'; id: string; startSec: number; eyebrow?: string; title: string; subtitle?: string}
	| {kind: 'pull-quote'; id: string; startSec: number; quote: string; attribution?: string; date?: string}
	| {kind: 'year-card'; id: string; startSec: number; eyebrow?: string; year: string; caption?: string};
