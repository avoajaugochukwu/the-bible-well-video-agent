// React-component lookup — the render-side counterpart of ../cardRegistry.ts
// (family + duration, React-free). Mirrors the reference project's split
// between lib/cards/registry.ts and remotion/cards/registry.tsx.
//
// Each PlacedCard variant is narrowed by `kind`; the narrowed card is passed
// straight through to its component.
import type {PlacedCard} from '../cardTypes';
import {PhotoTitle} from './PhotoTitle';
import {PhotoCaption} from './PhotoCaption';
import {BigStat} from './BigStat';
import {OpeningTitle} from './OpeningTitle';
import {PullQuote} from './PullQuote';
import {YearCard} from './YearCard';

export const CARD_COMPONENTS: Record<PlacedCard['kind'], React.FC<{card: PlacedCard}>> = {
	'photo-title': ({card}) => (card.kind === 'photo-title' ? <PhotoTitle card={card} /> : null),
	'photo-caption': ({card}) => (card.kind === 'photo-caption' ? <PhotoCaption card={card} /> : null),
	'big-stat': ({card}) => (card.kind === 'big-stat' ? <BigStat card={card} /> : null),
	'opening-title': ({card}) => (card.kind === 'opening-title' ? <OpeningTitle card={card} /> : null),
	'pull-quote': ({card}) => (card.kind === 'pull-quote' ? <PullQuote card={card} /> : null),
	'year-card': ({card}) => (card.kind === 'year-card' ? <YearCard card={card} /> : null),
};
