"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Camera, Loader2, Trash2, TriangleAlert } from "lucide-react";
import { useMemo, useRef, useState } from "react";

import { PageShell } from "@/components/layout/page-header";
import { TopBar } from "@/components/layout/topbar";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import {
  ACCEPTED_TYPES,
  byPose,
  defaultPair,
  type Photo,
  type PhotoPose,
  photoKeys,
  photosApi,
  POSE_LABELS,
  POSES,
  spanLabel,
  weightDeltaLabel,
} from "@/features/progress/photos-api";

/**
 * A private photo timeline, and a slider to compare any two.
 *
 * The comparison is the whole point. A month of photos in a grid is a grid; the same two
 * photos with a divider you can drag between them is the only view in the product that
 * shows a change slowly enough to have been invisible day to day.
 *
 * Nothing on this page is ever used as decoration anywhere else — not on the dashboard,
 * not in a share card, not as a background. These are the most sensitive images the
 * product holds and they appear here, on request, and nowhere else.
 */
export default function ProgressPhotosPage() {
  const queryClient = useQueryClient();
  const [pose, setPose] = useState<PhotoPose>("front");

  const photos = useQuery({
    queryKey: photoKeys.list(pose),
    queryFn: () => photosApi.list(pose),
  });

  const items = useMemo(() => photos.data ?? [], [photos.data]);
  const ready = useMemo(() => items.filter((photo) => photo.isReady), [items]);

  return (
    <>
      <TopBar title="Progress photos" />

      <PageShell>
        <p className="mb-6 max-w-2xl text-body text-text-secondary">
          Only you can see these. Location data is stripped from every photo before it is
          stored, and the links this page uses expire within minutes.
        </p>

        <div className="mb-6 flex flex-wrap items-center gap-3">
          <div
            role="tablist"
            aria-label="Pose"
            className="flex gap-1 rounded-lg bg-surface-well p-1"
          >
            {POSES.map((option) => (
              <button
                key={option}
                role="tab"
                aria-selected={pose === option}
                onClick={() => setPose(option)}
                className={`rounded-md px-3 py-1.5 text-caption transition ${
                  pose === option
                    ? "bg-accent text-accent-ink"
                    : "text-text-secondary hover:text-text"
                }`}
              >
                {POSE_LABELS[option]}
              </button>
            ))}
          </div>

          <UploadButton pose={pose} />
        </div>

        {photos.isLoading ? (
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
            {Array.from({ length: 4 }).map((_, index) => (
              <Skeleton key={index} className="aspect-[3/4] rounded-lg" />
            ))}
          </div>
        ) : items.length === 0 ? (
          <EmptyState
            icon={<Camera className="size-6" />}
            title={`No ${POSE_LABELS[pose].toLowerCase()} photos yet`}
            description="Take one in the same spot, same light, same time of day. Consistency is what makes the comparison mean anything."
          />
        ) : (
          <>
            {ready.length >= 2 && <Comparison photos={ready} />}
            <Timeline
              photos={items}
              onDeleted={() => queryClient.invalidateQueries({ queryKey: photoKeys.all })}
            />
          </>
        )}
      </PageShell>
    </>
  );
}

function UploadButton({ pose }: { pose: PhotoPose }) {
  const queryClient = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<string | null>(null);

  const upload = useMutation({
    mutationFn: (file: File) => photosApi.upload(file, { pose }),
    onSuccess: () => {
      setError(null);
      void queryClient.invalidateQueries({ queryKey: photoKeys.all });
    },
    onError: (cause: Error) => setError(cause.message),
  });

  return (
    <div className="flex items-center gap-3">
      <input
        ref={input}
        type="file"
        accept={ACCEPTED_TYPES}
        className="sr-only"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) upload.mutate(file);
          // Cleared so choosing the same file twice still fires a change event.
          event.target.value = "";
        }}
      />
      <Button onClick={() => input.current?.click()} disabled={upload.isPending}>
        {upload.isPending ? (
          <>
            <Loader2 className="mr-2 size-4 animate-spin" aria-hidden />
            Uploading
          </>
        ) : (
          <>
            <Camera className="mr-2 size-4" aria-hidden />
            Add {POSE_LABELS[pose].toLowerCase()} photo
          </>
        )}
      </Button>
      {error && (
        <p role="alert" className="text-caption text-critical">
          {error}
        </p>
      )}
    </div>
  );
}

/**
 * Two photos with a draggable divider.
 *
 * A range input rather than a mouse handler, which is what makes it work with a keyboard
 * and a screen reader for free — the arrow keys move the divider, and the value is
 * announced as a percentage. A bespoke drag handler is the version of this control that
 * only works for people who can already see it.
 */
function Comparison({ photos }: { photos: Photo[] }) {
  const pair = defaultPair(photos);
  const [firstId, setFirstId] = useState(() => pair?.[0].id ?? "");
  const [secondId, setSecondId] = useState(() => pair?.[1].id ?? "");
  const [position, setPosition] = useState(50);

  const comparison = useQuery({
    queryKey: photoKeys.comparison(firstId, secondId),
    queryFn: () => photosApi.compare(firstId, secondId),
    enabled: Boolean(firstId && secondId && firstId !== secondId),
  });

  if (!pair) return null;

  const data = comparison.data;
  const delta = weightDeltaLabel(data?.weightDeltaKg ?? null);

  return (
    <section className="mb-8 rounded-lg border border-border bg-surface p-4 lg:p-6">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-h3 text-text">Compare</h2>
          {data && (
            <p className="text-caption text-text-muted">
              {spanLabel(data.daysBetween)} apart
              {delta && <> · {delta}</>}
            </p>
          )}
        </div>

        <div className="flex flex-wrap gap-3">
          <PhotoPicker label="Before" photos={photos} value={firstId} onChange={setFirstId} />
          <PhotoPicker label="After" photos={photos} value={secondId} onChange={setSecondId} />
        </div>
      </div>

      {data && !data.posesMatch && (
        <p className="mb-3 flex items-center gap-2 text-caption text-warning">
          <TriangleAlert className="size-4" aria-hidden />
          Those are different poses, so the comparison will not tell you much.
        </p>
      )}

      {comparison.isLoading || !data ? (
        <Skeleton className="aspect-[3/4] w-full max-w-md rounded-lg" />
      ) : (
        <>
          <div className="relative mx-auto aspect-[3/4] w-full max-w-md overflow-hidden rounded-lg bg-surface-well">
            {/* The later photo underneath, the earlier one clipped over it. Clipping
                rather than opacity, so the divider is a hard edge and the two are never
                blended into an image that is neither. */}
            {data.later.url && (
              // A signed, short-lived URL on a third-party origin. next/image would
              // proxy it through our server and cache the result, which is the one
              // thing that must not happen to a progress photo.
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={data.later.url}
                alt={`${POSE_LABELS[data.later.pose as PhotoPose] ?? data.later.pose} photo from ${data.later.localDate}`}
                className="absolute inset-0 size-full object-cover"
              />
            )}
            {data.earlier.url && (
              <div
                className="absolute inset-0 overflow-hidden"
                style={{ clipPath: `inset(0 ${100 - position}% 0 0)` }}
              >
                {/* eslint-disable-next-line @next/next/no-img-element -- as above */}
                <img
                  src={data.earlier.url}
                  alt={`${POSE_LABELS[data.earlier.pose as PhotoPose] ?? data.earlier.pose} photo from ${data.earlier.localDate}`}
                  className="size-full object-cover"
                />
              </div>
            )}

            <div
              aria-hidden
              className="pointer-events-none absolute inset-y-0 w-0.5 bg-accent"
              style={{ left: `${position}%` }}
            />

            <span className="absolute bottom-2 left-2 rounded bg-black/60 px-2 py-1 text-caption text-white">
              {data.earlier.localDate}
            </span>
            <span className="absolute bottom-2 right-2 rounded bg-black/60 px-2 py-1 text-caption text-white">
              {data.later.localDate}
            </span>
          </div>

          <label className="mx-auto mt-3 block w-full max-w-md">
            <span className="sr-only">Comparison position</span>
            <input
              type="range"
              min={0}
              max={100}
              value={position}
              onChange={(event) => setPosition(Number(event.target.value))}
              aria-label="Reveal the earlier photo"
              aria-valuetext={`${position}% earlier photo`}
              className="w-full accent-accent"
            />
          </label>
        </>
      )}
    </section>
  );
}

function PhotoPicker({
  label,
  photos,
  value,
  onChange,
}: {
  label: string;
  photos: Photo[];
  value: string;
  onChange: (id: string) => void;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-caption text-text-muted">{label}</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-9 rounded-md border border-border bg-surface px-2 text-caption text-text"
      >
        {photos.map((photo) => (
          <option key={photo.id} value={photo.id}>
            {photo.localDate}
          </option>
        ))}
      </select>
    </label>
  );
}

function Timeline({ photos, onDeleted }: { photos: Photo[]; onDeleted: () => void }) {
  const grouped = byPose(photos);

  return (
    <section>
      <h2 className="mb-3 text-h3 text-text">Timeline</h2>
      {[...grouped.entries()].map(([pose, group]) => (
        <div key={pose} className="mb-6">
          <h3 className="mb-2 text-caption text-text-muted">
            {POSE_LABELS[pose as PhotoPose] ?? pose}
          </h3>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
            {group.map((photo) => (
              <PhotoTile key={photo.id} photo={photo} onDeleted={onDeleted} />
            ))}
          </div>
        </div>
      ))}
    </section>
  );
}

function PhotoTile({ photo, onDeleted }: { photo: Photo; onDeleted: () => void }) {
  const remove = useMutation({
    mutationFn: () => photosApi.remove(photo.id),
    onSuccess: onDeleted,
  });

  return (
    <figure className="group relative overflow-hidden rounded-lg bg-surface-well">
      <div className="aspect-[3/4]">
        {photo.thumbnailUrl ? (
          // eslint-disable-next-line @next/next/no-img-element -- signed, short-lived URL
          <img
            src={photo.thumbnailUrl}
            alt={`Photo from ${photo.localDate}`}
            loading="lazy"
            className="size-full object-cover"
          />
        ) : (
          // Not a broken image and not a spinner that never resolves: the photo has a
          // state, and it is shown.
          <div className="flex size-full flex-col items-center justify-center gap-2 p-3 text-center">
            {photo.processingStatus === "failed" ? (
              <>
                <TriangleAlert className="size-5 text-critical" aria-hidden />
                <span className="text-caption text-text-muted">
                  This one could not be processed
                </span>
              </>
            ) : (
              <>
                <Loader2 className="size-5 animate-spin text-text-muted" aria-hidden />
                <span className="text-caption text-text-muted">Processing</span>
              </>
            )}
          </div>
        )}
      </div>

      <figcaption className="flex items-center justify-between px-2 py-1.5">
        <span className="text-caption tabular-nums text-text-secondary">{photo.localDate}</span>
        {photo.weightAtCaptureKg && (
          <span className="text-caption tabular-nums text-text-muted">
            {Number(photo.weightAtCaptureKg).toFixed(1)} kg
          </span>
        )}
      </figcaption>

      <Button
        variant="ghost"
        size="icon"
        aria-label={`Delete the photo from ${photo.localDate}`}
        disabled={remove.isPending}
        onClick={() => remove.mutate()}
        className="absolute right-1 top-1 opacity-0 transition group-hover:opacity-100 focus-visible:opacity-100"
      >
        <Trash2 className="size-4" aria-hidden />
      </Button>
    </figure>
  );
}
