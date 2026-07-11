import {AbsoluteFill, OffthreadVideo, Sequence, staticFile, useCurrentFrame, useVideoConfig} from 'remotion'
import {SUBSCRIBE_BOTTOM_PX} from '../layout'

const SLIDE_IN_SEC = 0.5
const SLIDE_OUT_SEC = 0.5
const OFFSET_PX = 50

// Asset duration, pre-probed once: ffprobe Subscribe-button.webm => 7.4s.
const SUBSCRIBE_DURATION_SEC = 7.4
const SUBSCRIBE_ASSET = 'Subscribe-button.webm'

// Sized to ~21% of a 1920-wide composition.
const SUBSCRIBE_WIDTH_PX = 411

const Inner: React.FC<{assetFile: string; assetDurationSec: number}> = ({assetFile, assetDurationSec}) => {
	const frame = useCurrentFrame()
	const {fps} = useVideoConfig()
	const tSec = frame / fps

	const slideIn = SLIDE_IN_SEC
	const slideOut = SLIDE_OUT_SEC
	const holdEnd = assetDurationSec - slideOut

	let progress: number
	if (tSec <= slideIn) {
		progress = tSec / slideIn
	} else if (tSec <= holdEnd) {
		progress = 1
	} else if (tSec <= assetDurationSec) {
		progress = 1 - (tSec - holdEnd) / slideOut
	} else {
		progress = 0
	}

	const translatePct = (1 - progress) * 100
	const opacity = progress > 0 ? 1 : 0

	return (
		<AbsoluteFill style={{pointerEvents: 'none'}}>
			<div
				style={{
					position: 'absolute',
					bottom: SUBSCRIBE_BOTTOM_PX,
					right: OFFSET_PX,
					width: SUBSCRIBE_WIDTH_PX,
					transform: `translateX(${translatePct}%)`,
					opacity,
				}}
			>
				<OffthreadVideo
					src={staticFile(assetFile)}
					muted
					// transparent → Remotion extracts frames as PNG (with alpha) instead
					// of JPEG, preserving the VP9 webm's alpha channel through Lambda.
					transparent
					style={{width: '100%', display: 'block'}}
				/>
			</div>
		</AbsoluteFill>
	)
}

type Props = {
	placementsSec: number[]
}

export const SubscribeOverlay: React.FC<Props> = ({placementsSec}) => {
	const {fps} = useVideoConfig()
	return (
		<>
			{placementsSec.map((startSec, i) => {
				const fromFrame = Math.max(0, Math.round(startSec * fps))
				const durationInFrames = Math.max(1, Math.round(SUBSCRIBE_DURATION_SEC * fps))
				return (
					<Sequence key={`subscribe-${i}-${startSec}`} from={fromFrame} durationInFrames={durationInFrames} layout="none">
						<Inner assetFile={SUBSCRIBE_ASSET} assetDurationSec={SUBSCRIBE_DURATION_SEC} />
					</Sequence>
				)
			})}
		</>
	)
}

const SUBSCRIBE_INTERVAL_SEC = 120 // every 2 min, hardcoded per product
const SUBSCRIBE_FIRST_PLACEMENT_SEC = 30

// Every 2 min starting at 30s, skipping any placement whose full window would
// run past the video end. Independent of scene/card timing by design — it can
// coexist with anything else on screen.
export const computeSubscribePlacements = (videoDurationSec: number): number[] => {
	const placements: number[] = []
	for (let t = SUBSCRIBE_FIRST_PLACEMENT_SEC; t + SUBSCRIBE_DURATION_SEC <= videoDurationSec; t += SUBSCRIBE_INTERVAL_SEC) {
		placements.push(t)
	}
	return placements
}
