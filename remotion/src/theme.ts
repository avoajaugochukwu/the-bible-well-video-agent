// Heritage has no per-video theme system (single Krea "digital painting"
// look, not the reference's multi-theme deck) — hardcode the reference's
// default "teal" preset (lib/theme.ts: resolveTheme()) as one flat constant
// every card imports instead of calling useTheme().

const clamp = (n: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, n));

const hexToRgb = (hex: string): {r: number; g: number; b: number} => {
	let h = hex.replace('#', '').trim();
	if (h.length === 3) h = h.split('').map((c) => c + c).join('');
	const n = parseInt(h, 16);
	return {r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255};
};

// Emit a valid `rgba(r,g,b,a)` from any hex color + alpha in [0,1].
const withAlpha = (color: string, alpha: number): string => {
	const {r, g, b} = hexToRgb(color);
	return `rgba(${r}, ${g}, ${b}, ${clamp(alpha, 0, 1)})`;
};

export const THEME = {
	background: '#0a0a0a',
	surface: '#1a1a1a',
	surfaceRaised: '#262626',
	textPrimary: '#ffffff',
	textSecondary: '#d9d9d9',
	textMuted: 'rgba(255,255,255,0.65)',
	primary: '#e7c24b', // gold — accents: index numbers, eyebrows, underlines, bars
	secondary: '#0e3b44', // dark teal — washes / overlays / panels
	border: 'rgba(255,255,255,0.12)',
	shadow: 'rgba(0,0,0,0.55)',
	withAlpha,
};
