"use client";
import { useState } from "react";
import { api } from "@/lib/api-client";
import { CharacterModal, type CharacterModalTarget } from "@/components/CharacterModal";
import type { Character } from "@/lib/types";

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
  const [open, setOpen] = useState<{ characterId: string; target: CharacterModalTarget } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [approving, setApproving] = useState(false);

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

  const openCharacter = open ? characters.find((c) => c.id === open.characterId) : undefined;

  return (
    <div className="mt-8 rounded-xl border border-neutral-200 bg-white p-6 dark:border-neutral-800 dark:bg-neutral-900">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Review character wardrobe</h2>
          <p className="mt-0.5 text-xs text-neutral-500 dark:text-neutral-400">
            Click any thumbnail to view it full-size, edit its prompt, and regenerate. Approving
            doesn&apos;t require every thumbnail to be finished.
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

      <div className="mt-6 space-y-6">
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
            {/* flex-wrap, not overflow-x-auto: every variant stays visible at
                once, no hidden/scrolled-off thumbnails. */}
            <div className="mt-3 flex flex-wrap gap-3">
              <div className="flex w-20 flex-col items-center gap-1">
                <button
                  onClick={() => setOpen({ characterId: character.id, target: { kind: "base" } })}
                  className="h-20 w-20 overflow-hidden rounded-lg border border-neutral-200 bg-neutral-100 dark:border-neutral-800 dark:bg-neutral-800"
                >
                  {character.reference_image_url ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={character.reference_image_url} alt="" className="h-full w-full object-cover" />
                  ) : (
                    <div className="flex h-full w-full items-center justify-center text-[9px] text-neutral-400">
                      no image
                    </div>
                  )}
                </button>
                <span className="truncate text-[10px] text-neutral-500 dark:text-neutral-400">Everyday</span>
              </div>
              {character.variants.map((variant) => (
                <div key={variant.variant_id} className="flex w-20 flex-col items-center gap-1">
                  <button
                    onClick={() =>
                      setOpen({ characterId: character.id, target: { kind: "variant", variantId: variant.variant_id } })
                    }
                    className="h-20 w-20 overflow-hidden rounded-lg border border-neutral-200 bg-neutral-100 dark:border-neutral-800 dark:bg-neutral-800"
                  >
                    {variant.image_url ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={variant.image_url} alt="" className="h-full w-full object-cover" />
                    ) : (
                      <div className="flex h-full w-full items-center justify-center px-1 text-center text-[9px] text-neutral-400">
                        no image
                      </div>
                    )}
                  </button>
                  <span className="w-full truncate text-center text-[10px] text-neutral-500 dark:text-neutral-400" title={variant.context_label}>
                    {variant.context_label}
                  </span>
                </div>
              ))}
              {character.variants.length === 0 && (
                <p className="self-center text-xs text-neutral-400">
                  No significant wardrobe contexts needed — everyday outfit used everywhere.
                </p>
              )}
            </div>
          </div>
        ))}
      </div>

      {open && openCharacter && (
        <CharacterModal
          jobId={jobId}
          character={openCharacter}
          initialTarget={open.target}
          onClose={() => setOpen(null)}
          onCharacterUpdated={onCharacterUpdated}
        />
      )}
    </div>
  );
}
