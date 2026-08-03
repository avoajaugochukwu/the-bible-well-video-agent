// Job/scene shapes for the bible-well production UI. One row per job in
// Supabase (bible_well_jobs), payload is this whole Job as JSONB — same
// single-table-JSONB pattern as military/lib/review/types.ts.

export type JobStatus =
  | "queued"
  | "awaiting_wardrobe_approval"
  | "preparing"
  | "ready"
  | "rendering"
  | "rendered"
  | "failed";

export type AssetSource = "gpt-image" | "pexels" | "upload" | "video-gen";

/** Which reference (a character's base image, or one wardrobe variant) an
 * image actually resolved to for one present character — a plain fact
 * src/supabase_jobs.py stores verbatim from agents/scene_compositor's own
 * Python dict, not projected to camelCase (same as `Character` below), so the
 * inner keys stay snake_case even though this field's own name is camelCase. */
export interface CharacterRefUsed {
  character_id: string;
  variant_id?: string | null;
}

/** One past generation/pick for a scene — appended, never overwritten, so the
 * user can pick any previous image or video back into the active slot. */
export interface AssetHistoryItem {
  id: string;
  url: string;
  source: AssetSource;
  prompt?: string;
  characterRefsUsed?: CharacterRefUsed[];
  createdAt: string;
}

/** One wardrobe outfit for a tracked character, for a significant recurring
 * context (a wedding, a work uniform) — everyday scenes just use the
 * character's base reference_image_url instead. Written by
 * agents/character_wardrobe + agents/character_sheet's generate_variants_all(),
 * stored on the job payload verbatim (Python's own snake_case dict shape, same
 * as `Character` below). */
export interface CharacterVariant {
  variant_id: string;
  /** Short human-readable phrase for a production reviewer, e.g. "Wedding guest". */
  context_label: string;
  /** Compact clothing-only sentence agents/character_wardrobe decided on. */
  outfit_prompt?: string;
  /** The FULL prompt actually sent to gpt-image-2 for this variant's image
   * (style scaffold + the character's locked identity text + outfit_prompt) —
   * what the review UI shows/edits, so what you see is what gets sent on
   * regenerate. Always set once generation has run, even if it failed. */
  reference_prompt?: string;
  image_url?: string | null;
  /** Which scenes this variant applies to — every other scene the character
   * appears in uses the base reference_image_url. */
  scene_numbers: number[];
}

/** The locked character ledger, extended with wardrobe variants. Stored
 * verbatim from Python (not camelCase-projected — same reasoning as
 * CharacterRefUsed above), because agents/scene_compositor and
 * agents/character_sheet read this exact shape back on the Python side too. */
export interface Character {
  id: string;
  name?: string;
  role?: string;
  appearance?: string;
  reference_image_url?: string | null;
  /** The FULL prompt actually sent for the base image (style scaffold +
   * appearance) — same reasoning as CharacterVariant.reference_prompt. */
  reference_prompt?: string;
  variants: CharacterVariant[];
}

export interface SceneAsset {
  imageHistory: AssetHistoryItem[];
  videoHistory: AssetHistoryItem[];
  activeImageId?: string;
  activeVideoId?: string;
  /** Which of image/video actually renders — video only wins while one is
   * active; deleting/clearing the active video falls back to the image. */
  mode: "image" | "video";
}

export interface Scene {
  sceneNumber: number;
  scriptSnippet: string;
  sceneType?: string;
  visualMode?: "concrete" | "abstract";
  characterIds: string[];
  heroSubject?: string;
  imagePrompt: string;
  /** Real Whisper+DTW-aligned narration length for this scene, in seconds —
   * how long a video clip needs to be to cover it. */
  durationSeconds?: number;
  asset: SceneAsset;
}

export interface Job {
  id: string; // Baserow row_id
  createdAt: string;
  status: JobStatus;
  title?: string;
  clickupUrl?: string;
  scenes: Scene[];
  renderUrl?: string;
  error?: string;
  /** Which stage the last failure happened in — undefined on older jobs
   * predating this field, treated as "render" for display. */
  failedStage?: "prepare" | "render";
  /** What prepare_cast_and_scenes()/prepare_images_and_align() is doing right
   * now (e.g. "Generating images"), while status is 'preparing'. Cleared once
   * the job is 'ready'. */
  currentStage?: string;
  /** Scene-image progress: `total` scenes to illustrate, `completed` that have
   * one. Written by src/supabase_jobs.py as the compositor works through them,
   * so the UI can show a real bar instead of a spinner. */
  total?: number;
  completed?: number;
  /** The locked character ledger (ids, appearance, reference image urls, and
   * wardrobe variants). Lives on the payload because the container keeps
   * nothing on disk and the regenerate-image/wardrobe-review routes need it. */
  characters?: Character[];
  /** Set once the finished video url has been prepended to the ClickUp task —
   * the gate that stops a second render pass prepending it twice. */
  clickupPushedAt?: string;
}

export interface JobSummary {
  id: string;
  createdAt: string;
  status: JobStatus;
  title?: string;
  sceneCount: number;
  currentStage?: string;
  clickupUrl?: string;
  total?: number;
  completed?: number;
}

/** Mirrors src/supabase_jobs.py's _resolve_asset — which url actually renders
 * for this scene right now (video wins while one is active). */
export function activeAssetUrl(scene: Scene): { url: string; kind: "image" | "video" } | null {
  const { asset } = scene;
  if (asset.mode === "video") {
    const video = asset.videoHistory.find((v) => v.id === asset.activeVideoId);
    if (video) return { url: video.url, kind: "video" };
  }
  const image = asset.imageHistory.find((i) => i.id === asset.activeImageId);
  return image ? { url: image.url, kind: "image" } : null;
}

export interface ResolvedCharacterRef {
  characterId: string;
  /** Human-readable, never a bare internal id — disambiguated with the
   * character's role in parens if two tracked characters share a first name
   * (a real case in this pipeline), e.g. "Samuel (church garden friend)" vs
   * "Samuel (neighbor)". */
  label: string;
  /** Human-readable context, e.g. "Wedding guest" — "Everyday" when no
   * wardrobe variant applied (the character's base outfit was used). */
  contextLabel: string;
}

/** Which reference each present character actually resolved to for a scene's
 * ACTIVE image (not just whatever the scene was cut with) — the production
 * UI's per-scene audit display, resolved to human-readable names/contexts by
 * joining against `job.characters`. */
export function resolveCharacterRefsUsed(scene: Scene, characters: Character[]): ResolvedCharacterRef[] {
  const active = scene.asset.imageHistory.find((i) => i.id === scene.asset.activeImageId);
  const refsUsed = active?.characterRefsUsed;
  if (!refsUsed || refsUsed.length === 0) return [];

  const byId = new Map(characters.map((c) => [c.id, c]));
  const nameCounts = new Map<string, number>();
  for (const c of characters) {
    const name = c.name || c.id;
    nameCounts.set(name, (nameCounts.get(name) || 0) + 1);
  }

  return refsUsed.map((ref) => {
    const character = byId.get(ref.character_id);
    const name = character?.name || ref.character_id;
    const ambiguous = (nameCounts.get(name) || 0) > 1;
    const label = ambiguous && character?.role ? `${name} (${character.role})` : name;
    const variant = character?.variants.find((v) => v.variant_id === ref.variant_id);
    return { characterId: ref.character_id, label, contextLabel: variant?.context_label || "Everyday" };
  });
}

export function jobSummary(job: Job): JobSummary {
  return {
    id: job.id,
    createdAt: job.createdAt,
    status: job.status,
    title: job.title,
    sceneCount: job.scenes.length,
    currentStage: job.currentStage,
    clickupUrl: job.clickupUrl,
    total: job.total,
    completed: job.completed,
  };
}
