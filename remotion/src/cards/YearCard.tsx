import {AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import type {PlacedCard} from '../cardTypes';
import {THEME} from '../theme';
import {DISPLAY_FONT, LABEL_FONT} from '../typography';

// ─── Animation timing ──────────────────────────────────────────────────────
// Duration is fixed by the registry; everything below is keyed off absolute
// seconds (frame / fps) so the staged entrance reads the same regardless of
// the resolved hold length. The whole card fades out over the last 0.6s.
const OUT_SEC = 0.6;

// Entrance stages (delaySec, durationSec).
const EYEBROW_DELAY = 0.15;
const EYEBROW_DUR = 0.9;
const YEAR_DELAY = 0.35;
const YEAR_DUR = 1.05;
const UNDERLINE_DELAY = 0.8;
const UNDERLINE_DUR = 0.8;
const CAPTION_DELAY = 1.0;
const CAPTION_DUR = 0.8;

const EASE_OUT = Easing.bezier(0.16, 1, 0.3, 1);

type Props = {
	card: Extract<PlacedCard, {kind: 'year-card'}>;
};

export const YearCard: React.FC<Props> = ({card}) => {
	const frame = useCurrentFrame();
	const {fps, durationInFrames} = useVideoConfig();
	const tSec = frame / fps;
	const totalSec = durationInFrames / fps;

	// Whole-card exit fade over the final 0.6s.
	const exitProgress = interpolate(tSec, [totalSec - OUT_SEC, totalSec], [0, 1], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
		easing: Easing.ease,
	});
	const cardOpacity = 1 - exitProgress;

	// 1. Eyebrow — "om-letters" reveal: letter-spacing collapses inward while
	//    the text fades in.
	const eyebrowProgress = interpolate(tSec, [EYEBROW_DELAY, EYEBROW_DELAY + EYEBROW_DUR], [0, 1], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
		easing: EASE_OUT,
	});
	const eyebrowLetterSpacing = interpolate(eyebrowProgress, [0, 1], [0.65, 0.28]);

	// 2. Year — rises up from below behind a clipping mask.
	const yearProgress = interpolate(tSec, [YEAR_DELAY, YEAR_DELAY + YEAR_DUR], [0, 1], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
		easing: EASE_OUT,
	});
	const yearRiseY = interpolate(yearProgress, [0, 1], [112, 0]);

	// 3. Underline — grows from the centre.
	const underlineProgress = interpolate(tSec, [UNDERLINE_DELAY, UNDERLINE_DELAY + UNDERLINE_DUR], [0, 1], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
		easing: EASE_OUT,
	});

	// 4. Caption — plain fade.
	const captionProgress = interpolate(tSec, [CAPTION_DELAY, CAPTION_DELAY + CAPTION_DUR], [0, 1], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
		easing: Easing.ease,
	});

	return (
		<AbsoluteFill style={{pointerEvents: 'none', justifyContent: 'center', alignItems: 'center', opacity: cardOpacity}}>
			{/* Strong teal wash — reads as a near-solid teal card even over a photo. */}
			<AbsoluteFill style={{backgroundColor: THEME.withAlpha(THEME.secondary, 0.97)}} />
			{/* Vignette — darkens the corners to focus the eye on the centred year. */}
			<AbsoluteFill
				style={{background: 'radial-gradient(120% 120% at 50% 50%, transparent 50%, rgba(0,0,0,0.5) 100%)'}}
			/>

			<div
				style={{
					// position:relative so the column paints above the absolute scrims.
					position: 'relative',
					display: 'flex',
					flexDirection: 'column',
					alignItems: 'center',
					textAlign: 'center',
					fontFamily: DISPLAY_FONT,
				}}
			>
				{card.eyebrow ? (
					<div
						style={{
							fontFamily: LABEL_FONT,
							fontSize: 38,
							fontWeight: 500,
							textTransform: 'uppercase',
							color: THEME.primary,
							letterSpacing: `${eyebrowLetterSpacing}em`,
							opacity: eyebrowProgress,
						}}
					>
						{card.eyebrow}
					</div>
				) : null}

				<div style={{overflow: 'hidden', padding: '0.04em 0', margin: '19px 0'}}>
					<div
						style={{
							transform: `translateY(${yearRiseY}%)`,
							opacity: yearProgress,
							fontFamily: DISPLAY_FONT,
							fontSize: 346,
							fontWeight: 900,
							letterSpacing: '-0.02em',
							lineHeight: 0.9,
							color: THEME.textPrimary,
						}}
					>
						{card.year}
					</div>
				</div>

				<div
					style={{
						width: 345,
						height: 2,
						background: THEME.primary,
						transform: `scaleX(${underlineProgress})`,
						transformOrigin: 'center',
					}}
				/>

				{card.caption ? (
					<div
						style={{
							marginTop: 46,
							fontFamily: LABEL_FONT,
							fontSize: 36,
							fontWeight: 400,
							letterSpacing: '0.2em',
							textTransform: 'uppercase',
							color: THEME.textSecondary,
							opacity: captionProgress,
						}}
					>
						{card.caption}
					</div>
				) : null}
			</div>
		</AbsoluteFill>
	);
};
