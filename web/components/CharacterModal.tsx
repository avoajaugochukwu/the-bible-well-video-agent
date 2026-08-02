"use client";
import { useState } from "react";
import { api } from "@/lib/api-client";
import type { Character, CharacterVariant } from "@/lib/types";

export type CharacterModalTarget = { kind: "base" } | { kind: "variant"; variantId: string };

function targetKey(t: CharacterModalTarget): string {
  return t.kind === "base" ? "base" : t.variantId;
}

export function CharacterModal({
  jobId,
  character,
  initialTarget,
  onClose,
  onCharacterUpdated,
}: {
  jobId: string;
  character: Character;
  initialTarget: CharacterModalTarget;
  onClose: () => void;
  onCharacterUpdated: (character: Character) => void;
}) {
  const [target, setTarget] = useState<CharacterModalTarget>(initialTarget);
  const [editedPrompts, setEditedPrompts] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const activeVariant =
    target.kind === "variant" ? character.variants.find((v) => v.variant_id === target.variantId) : undefined;
  const activeUrl = target.kind === "base" ? character.reference_image_url : activeVariant?.image_url;
  const activeLabel = target.kind === "base" ? "Everyday (base)" : activeVariant?.context_label || "";
  const defaultPrompt =
    target.kind === "base"
      ? character.reference_prompt || character.appearance || ""
      : activeVariant?.reference_prompt || activeVariant?.outfit_prompt || "";
  const key = targetKey(target);
  const prompt = editedPrompts[key] ?? defaultPrompt;

  function setPrompt(value: string) {
    setEditedPrompts((p) => ({ ...p, [key]: value }));
  }

  async function regenerate() {
    if (!prompt.trim()) return;
    setBusy(true);
    setError(null);
    try {
      if (target.kind === "base") {
        const updated = (await api.regenerateCharacterImage(jobId, character.id, prompt)) as Character;
        onCharacterUpdated(updated);
      } else {
        const updatedVariant = (await api.regenerateCharacterImage(
          jobId,
          character.id,
          prompt,
          target.variantId,
        )) as CharacterVariant;
        onCharacterUpdated({
          ...character,
          variants: character.variants.map((v) => (v.variant_id === target.variantId ? updatedVariant : v)),
        });
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div
        className="flex h-[90vh] w-[95vw] max-w-5xl flex-col overflow-hidden rounded-2xl bg-white shadow-xl dark:bg-neutral-900"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-neutral-200 px-5 py-4 dark:border-neutral-800">
          <div>
            <p className="text-sm font-medium">
              {character.name || character.id}
              {character.role && (
                <span className="ml-2 text-xs font-normal text-neutral-500 dark:text-neutral-400">
                  {character.role}
                </span>
              )}
            </p>
            <p className="mt-0.5 text-xs text-neutral-500 dark:text-neutral-400">{activeLabel}</p>
          </div>
          <button onClick={onClose} className="text-neutral-400 hover:text-neutral-700 dark:hover:text-neutral-200">
            ✕
          </button>
        </div>

        <div className="flex flex-1 overflow-hidden">
          <div className="flex w-[55%] flex-col overflow-y-auto border-r border-neutral-200 p-5 dark:border-neutral-800">
            <div className="mx-auto aspect-[3/4] w-full max-w-sm overflow-hidden rounded-lg bg-black">
              {activeUrl ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={activeUrl} alt="" className="h-full w-full object-contain" />
              ) : (
                <div className="flex h-full w-full items-center justify-center text-sm text-neutral-500">
                  no image yet
                </div>
              )}
            </div>

            <p className="mt-4 text-xs font-medium text-neutral-500 dark:text-neutral-400">
              Click a thumbnail to view and edit it
            </p>
            <div className="mt-2 flex flex-wrap gap-2">
              <button
                onClick={() => setTarget({ kind: "base" })}
                title="Everyday (base)"
                className={`h-16 w-16 overflow-hidden rounded-md border-2 bg-neutral-100 dark:bg-neutral-800 ${
                  target.kind === "base" ? "border-indigo-500" : "border-transparent opacity-70 hover:opacity-100"
                }`}
              >
                {character.reference_image_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={character.reference_image_url} alt="" className="h-full w-full object-cover" />
                ) : (
                  <div className="flex h-full w-full items-center justify-center text-[9px] text-neutral-400">
                    base
                  </div>
                )}
              </button>
              {character.variants.map((v) => (
                <button
                  key={v.variant_id}
                  onClick={() => setTarget({ kind: "variant", variantId: v.variant_id })}
                  title={v.context_label}
                  className={`h-16 w-16 overflow-hidden rounded-md border-2 bg-neutral-100 dark:bg-neutral-800 ${
                    target.kind === "variant" && target.variantId === v.variant_id
                      ? "border-indigo-500"
                      : "border-transparent opacity-70 hover:opacity-100"
                  }`}
                >
                  {v.image_url ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={v.image_url} alt="" className="h-full w-full object-cover" />
                  ) : (
                    <div className="flex h-full w-full items-center justify-center px-1 text-center text-[9px] text-neutral-400">
                      {v.context_label}
                    </div>
                  )}
                </button>
              ))}
            </div>
          </div>

          <div className="flex w-[45%] flex-col overflow-y-auto px-5 py-4">
            {error && (
              <p className="mb-3 rounded-md bg-red-50 px-3 py-2 text-xs text-red-700 dark:bg-red-950 dark:text-red-300">
                {error}
              </p>
            )}
            <p className="text-xs font-medium text-neutral-500 dark:text-neutral-400">
              Prompt — the exact text sent to generate this image
            </p>
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              rows={14}
              className="mt-2 w-full flex-1 rounded-lg border border-neutral-300 bg-white p-3 text-sm dark:border-neutral-700 dark:bg-neutral-800"
            />
            <button
              disabled={busy || !prompt.trim()}
              onClick={regenerate}
              className="mt-3 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
            >
              {busy ? "Regenerating…" : "Regenerate"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
