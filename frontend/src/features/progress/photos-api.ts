import { api } from "@/lib/api/client";

/**
 * Progress photos.
 *
 * The upload is three steps rather than one, and the split is the security design: the
 * API issues a credential scoped to a single object, the browser posts the file straight
 * to private storage, and a second call brings the photo through the metadata strip. The
 * bytes never touch our server, which is also why the upload below uses `fetch` directly
 * rather than the API client — it is not a call to our API at all, and attaching an
 * access token to a third-party URL is exactly what should never happen.
 *
 * A photo is not readable until `isReady`. That is not a loading state: it means the
 * EXIF has not been proven gone, and the coordinates in it are the inside of somebody's
 * home. The UI shows a pending tile rather than reaching for a URL that is null.
 */

export type PhotoPose = "front" | "side" | "back" | "custom";

export const POSES: readonly PhotoPose[] = ["front", "side", "back"] as const;

export const POSE_LABELS: Record<PhotoPose, string> = {
  front: "Front",
  side: "Side",
  back: "Back",
  custom: "Other",
};

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
  list: (pose?: string) => [...photoKeys.all, "list", pose ?? "all"] as const,
  comparison: (first: string, second: string) =>
    [...photoKeys.all, "compare", first, second] as const,
};

export const photosApi = {
  list: (pose?: string) =>
    api.get<Photo[]>("/v1/progress/photos", { query: pose ? { pose } : undefined }),

  compare: (first: string, second: string) =>
    api.get<PhotoComparison>("/v1/progress/photos/compare", { query: { first, second } }),

  remove: (photoId: string) => api.delete<void>(`/v1/progress/photos/${photoId}`),

  /**
   * The whole upload, as one call for the caller.
   *
   * Kept together because the three steps are not independently useful: an intent
   * without an upload is a pending row nobody can see, and an upload without the
   * completion call is bytes that never become a photo. Failing halfway leaves exactly
   * that — recoverable, and invisible — rather than a broken tile.
   */
  upload: async (
    file: File,
    options: { pose: PhotoPose; localDate?: string; note?: string },
  ): Promise<Photo> => {
    const intent = await api.post<UploadIntent>("/v1/progress/photos/upload-intent", {
      contentType: file.type,
      pose: options.pose,
      localDate: options.localDate,
      note: options.note,
    });

    if (file.size > intent.maxBytes) {
      // Checked here only so the user gets a sentence instead of a failed request. The
      // limit that matters is the one in the signed policy, which storage enforces.
      throw new Error(`That image is larger than ${Math.round(intent.maxBytes / 1024 / 1024)} MB.`);
    }

    // A browser form POST, straight to storage. No credentials, no cookies, and
    // deliberately not through the API client — the signature already authorises
    // exactly this one write, and attaching our access token to a third-party origin is
    // the mistake this comment exists to prevent.
    //
    // The fields go first and the file last: an S3 POST policy ignores anything after
    // the file part, so a field placed after it is silently dropped and the request
    // fails the policy check.
    const form = new FormData();
    for (const [name, value] of Object.entries(intent.fields)) form.append(name, value);
    form.append("file", file);

    // No `Content-Type` header set by hand. The browser has to write the multipart
    // boundary into it, and overriding it produces a body storage cannot parse.
    const stored = await fetch(intent.uploadUrl, { method: "POST", body: form });
    if (!stored.ok) {
      throw new Error("The upload did not finish. Check your connection and try again.");
    }

    return api.post<Photo>(`/v1/progress/photos/${intent.photoId}/complete`, {});
  },
};

/** `image/jpeg` and friends, as the server accepts them. */
export const ACCEPTED_TYPES = "image/jpeg,image/png,image/heic,image/webp";

/**
 * Group a timeline into pose → photos, newest first within each.
 *
 * The comparison only makes sense within a pose — a front shot against a back shot tells
 * you nothing — so the picker is built per pose rather than over the whole list.
 */
export function byPose(photos: readonly Photo[]): Map<string, Photo[]> {
  const map = new Map<string, Photo[]>();
  for (const photo of photos) {
    const existing = map.get(photo.pose);
    if (existing) existing.push(photo);
    else map.set(photo.pose, [photo]);
  }
  return map;
}

/**
 * The two photos a comparison should open with: the oldest and the newest of a pose.
 *
 * That pair is the one worth seeing. Two photos a week apart show noise; the ends of the
 * range are the only pair that shows anything.
 */
export function defaultPair(photos: readonly Photo[]): [Photo, Photo] | null {
  const ready = photos.filter((photo) => photo.isReady);
  if (ready.length < 2) return null;

  const sorted = [...ready].sort((a, b) => a.localDate.localeCompare(b.localDate));
  return [sorted[0], sorted[sorted.length - 1]];
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
  const years = (days / 365.25).toFixed(1);
  return `${years} years`;
}

/**
 * `-2.5 kg`, `+1.2 kg`, or null when either side has no weight recorded.
 *
 * Signed explicitly, because "2.5 kg" next to a photo comparison is ambiguous in the one
 * direction that matters to the person reading it.
 */
export function weightDeltaLabel(delta: string | null): string | null {
  if (delta === null || delta === "") return null;
  const value = Number(delta);
  if (!Number.isFinite(value)) return null;
  const rounded = Math.round(value * 10) / 10;
  if (rounded === 0) return "no change";
  return `${rounded > 0 ? "+" : ""}${rounded.toFixed(1)} kg`;
}
