"use client";
import { useState } from "react";
import { api } from "@/lib/api-client";
import type { Character, CharacterVariant } from "@/lib/types";

function Thumb({
  url,
  label,
  prompt,
  busy,
  onPromptChange,
  onRegenerate,
}: {
  url?: string | null;
  label: string;
  prompt: string;
  busy: boolean;
  onPromptChange: (v: string) => void;
  onRegenerate: () => void;
}) {
  return (
    <div className="w-56 shrink-0 rounded-xl border border-neutral-200 bg-white p-3 dark:border-neutral-800 dark:bg-neutral-900">
      <div className="aspect-[3/4] w-full overflow-hidden rounded-lg bg-neutral-100 dark:bg-neutral-800">
        {url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={url} alt="" className="h-full w-full object-cover" />
        ) : (
          <div className="flex h-full w-full items-center justify-center text-center text-xs text-neutral-400">
            {busy ? "generating…" : "no image yet"}
          </div>
        )}
      </div>
      <p className="mt-2 truncate text-xs font-semibold" title={label}>
        {label}
      </p>
      <textarea
        value={prompt}
        onChange={(e) => onPromptChange(e.target.value)}
        rows={3}
        className="mt-2 w-full rounded-lg border border-neutral-300 bg-white p-2 text-[11px] leading-snug dark:border-neutral-700 dark:bg-neutral-800"
      />
      <button
        disabled={busy || !prompt.trim()}
        onClick={onRegenerate}
        className="mt-2 w-full rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50"
      >
        {busy ? "Regenerating…" : "Regenerate"}
      </button>
    </div>
  );
}

export function CharacterWardrobeReview({
  jobId,
  characters,
  onCharacterUpdated,
  onApproved,
}: {
  jobId: string;
  characters: Character[];
  onCharacterUpdated: (character: Character) => void;
  onApproved: () => void;
}) {
  const [prompts, setPrompts] = useState<Record<string, string>>({});
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [approving, setApproving] = useState(false);

  function promptFor(key: string, fallback?: string | null) {
    return prompts[key] ?? fallback ?? "";
  }
  function setPrompt(key: string, value: string) {
    setPrompts((p) => ({ ...p, [key]: value }));
  }

  async function regenerateBase(character: Character) {
    const key = `${character.id}::base`;
    const prompt = promptFor(key, character.appearance).trim();
    if (!prompt) return;
    setBusyKey(key);
    setError(null);
    try {
      const updated = (await api.regenerateCharacterImage(jobId, character.id, prompt)) as Character;
      onCharacterUpdated(updated);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusyKey(null);
    }
  }

  async function regenerateVariant(character: Character, variant: CharacterVariant) {
    const key = `${character.id}::${variant.variant_id}`;
    const prompt = promptFor(key, variant.outfit_prompt).trim();
    if (!prompt) return;
    setBusyKey(key);
    setError(null);
    try {
      // The backend returns just the updated variant here, not the whole
      // character — merge it into a fresh copy for the parent's job state.
      const updated = (await api.regenerateCharacterImage(
        jobId,
        character.id,
        prompt,
        variant.variant_id,
      )) as CharacterVariant;
      onCharacterUpdated({
        ...character,
        variants: character.variants.map((v) => (v.variant_id === variant.variant_id ? updated : v)),
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusyKey(null);
    }
  }

  async function approve() {
    setApproving(true);
    setError(null);
    try {
      await api.approveWardrobe(jobId);
      onApproved();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setApproving(false);
    }
  }

  return (
    <div className="mt-8 rounded-xl border border-neutral-200 bg-white p-6 dark:border-neutral-800 dark:bg-neutral-900">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Review character wardrobe</h2>
          <p className="mt-0.5 text-xs text-neutral-500 dark:text-neutral-400">
            Confirm each character&apos;s everyday look and every significant-context outfit before
            scene images generate. Approving doesn&apos;t require every thumbnail to be finished.
          </p>
        </div>
        <button
          onClick={approve}
          disabled={approving}
          className="shrink-0 rounded-lg bg-indigo-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-500 disabled:opacity-50"
        >
          {approving ? "Approving…" : "Approve & Generate Scene Images"}
        </button>
      </div>

      {error && (
        <p className="mt-4 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">
          {error}
        </p>
      )}

      <div className="mt-6 space-y-8">
        {characters.map((character) => (
          <div key={character.id}>
            <h3 className="text-sm font-semibold">
              {character.name || character.id}
              {character.role && (
                <span className="ml-2 text-xs font-normal text-neutral-500 dark:text-neutral-400">
                  {character.role}
                </span>
              )}
            </h3>
            <div className="mt-3 flex gap-4 overflow-x-auto pb-1">
              <Thumb
                url={character.reference_image_url}
                label="Everyday (base)"
                prompt={promptFor(`${character.id}::base`, character.appearance)}
                busy={busyKey === `${character.id}::base`}
                onPromptChange={(v) => setPrompt(`${character.id}::base`, v)}
                onRegenerate={() => regenerateBase(character)}
              />
              {character.variants.map((variant) => (
                <Thumb
                  key={variant.variant_id}
                  url={variant.image_url}
                  label={variant.context_label}
                  prompt={promptFor(`${character.id}::${variant.variant_id}`, variant.outfit_prompt)}
                  busy={busyKey === `${character.id}::${variant.variant_id}`}
                  onPromptChange={(v) => setPrompt(`${character.id}::${variant.variant_id}`, v)}
                  onRegenerate={() => regenerateVariant(character, variant)}
                />
              ))}
              {character.variants.length === 0 && (
                <p className="self-center text-xs text-neutral-400">
                  No significant wardrobe contexts needed — everyday outfit used everywhere this
                  character appears.
                </p>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
