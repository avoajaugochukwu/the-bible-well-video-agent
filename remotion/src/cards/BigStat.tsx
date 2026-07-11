import {AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import type {PlacedCard} from '../cardTypes';
import {THEME} from '../theme';
import {DISPLAY_FONT, LABEL_FONT} from '../typography';

// ─── Animation timing ──────────────────────────────────────────────────────
// Fixed 5s window (0.5 in + 4.0 hold + 0.5 out). Keep these in sync with
// cardDurations.ts so the renderer's Sequence length matches this component's
// actual on-screen animation exactly.
const IN_SEC = 0.5;
const OUT_SEC = 0.5;
const COUNT_UP_SEC = 0.9;

// Visual palette — high-contrast white-on-tinted-glass over the underlying
// scene. The figure is the loudest thing on the frame, so the descriptor has
// to recede. Up/down stay semantic (green/red); neutral picks up the theme
// accent so a neutral stat reads as on-brand.
const ACCENT_UP = '#22c55e'; // green
const ACCENT_DOWN = '#ef4444'; // red

// Pull a parseable number out of "11%" / "$4.2B" / "1987" / "3 in 5".
// Returns null when no leading number is present (e.g. pure word figures);
// in that case we skip the count-up animation and just fade the figure in.
const parseLeadingNumber = (s: string): number | null => {
	const m = s.match(/-?\d{1,3}(?:[, ]?\d{3})*(?:\.\d+)?|-?\d+(?:\.\d+)?/);
	if (!m) return null;
	const cleaned = m[0].replace(/[, ]/g, '');
	const n = Number(cleaned);
	return Number.isFinite(n) ? n : null;
};

// Reformat the figure with a tween-progressed leading number while keeping
// the original suffix/prefix ("$" / "%" / "B" / "in 5" …) intact.
const renderFigureAt = (figure: string, finalNumber: number, t: number): string => {
	const m = figure.match(/-?\d{1,3}(?:[, ]?\d{3})*(?:\.\d+)?|-?\d+(?:\.\d+)?/);
	if (!m) return figure;
	const original = m[0];
	const prefix = figure.slice(0, m.index!);
	const suffix = figure.slice(m.index! + original.length);
	const hasDecimal = /\./.test(original);
	const animated = t * finalNumber;
	const displayed = hasDecimal
		? animated.toFixed(Math.min(2, original.split('.')[1]!.length))
		: Math.round(animated).toLocaleString();
	return `${prefix}${displayed}${suffix}`;
};

type Props = {
	card: Extract<PlacedCard, {kind: 'big-stat'}>;
};

export const BigStat: React.FC<Props> = ({card}) => {
	const frame = useCurrentFrame();
	const {fps, durationInFrames} = useVideoConfig();
	const tSec = frame / fps;
	const totalSec = durationInFrames / fps;

	const enterProgress = interpolate(tSec, [0, IN_SEC], [0, 1], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
	});
	const exitProgress = interpolate(tSec, [totalSec - OUT_SEC, totalSec], [0, 1], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
	});
	const opacity = enterProgress * (1 - exitProgress);
	const translateY = (1 - enterProgress) * 24 + exitProgress * -12;
	const scale = 0.92 + enterProgress * 0.08;

	const finalNumber = parseLeadingNumber(card.figure);
	// Count-up runs immediately after the entry settles, ends well before exit.
	const countT = interpolate(tSec, [IN_SEC, IN_SEC + COUNT_UP_SEC], [0, 1], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
	});
	const figureText = finalNumber !== null ? renderFigureAt(card.figure, finalNumber, countT) : card.figure;

	const direction = card.direction ?? 'neutral';
	const arrowColor = direction === 'up' ? ACCENT_UP : direction === 'down' ? ACCENT_DOWN : THEME.primary;
	const arrow = direction === 'up' ? '▲' : direction === 'down' ? '▼' : null;

	return (
		<AbsoluteFill style={{pointerEvents: 'none', justifyContent: 'center', alignItems: 'center'}}>
			<div
				style={{
					opacity,
					transform: `translateY(${translateY}px) scale(${scale})`,
					background: 'rgba(14, 18, 24, 0.5)',
					backdropFilter: 'blur(14px)',
					WebkitBackdropFilter: 'blur(14px)',
					padding: '65px 96px',
					borderRadius: 27,
					border: `1px solid ${THEME.withAlpha(THEME.textPrimary, 0.14)}`,
					boxShadow: `0 24px 80px ${THEME.shadow}`,
					display: 'flex',
					flexDirection: 'column',
					alignItems: 'center',
					gap: 23,
					fontFamily: DISPLAY_FONT,
					maxWidth: '78%',
				}}
			>
				{/* Figure row. The arrow is positioned OUT OF FLOW (absolute, hanging
				    to the left) so the number itself stays dead-centered in the card
				    whether or not a direction arrow is present. */}
				<div style={{position: 'relative', color: THEME.textPrimary, textAlign: 'center'}}>
					{arrow ? (
						<span
							style={{
								position: 'absolute',
								right: '100%',
								bottom: 0,
								marginRight: 18,
								color: arrowColor,
								fontSize: 64,
								lineHeight: 0.92,
								fontWeight: 800,
							}}
						>
							{arrow}
						</span>
					) : null}
					<span
						style={{
							fontSize: 173,
							lineHeight: 0.92,
							fontWeight: 900,
							letterSpacing: -3.5,
							fontVariantNumeric: 'tabular-nums',
							textTransform: 'uppercase',
						}}
					>
						{figureText}
					</span>
				</div>
				<div
					style={{
						color: THEME.textSecondary,
						fontFamily: LABEL_FONT,
						fontSize: 35,
						letterSpacing: '0.32em',
						// Trailing letter-spacing sits after the last glyph and would pull
						// centered text left by half a step — cancel it so the label is
						// optically centered under the figure.
						marginRight: '-0.32em',
						textTransform: 'uppercase',
						fontWeight: 500,
						textAlign: 'center',
					}}
				>
					{card.label}
				</div>
			</div>
		</AbsoluteFill>
	);
};
