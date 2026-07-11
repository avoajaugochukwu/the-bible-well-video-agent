// Two-font system, matched to the reference deck (Title Cards lite).
//
// The deck uses exactly two families, split by ROLE — never mixed at random:
//
//   DISPLAY  → Archivo   The loud text: headlines, card titles, big figures.
//                        Heavy weights (700–900), TIGHT tracking (negative
//                        letter-spacing), large sizes. ~60 uses in the deck.
//
//   LABEL    → Oswald    The quiet text: eyebrows, kickers, captions, list
//                        items, stat labels, index numbers ("01"/"02").
//                        Medium weights (400–500), almost always UPPERCASE,
//                        tracked-OUT (positive letter-spacing), small sizes.
//                        ~50 uses in the deck.
//
// Rule of thumb when building a new card: the single biggest thing on the
// frame is DISPLAY; everything that supports/labels it is LABEL.
//
// Both families load via the Google Fonts @import in src/index.css (Archivo
// 400;600;700;800;900 · Oswald 300;400;500;600;700) so Lambda's headless
// Chrome has them at render time. Keep the weights here in sync with that
// @import if a card needs a weight not yet loaded.

export const DISPLAY_FONT = '"Archivo", "Helvetica Neue", system-ui, sans-serif';
export const LABEL_FONT = '"Oswald", "Helvetica Neue", system-ui, sans-serif';
