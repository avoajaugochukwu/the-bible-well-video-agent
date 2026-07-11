import {AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import type {PlacedCard} from '../cardTypes';
import {THEME} from '../theme';
import {DISPLAY_FONT, LABEL_FONT} from '../typography';

// ─── Animation timing ──────────────────────────────────────────────────────
// Transparent full-frame OVERLAY (the scene photo shows behind it). A teal
// scrim + vignette keep the text legible; a left-aligned column carries an
// optional eyebrow, the kinetic title, and an optional dateline footer.
//
// Entrance is driven by ABSOLUTE-second delays (frame/fps); the whole card
// fades out over the last 0.6s. Sequence length is fixed by the registry.
const EXIT_SEC = 0.6;

// Entrance delays (seconds).
const EYEBROW_DELAY_SEC = 0.15;
const BAR_DELAY_SEC = 0.25;
const TITLE_DELAY_SEC = 0.35;
const TITLE_STAGGER_SEC = 0.15;
const RULE_DELAY_SEC = 0.8;
const DATELINE_DELAY_SEC = 1.0;

// Entrance durations (seconds).
const EYEBROW_DUR_SEC = 0.7;
const BAR_DUR_SEC = 0.7;
const TITLE_DUR_SEC = 1.0;
const RULE_DUR_SEC = 0.9;
const DATELINE_DUR_SEC = 0.7;

// ─── Layout (px @ 1920×1080) ────────────────────────────────────────────────
const EDGE_PX = 173;

const EYEBROW_GAP_PX = 27;
const BAR_W_PX = 77;
const EYEBROW_FONT_PX = 33;

const TITLE_MARGIN_TOP_PX = 31;
const TITLE_FONT_PX = 211;

const FOOTER_GAP_PX = 38;
const FOOTER_MARGIN_TOP_PX = 50;
const RULE_W_PX = 269;
const DATELINE_FONT_PX = 36;

const EASE = Easing.bezier(0.16, 1, 0.3, 1);

type Props = {
	card: Extract<PlacedCard, {kind: 'opening-title'}>;
};

export const OpeningTitle: React.FC<Props> = ({card}) => {
	const frame = useCurrentFrame();
	const {fps, durationInFrames} = useVideoConfig();
	const tSec = frame / fps;

	// Whole-card exit fade over the last EXIT_SEC.
	const exitProgress = interpolate(frame, [durationInFrames - EXIT_SEC * fps, durationInFrames], [0, 1], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
	});
	const exitOpacity = 1 - exitProgress;

	// Eyebrow row: fade-up.
	const eyebrowIn = interpolate(tSec, [EYEBROW_DELAY_SEC, EYEBROW_DELAY_SEC + EYEBROW_DUR_SEC], [0, 1], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
		easing: EASE,
	});
	const eyebrowTranslateY = (1 - eyebrowIn) * 0.7; // em

	// Gold bar: scaleX grow.
	const barIn = interpolate(tSec, [BAR_DELAY_SEC, BAR_DELAY_SEC + BAR_DUR_SEC], [0, 1], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
		easing: EASE,
	});

	// Footer rule: scaleX grow.
	const ruleIn = interpolate(tSec, [RULE_DELAY_SEC, RULE_DELAY_SEC + RULE_DUR_SEC], [0, 1], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
		easing: EASE,
	});

	// Dateline: fade only.
	const datelineIn = interpolate(tSec, [DATELINE_DELAY_SEC, DATELINE_DELAY_SEC + DATELINE_DUR_SEC], [0, 1], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
		easing: Easing.ease,
	});

	const words = card.title.split(' ');

	return (
		<AbsoluteFill style={{pointerEvents: 'none', opacity: exitOpacity}}>
			{/* Scrim layer 1 — teal wash over the whole frame. */}
			<AbsoluteFill style={{backgroundColor: THEME.withAlpha(THEME.secondary, 0.7)}} />
			{/* Scrim layer 2 — vignette darkening the corners. */}
			<AbsoluteFill
				style={{background: 'radial-gradient(120% 120% at 50% 50%, transparent 50%, rgba(0,0,0,0.5) 100%)'}}
			/>

			{/* Content column — absolutely positioned, vertically centred, left
			    aligned. Being absolute it sits above the scrim AbsoluteFills. */}
			<div
				style={{
					position: 'absolute',
					left: EDGE_PX,
					right: EDGE_PX,
					top: '50%',
					transform: 'translateY(-50%)',
					display: 'flex',
					flexDirection: 'column',
				}}
			>
				{/* Eyebrow row — gold bar + eyebrow label. */}
				{card.eyebrow ? (
					<div
						style={{
							display: 'flex',
							alignItems: 'center',
							gap: EYEBROW_GAP_PX,
							opacity: eyebrowIn,
							transform: `translateY(${eyebrowTranslateY}em)`,
						}}
					>
						<div
							style={{
								height: 2,
								width: BAR_W_PX,
								background: THEME.primary,
								transform: `scaleX(${barIn})`,
								transformOrigin: 'left',
							}}
						/>
						<span
							style={{
								fontFamily: LABEL_FONT,
								fontSize: EYEBROW_FONT_PX,
								fontWeight: 500,
								letterSpacing: '0.42em',
								textTransform: 'uppercase',
								color: THEME.primary,
							}}
						>
							{card.eyebrow}
						</span>
					</div>
				) : null}

				{/* Title — per-word masked rise, STACKED one word per line so a
				    multi-word title never overflows the frame width. */}
				<div style={{display: 'flex', flexDirection: 'column', alignItems: 'flex-start', marginTop: TITLE_MARGIN_TOP_PX}}>
					{words.map((word, i) => {
						const wordStart = TITLE_DELAY_SEC + i * TITLE_STAGGER_SEC;
						const wordIn = interpolate(tSec, [wordStart, wordStart + TITLE_DUR_SEC], [0, 1], {
							extrapolateLeft: 'clamp',
							extrapolateRight: 'clamp',
							easing: EASE,
						});
						const riseY = (1 - wordIn) * 105;
						const rot = (1 - wordIn) * 2;

						return (
							<div key={i} style={{overflow: 'hidden', padding: '0.04em 0'}}>
								<div
									style={{
										transform: `translateY(${riseY}%) rotate(${rot}deg)`,
										fontFamily: DISPLAY_FONT,
										fontSize: TITLE_FONT_PX,
										fontWeight: 900,
										letterSpacing: '-0.02em',
										lineHeight: 0.92,
										textTransform: 'uppercase',
										color: THEME.textPrimary,
										whiteSpace: 'nowrap',
									}}
								>
									{word}
								</div>
							</div>
						);
					})}
				</div>

				{/* Footer row — rule + dateline. */}
				{card.subtitle ? (
					<div style={{display: 'flex', alignItems: 'center', gap: FOOTER_GAP_PX, marginTop: FOOTER_MARGIN_TOP_PX}}>
						<div
							style={{
								height: 1,
								width: RULE_W_PX,
								background: THEME.withAlpha(THEME.textPrimary, 0.35),
								transform: `scaleX(${ruleIn})`,
								transformOrigin: 'left',
								flex: 'none',
							}}
						/>
						<span
							style={{
								fontFamily: LABEL_FONT,
								fontSize: DATELINE_FONT_PX,
								fontWeight: 400,
								letterSpacing: '0.2em',
								textTransform: 'uppercase',
								color: THEME.textSecondary,
								opacity: datelineIn,
								whiteSpace: 'nowrap',
							}}
						>
							{card.subtitle}
						</span>
					</div>
				) : null}
			</div>
		</AbsoluteFill>
	);
};
