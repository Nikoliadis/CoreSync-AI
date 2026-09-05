import { api } from "@/lib/api/client";

/**
 * Progress photos.
 *
 * The upload is three steps, and the split is the security design rather than an
 * artefact of REST: the API issues a credential scoped to a single object, the phone
 * posts the file straight to private storage, and a second call brings the photo through
 * the metadata strip. The bytes never touch our server.
 *
 * A photo is not readable until `isReady`. That is not a loading state — it means the
 * EXIF has not been proven gone, and on a progress photo that EXIF is the GPS
 * coordinates of somebody's home. The screen shows a pending tile rather than reaching
 * for a URL that is null.
 */

export type PhotoPose = "front" | "side" | "back" | "custom";

export const POSES: readonly PhotoPose[] = ["front", "side", "back"] as const;

export type Photo = {
  id: string;
  localDate: string;
  pose: string;
  processingStatus: "pending" | "processing" | "ready" | "failed";
  isReady: boolean;
  url: string | null;
  thumbnailUrl: string | null;
  urlExpiresAt: string | null;
  width: number | null;
  height: number | null;
  weightAtCaptureKg: string | null;
  note: string | null;
};

export type PhotoComparison = {
  earlier: Photo;
  later: Photo;
  daysBetween: number;
  weightDeltaKg: string | null;
  posesMatch: boolean;
};

type UploadIntent = {
  photoId: string;
  uploadUrl: string;
  /** Opaque policy fields. Posted back verbatim, then the file last. */
  fields: Record<string, string>;
  expiresAt: string;
  maxBytes: number;
  requiredContentType: string | null;
};

export const photoKeys = {
  all: ["progress", "photos"] as const,
  list: (pose: string) => [...photoKeys.all, "list", pose] as const,
  comparison: (first: string, second: string) =>
    [...photoKeys.all, "compare", first, second] as const,
};

export const photosApi = {
  list: (pose: string) => api.get<Photo[]>("/v1/progress/photos", { query: { pose } }),

  compare: (first: string, second: string) =>
    api.get<PhotoComparison>("/v1/progress/photos/compare", { query: { first, second } }),

  remove: (photoId: string) => api.delete<void>(`/v1/progress/photos/${photoId}`),

  /**
   * The whole upload, as one call.
   *
   * Kept together because the steps are not independently useful: an intent with no
   * upload is a pending row nobody can see, and an upload with no completion call is
   * bytes that never become a photo. Failing halfway leaves exactly that — recoverable,
   * and invisible — rather than a broken tile in the grid.
   */
  upload: async (
    file: { uri: string; mimeType: string; fileSize?: number },
    options: { pose: PhotoPose; localDate?: string },
  ): Promise<Photo> => {
    const intent = await api.post<UploadIntent>("/v1/progress/photos/upload-intent", {
      contentType: file.mimeType,
      pose: options.pose,
      localDate: options.localDate,
    });

    if (file.fileSize && file.fileSize > intent.maxBytes) {
      // Checked here only so the user gets a sentence instead of a failed request. The
      // limit that matters is the one in the signed policy, which storage enforces.
      throw new Error(`That photo is larger than ${Math.round(intent.maxBytes / 1024 / 1024)} MB.`);
    }

    // A form POST straight to storage. Deliberately a bare `fetch` rather than the API
    // client: this is not our origin, and attaching an access token to a third-party URL
    // is the mistake this comment exists to prevent.
    //
    // The fields go first and the file last — an S3 POST policy ignores anything after
    // the file part, so a field placed after it is silently dropped.
    //
    // React Native's FormData takes the local `file://` URI directly and streams it, so
    // a 15 MB photo never sits in the JS heap as a blob.
    const form = new FormData();
    for (const [name, value] of Object.entries(intent.fields)) form.append(name, value);
    form.append("file", {
      uri: file.uri,
      name: "photo.jpg",
      type: intent.requiredContentType ?? file.mimeType,
    } as unknown as Blob);

    // No `Content-Type` header by hand: the runtime has to write the multipart boundary.
    const stored = await fetch(intent.uploadUrl, { method: "POST", body: form });
    if (!stored.ok) {
      throw new Error("The upload did not finish. Check your connection and try again.");
    }

    return api.post<Photo>(`/v1/progress/photos/${intent.photoId}/complete`, {});
  },
};

/**
 * The two photos worth opening a comparison with: the oldest and the newest.
 *
 * Two photos a week apart show noise. The ends of the range are the only pair that shows
 * anything, which is why this is the default rather than "the last two".
 */
export function defaultPair(photos: readonly Photo[]): [Photo, Photo] | null {
  const ready = photos.filter((photo) => photo.isReady);
  if (ready.length < 2) return null;

  const sorted = [...ready].sort((a, b) => a.localDate.localeCompare(b.localDate));
  const oldest = sorted[0];
  const newest = sorted[sorted.length - 1];
  // `noUncheckedIndexedAccess` types an index into a non-empty array as possibly
  // undefined, and the length check above is not something the compiler can carry here.
  if (!oldest || !newest) return null;
  return [oldest, newest];
}

/** `3 months`, `18 days` — the gap, in the largest unit that is not a lie. */
export function spanLabel(days: number): string {
  if (days < 14) return `${days} ${days === 1 ? "day" : "days"}`;
  if (days < 60) {
    const weeks = Math.round(days / 7);
    return `${weeks} ${weeks === 1 ? "week" : "weeks"}`;
  }
  if (days < 730) {
    const months = Math.round(days / 30.44);
    return `${months} ${months === 1 ? "month" : "months"}`;
  }
  return `${(days / 365.25).toFixed(1)} years`;
}

/**
 * `-2.5 kg`, `+1.2 kg`, or null when either side has no weight recorded.
 *
 * Signed explicitly: "2.5 kg" beside a photo comparison is ambiguous in the one
 * direction the person reading it cares about.
 */
export function weightDeltaLabel(delta: string | null): string | null {
  if (delta === null || delta === "") return null;
  const value = Number(delta);
  if (!Number.isFinite(value)) return null;
  const rounded = Math.round(value * 10) / 10;
  if (rounded === 0) return "no change";
  return `${rounded > 0 ? "+" : ""}${rounded.toFixed(1)} kg`;
}
