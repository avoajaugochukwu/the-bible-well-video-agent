import {AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import type {PlacedCard} from '../cardTypes';
import {THEME} from '../theme';
import {DISPLAY_FONT, LABEL_FONT} from '../typography';

// ─── Animation timing ──────────────────────────────────────────────────────
// Fixed 5s window (0.4 in + 4.2 hold + 0.4 out). Keep in sync with
// cardDurations.ts.
const IN_SEC = 0.4;
const OUT_SEC = 0.4;

type Props = {
	card: Extract<PlacedCard, {kind: 'photo-title'}>;
};

// Centered kinetic-type look: one strong word over a full-page teal scrim,
// with an underline and optional descriptor. One card, one location.
export const PhotoTitle: React.FC<Props> = ({card}) => {
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
	const wordTranslateY = (1 - enterProgress) * 28 + exitProgress * -18;
	const wordSkew = (1 - enterProgress) * -2;

	const underlineProgress = interpolate(tSec, [IN_SEC * 0.4, IN_SEC * 1.1], [0, 1], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
	});
	return (
		<AbsoluteFill style={{pointerEvents: 'none', justifyContent: 'center', alignItems: 'center'}}>
			{/* Full-page secondary-color scrim — a flat translucent teal wash over the
			    whole frame keeps the text legible without per-letter shadows and
			    carries the video's theme tone. */}
			<AbsoluteFill
				style={{
					backgroundColor: THEME.withAlpha(THEME.secondary, 0.62),
					opacity,
				}}
			/>
			<div
				style={{
					// position:relative so the whole column (incl. the transform-less
					// descriptor) paints ABOVE the absolute scrim. Without it the scrim
					// washes over the descriptor (the headline/underline escape only
					// because their transforms make their own stacking contexts).
					position: 'relative',
					display: 'flex',
					flexDirection: 'column',
					alignItems: 'center',
					gap: 38,
					fontFamily: DISPLAY_FONT,
					opacity,
					maxWidth: '82%',
					textAlign: 'center',
				}}
			>
				<div style={{display: 'inline-block', transform: `translateY(${wordTranslateY}px) skewY(${wordSkew}deg)`}}>
					<span
						style={{
							color: THEME.textPrimary,
							fontSize: 138,
							fontWeight: 900,
							letterSpacing: -1.4,
							lineHeight: 1,
							textTransform: 'uppercase',
							whiteSpace: 'nowrap',
						}}
					>
						{card.word}
					</span>
				</div>
				{/* Underline — thin, centered, fixed ~34%-of-frame width, drawn via
				    scaleX. No glow (ref). */}
				<div
					style={{
						width: 653,
						height: 3,
						background: THEME.primary,
						transform: `scaleX(${underlineProgress})`,
						transformOrigin: 'center',
					}}
				/>
				{card.descriptor ? (
					<div
						style={{
							color: THEME.textSecondary,
							fontFamily: LABEL_FONT,
							fontSize: 35,
							fontWeight: 500,
							letterSpacing: '0.32em',
							textTransform: 'uppercase',
						}}
					>
						{card.descriptor}
					</div>
				) : null}
			</div>
		</AbsoluteFill>
	);
};
