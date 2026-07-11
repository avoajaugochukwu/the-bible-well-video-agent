import {AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import type {PlacedCard} from '../cardTypes';
import {THEME} from '../theme';
import {DISPLAY_FONT, LABEL_FONT} from '../typography';

// ─── Animation timing ──────────────────────────────────────────────────────
// Opaque full-frame quote card. The Sequence length is fixed by the registry;
// here we only place entrances against absolute seconds and fade the whole
// card out over the final 0.6s. Keep this card's window in sync with
// cardDurations.ts.
const OUT_SEC = 0.6;
const ENTER_EASE = Easing.bezier(0.16, 1, 0.3, 1);

type Props = {
	card: Extract<PlacedCard, {kind: 'pull-quote'}>;
};

export const PullQuote: React.FC<Props> = ({card}) => {
	const frame = useCurrentFrame();
	const {fps, durationInFrames} = useVideoConfig();
	const tSec = frame / fps;

	// Whole-card fade-out over the last OUT_SEC.
	const exitProgress = interpolate(frame, [durationInFrames - OUT_SEC * fps, durationInFrames], [0, 1], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
	});
	const cardOpacity = 1 - exitProgress;

	// 1. Quote glyph: fade-up.
	const glyphProgress = interpolate(tSec, [0.1, 0.1 + 0.8], [0, 1], {
		easing: ENTER_EASE,
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
	});
	const glyphTranslateEm = (1 - glyphProgress) * 0.7;
	const glyphOpacity = glyphProgress;

	// 2. Quote body: rise from below behind a mask.
	const bodyProgress = interpolate(tSec, [0.35, 0.35 + 0.9], [0, 1], {
		easing: ENTER_EASE,
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
	});
	const riseY = (1 - bodyProgress) * 112;
	const bodyOpacity = bodyProgress;

	// 3. Attribution row: plain fade.
	const attributionOpacity = interpolate(tSec, [0.85, 0.85 + 0.8], [0, 1], {
		easing: Easing.ease,
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
	});

	return (
		<AbsoluteFill style={{pointerEvents: 'none', opacity: cardOpacity}}>
			{/* Transparent OVERLAY — the scene photo shows through a teal wash so the
			    card carries the theme tone but never fully hides what's underneath. */}
			<AbsoluteFill style={{backgroundColor: THEME.withAlpha(THEME.secondary, 0.72)}} />
			{/* Dark-teal glow biased to the upper-right for depth. */}
			<AbsoluteFill
				style={{
					background: `radial-gradient(120% 130% at 70% 20%, ${THEME.withAlpha(THEME.secondary, 0.4)} 0%, ${THEME.withAlpha(THEME.secondary, 0)} 60%)`,
				}}
			/>
			{/* Foreground content — position:relative so it paints above the
			    absolute background/scrim layers above. */}
			<div style={{position: 'absolute', left: 173, right: 173, top: '50%', transform: 'translateY(-50%)', textAlign: 'left'}}>
				<div style={{position: 'relative'}}>
					{/* Decorative opening quote glyph. */}
					<span
						style={{
							position: 'absolute',
							left: -8,
							top: -163,
							fontFamily: DISPLAY_FONT,
							fontSize: 269,
							fontWeight: 700,
							lineHeight: 1,
							color: THEME.primary,
							opacity: glyphOpacity,
							transform: `translateY(${glyphTranslateEm}em)`,
						}}
					>
						{'“'}
					</span>

					{/* Quote body, masked rise. */}
					<div style={{overflow: 'hidden', padding: '0.05em 0'}}>
						<div
							style={{
								transform: `translateY(${riseY}%)`,
								opacity: bodyOpacity,
								fontFamily: DISPLAY_FONT,
								fontSize: 84,
								fontWeight: 600,
								fontStyle: 'italic',
								lineHeight: 1.18,
								color: THEME.textPrimary,
							}}
						>
							{card.quote}
						</div>
					</div>

					{/* Attribution + optional date — same styled row, shown only when
					    the field is present. Date reads like a dateline next to the
					    speaker (or on its own when no speaker is known). */}
					{card.attribution || card.date ? (
						<div style={{display: 'flex', alignItems: 'center', gap: 31, marginTop: 58, opacity: attributionOpacity}}>
							<div style={{height: 2, width: 96, background: THEME.primary}} />
							<span
								style={{
									fontFamily: LABEL_FONT,
									fontSize: 33,
									fontWeight: 500,
									letterSpacing: '0.18em',
									textTransform: 'uppercase',
									color: THEME.textSecondary,
									whiteSpace: 'nowrap',
								}}
							>
								{[card.attribution, card.date].filter(Boolean).join(' · ')}
							</span>
						</div>
					) : null}
				</div>
			</div>
		</AbsoluteFill>
	);
};
