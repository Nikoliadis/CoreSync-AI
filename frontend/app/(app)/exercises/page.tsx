"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Library, Search } from "lucide-react";
import { useState } from "react";

import { PageShell } from "@/components/layout/page-header";
import { TopBar } from "@/components/layout/topbar";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useDebouncedValue } from "@/lib/utils/use-debounced-value";
import { api } from "@/lib/api/client";

type ExerciseMedia = {
  id: string;
  mediaType: "image" | "video" | "animation";
  url: string;
};

type Exercise = {
  id: string;
  name: string;
  primaryMuscleGroup?: string | null;
  equipment?: string[] | null;
  difficulty?: string | null;
  /**
   * Demonstration media, in display order.
   *
   * Optional because most of the catalogue still has none — an exercise without a
   * photograph is the normal case, not an error, so every use of this has to read fine
   * when it is absent.
   */
  media?: ExerciseMedia[] | null;
};

/** The first still image, if there is one. A `video` needs a player this page has not got. */
function thumbnail(exercise: Exercise): string | null {
  const first = (exercise.media ?? []).find(
    (item) => item.mediaType === "image" || item.mediaType === "animation",
  );
  return first?.url ?? null;
}

export default function ExerciseLibraryPage() {
  const [query, setQuery] = useState("");
  // Debounced so typing "bench press" is one request, not eleven.
  const debounced = useDebouncedValue(query, 250);

  const exercises = useQuery({
    queryKey: ["exercises", debounced],
    queryFn: () =>
      api
        .get<{ items: Exercise[]; total: number }>("/v1/exercises", {
          query: { q: debounced || undefined, limit: 40 },
        })
        .then((r) => r.items ?? []),
    // Keeps the previous page visible while the next one loads, so the list
    // does not blank out on every keystroke.
    placeholderData: keepPreviousData,
  });

  return (
    <>
      <TopBar title="Exercise Library" />

      <PageShell>
        <div className="mb-5 max-w-md">
          <Input
            label="Search"
            placeholder="Bench press, squat, row…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            leadingIcon={<Search className="h-4 w-4" />}
            type="search"
          />
        </div>

        {exercises.isLoading && (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 9 }).map((_, i) => (
              <Skeleton key={i} className="h-24" />
            ))}
          </div>
        )}

        {exercises.isError && (
          <EmptyState
            icon={<Library className="h-8 w-8" />}
            title="Couldn't load the catalog"
            description="The exercise library needs a connection. Try again in a moment."
            action={<Button onClick={() => exercises.refetch()}>Try again</Button>}
          />
        )}

        {exercises.isSuccess && exercises.data.length === 0 && (
          <EmptyState
            icon={<Search className="h-8 w-8" />}
            title="Nothing matched"
            description={
              debounced
                ? `No exercises found for "${debounced}". Try a shorter search.`
                : "The catalog is empty."
            }
          />
        )}

        {exercises.isSuccess && exercises.data.length > 0 && (
          <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {exercises.data.map((exercise) => (
              <li key={exercise.id}>
                <Card variant="interactive" className="h-full">
                  {/* Fixed 4:3 whether or not there is an image, so the grid does not
                      reflow as photographs arrive and rows stay aligned. */}
                  <div className="mb-3 aspect-[4/3] w-full overflow-hidden rounded-md bg-surface-well">
                    {thumbnail(exercise) ? (
                      /* A plain img rather than next/image: the catalogue's media
                         origin is configurable and about to move to a CDN, and
                         next/image needs every host declared in next.config. */
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={thumbnail(exercise) ?? ""}
                        alt=""
                        loading="lazy"
                        className="h-full w-full object-cover"
                      />
                    ) : (
                      <div className="flex h-full w-full items-center justify-center">
                        <Library aria-hidden className="size-6 text-text-muted" />
                      </div>
                    )}
                  </div>
                  <p className="text-h3 text-text">{exercise.name}</p>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {exercise.primaryMuscleGroup && (
                      <span className="rounded-sm bg-surface-well px-2 py-0.5 text-overline uppercase text-text-muted">
                        {exercise.primaryMuscleGroup}
                      </span>
                    )}
                    {exercise.difficulty && (
                      <span className="rounded-sm bg-surface-well px-2 py-0.5 text-overline uppercase text-text-muted">
                        {exercise.difficulty}
                      </span>
                    )}
                  </div>
                </Card>
              </li>
            ))}
          </ul>
        )}
      </PageShell>
    </>
  );
}
