import React from 'react';
import {Composition} from 'remotion';
import {
	FPS,
	HeritageScenes,
	Scene,
	computeTotalDurationInFrames,
} from './HeritageScenes';
import type {PlacedCard} from './cardTypes';
import payload from './scenes.json';

const {scenes, narrationUrl, cards} = payload as {
	scenes: Scene[];
	narrationUrl?: string;
	cards?: PlacedCard[];
};

export const RemotionRoot: React.FC = () => {
	return (
		<Composition
			id="HeritageScenes"
			component={HeritageScenes}
			durationInFrames={computeTotalDurationInFrames(scenes)}
			fps={FPS}
			width={1920}
			height={1080}
			defaultProps={{scenes, narrationUrl, cards}}
		/>
	);
};
