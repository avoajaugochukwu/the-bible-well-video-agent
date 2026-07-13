import React from 'react';
import {AbsoluteFill, Audio, Img, Sequence, interpolate, useCurrentFrame} from 'remotion';
import {SubscribeOverlay, computeSubscribePlacements} from './overlays/SubscribeOverlay';
import {Captions, type Word} from './overlays/Captions';

// ---------------------------------------------------------------------------
// Motion spec, revised per user feedback:
// - No rotation - zoom only.
// - The image must NEVER stop moving - one continuous zoom interpolation
//   across a scene's ENTIRE on-screen duration, no flat/paused phase.
// - Every scene starts AND ends at ZOOM_EDGE (native full-bleed cover, no
//   crop) - a brief punch-in to PEAK_SCALE in between. Turnaround point is a
//   fraction of that scene's OWN duration_frames (ZOOM_IN_FRACTION), so it
//   scales correctly whether a scene is 4s or 12s.
// - True crossfade: only ONE shared black backdrop for the whole composition
//   (see HeritageScenes) - a scene must never carry its own opaque
//   background, or it occludes the scene fading out underneath it.
// - Durations are per-scene, not a single global constant. Real scenes will
//   have variable length (driven by narration alignment later) - the timing/
//   placement math below is written against each scene's own duration so
//   swapping in real per-scene durations later doesn't require touching this
//   file again.
// ---------------------------------------------------------------------------

export const FPS = 30;

// Used only when a scene doesn't specify its own duration_frames (today's
// test data doesn't) - NOT a global constant the animation logic depends on.
export const DEFAULT_SCENE_DURATION_FRAMES = 180; // 6.0s @ 30fps

// Fraction of a scene's OWN duration spent fading in / out (opacity only -
// this is what makes the crossfade), and consecutive scenes overlap by this
// fraction of the shorter neighbor's duration. Independent of duration, so
// it scales correctly whether a scene is 3s or 12s.
const FADE_FRACTION = 0.18;
const CROSSFADE_FRACTION = 0.18;

// No rotation, so scale 1.0 is already exact full-frame cover (objectFit:
// cover handles that) - ZOOM_EDGE IS that native edge, the true "no crop"
// state. Every scene's zoom starts AND ends exactly here.
const ZOOM_EDGE = 1.0;
const PEAK_SCALE = 1.3; // the "bit" of zoom-in at the turnaround
// First 25% of the scene's own duration is the rise to PEAK_SCALE, the
// remaining 75% is the (slower, calmer) fall back to ZOOM_EDGE.
const ZOOM_IN_FRACTION = 0.25;

export type Scene = {
	scene_number: number;
	image_url: string;
	// Optional: lets a future caller drive per-scene timing from real
	// narration alignment without changing any logic below.
	duration_frames?: number;
};

const SingleScene: React.FC<{scene: Scene; durationInFrames: number}> = ({
	scene,
	durationInFrames,
}) => {
	const frame = useCurrentFrame(); // relative to this <Sequence>'s `from`
	const fadeFrames = Math.round(durationInFrames * FADE_FRACTION);

	// Opacity only controls the crossfade edges - it's the one thing that IS
	// flat (at 1) through the middle, since it's about visibility, not motion.
	const opacity = interpolate(
		frame,
		[0, fadeFrames, durationInFrames - fadeFrames, durationInFrames],
		[0, 1, 1, 0],
		{extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}
	);

	// Continuous zoom across the ENTIRE scene - rises from the edge to
	// PEAK_SCALE over the first ZOOM_IN_FRACTION of the scene's own duration,
	// then falls back to the edge for the rest. Never stops moving, never
	// flat.
	// Clamped so the 3 breakpoints stay strictly increasing even for a very
	// short scene (interpolate() requires that).
	const peakFrame = Math.min(
		Math.max(1, Math.round(durationInFrames * ZOOM_IN_FRACTION)),
		durationInFrames - 1
	);
	const scale = interpolate(
		frame,
		[0, peakFrame, durationInFrames],
		[ZOOM_EDGE, PEAK_SCALE, ZOOM_EDGE],
		{extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}
	);

	// No per-scene opaque background here - only the true crossfade layer.
	// HeritageScenes below owns the ONE shared black backdrop; if each scene
	// wrapped its own opaque black AbsoluteFill, the later (higher-stacked)
	// scene's backing would occlude the earlier scene's fading image the
	// moment its Sequence went active, turning the intended crossfade into a
	// hard cut to black underneath the incoming photo.
	return (
		<AbsoluteFill
			style={{
				opacity,
				transform: `scale(${scale})`,
			}}
		>
			<Img
				src={scene.image_url}
				style={{
					width: '100%',
					height: '100%',
					objectFit: 'cover',
				}}
			/>
		</AbsoluteFill>
	);
};

type SceneTiming = {from: number; durationInFrames: number};

// Places each scene's <Sequence>, overlapping consecutive scenes by
// CROSSFADE_FRACTION of the shorter neighbor's duration. Written against
// each scene's own duration_frames (falling back to the default) so this
// keeps working unchanged once real per-scene durations vary.
const computeSceneTimings = (scenes: Scene[]): SceneTiming[] => {
	const timings: SceneTiming[] = [];
	let cursor = 0;
	scenes.forEach((scene, i) => {
		const duration = scene.duration_frames ?? DEFAULT_SCENE_DURATION_FRAMES;
		if (i === 0) {
			timings.push({from: 0, durationInFrames: duration});
			cursor = duration;
			return;
		}
		const prevDuration = timings[i - 1].durationInFrames;
		const overlap = Math.round(Math.min(prevDuration, duration) * CROSSFADE_FRACTION);
		const from = cursor - overlap;
		timings.push({from, durationInFrames: duration});
		cursor = from + duration;
	});
	// Overlap shrinks the total below the sum of each scene's own duration_frames
	// (what the narration was aligned to) — pad the last scene so total playback
	// still covers the full narration instead of truncating the tail.
	const rawTotal = scenes.reduce((sum, s) => sum + (s.duration_frames ?? DEFAULT_SCENE_DURATION_FRAMES), 0);
	const shrink = rawTotal - cursor;
	if (shrink > 0 && timings.length > 0) {
		timings[timings.length - 1].durationInFrames += shrink;
	}
	return timings;
};

export const computeTotalDurationInFrames = (scenes: Scene[]): number => {
	if (scenes.length === 0) return 0;
	const timings = computeSceneTimings(scenes);
	const last = timings[timings.length - 1];
	return last.from + last.durationInFrames;
};

export const HeritageScenes: React.FC<{scenes: Scene[]; narrationUrl?: string; words?: Word[]}> = ({
	scenes,
	narrationUrl,
	words,
}) => {
	const timings = computeSceneTimings(scenes);
	const totalDurationSec = computeTotalDurationInFrames(scenes) / FPS;
	const subscribePlacementsSec = computeSubscribePlacements(totalDurationSec);
	return (
		<AbsoluteFill style={{backgroundColor: 'black'}}>
			{narrationUrl ? <Audio src={narrationUrl} /> : null}
			{scenes.map((scene, index) => (
				<Sequence
					key={scene.scene_number}
					from={timings[index].from}
					durationInFrames={timings[index].durationInFrames}
				>
					<SingleScene scene={scene} durationInFrames={timings[index].durationInFrames} />
				</Sequence>
			))}
			<Captions words={words ?? []} />
			<SubscribeOverlay placementsSec={subscribePlacementsSec} />
		</AbsoluteFill>
	);
};
