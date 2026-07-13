import React from 'react';
import {AbsoluteFill, useCurrentFrame, useVideoConfig} from 'remotion';
import {DISPLAY_FONT} from '../typography';

export type Word = {word: string; start: number; end: number};

const CHUNK_SIZE = 6;
const HIGHLIGHT_COLOR = '#ff3b30';
const TEXT_COLOR = '#ffffff';

const chunkWords = (words: Word[]): Word[][] => {
	const chunks: Word[][] = [];
	for (let i = 0; i < words.length; i += CHUNK_SIZE) {
		chunks.push(words.slice(i, i + CHUNK_SIZE));
	}
	return chunks;
};

export const Captions: React.FC<{words: Word[]}> = ({words}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const tSec = frame / fps;

	if (!words.length) return null;

	const chunks = chunkWords(words);
	const activeChunk =
		chunks.find((c) => tSec >= c[0].start && tSec < c[c.length - 1].end + 0.15) ??
		(tSec < words[0].start ? chunks[0] : chunks[chunks.length - 1]);

	return (
		<AbsoluteFill style={{pointerEvents: 'none'}}>
			<div
				style={{
					position: 'absolute',
					bottom: 160,
					left: 0,
					right: 0,
					textAlign: 'center',
					padding: '0 80px',
					fontFamily: DISPLAY_FONT,
					fontWeight: 800,
					fontSize: 56,
					lineHeight: 1.25,
					textShadow: '0 4px 18px rgba(0,0,0,0.75)',
				}}
			>
				{activeChunk.map((w, i) => {
					const isActive = tSec >= w.start && tSec < w.end;
					return (
						<span key={i} style={{color: isActive ? HIGHLIGHT_COLOR : TEXT_COLOR}}>
							{w.word}{' '}
						</span>
					);
				})}
			</div>
		</AbsoluteFill>
	);
};
