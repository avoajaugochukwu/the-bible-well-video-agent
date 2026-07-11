import {AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import type {PlacedCard} from '../cardTypes';
import {SAFE_BOTTOM_PX} from '../layout';
import {THEME} from '../theme';
import {LABEL_FONT} from '../typography';

// ─── Animation timing ──────────────────────────────────────────────────────
// Fixed 5s window (0.4 in + 4.2 hold + 0.4 out). Keep in sync with
// cardDurations.ts (PHOTO_CAPTION_DURATION_SEC).
const IN_SEC = 0.5;
const OUT_SEC = 0.4;

type Props = {
	card: Extract<PlacedCard, {kind: 'photo-caption'}>;
};

// Contextual caption, ref-matched: a LIGHT (cream/white) badge with dark
// uppercase Oswald text, bottom-left, revealed by a clean left-to-right wipe
// (clip-path). Colors are theme-driven — light backing = textPrimary, dark
// ink = surface — so a custom accent/theme still inverts cleanly. Timing is
// driven off the Sequence's own duration so it stays in lockstep with the
// registry duration.
export const PhotoCaption: React.FC<Props> = ({card}) => {
	const frame = useCurrentFrame();
	const {fps, durationInFrames} = useVideoConfig();

	const fadeFrames = Math.round(OUT_SEC * fps);
	const fadeStart = durationInFrames - fadeFrames;
	const fadeOpacity = interpolate(frame, [fadeStart, durationInFrames], [1, 0], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
	});

	// Left-to-right wipe-in over the first IN_SEC: clip-path inset right edge
	// recedes 100% → 0%. Ease-out so it starts fast then settles at the end.
	const wipe = interpolate(frame, [0, IN_SEC * fps], [100, 0], {
		easing: Easing.out(Easing.cubic),
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
	});

	return (
		<AbsoluteFill style={{pointerEvents: 'none'}}>
			<div
				style={{
					position: 'absolute',
					left: 96,
					bottom: SAFE_BOTTOM_PX,
					maxWidth: '55%',
					opacity: fadeOpacity,
					clipPath: `inset(0 ${wipe}% 0 0)`,
				}}
			>
				{/* Light/inverted backing box (sharp corners) so the caption reads as
				    a clean editorial lower-third over any scene image. Hugs the text
				    via inline-block + padding. */}
				<h1
					style={{
						display: 'inline-block',
						backgroundColor: THEME.textPrimary,
						color: THEME.surface,
						fontFamily: LABEL_FONT,
						fontSize: 60,
						fontWeight: 600,
						lineHeight: 1.05,
						margin: 0,
						padding: '25px 42px',
						letterSpacing: 3,
						textTransform: 'uppercase',
						textAlign: 'left',
					}}
				>
					{card.text}
				</h1>
			</div>
		</AbsoluteFill>
	);
};
