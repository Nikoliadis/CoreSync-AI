import { api } from "@/lib/api/client";

/**
 * Profile, settings, and leaving.
 *
 * Account deletion lives here rather than being deferred to a support email because both
 * app stores require it to be reachable in-app, and because a product that is easy to
 * join and hard to leave has decided something about its users.
 *
 * Settings is a PUT of a partial body: fields omitted are unchanged, so a single toggle
 * sends only itself. Sending the whole object back would overwrite anything changed on
 * another device between read and write.
 */

export type Profile = {
  userId: string;
  displayName: string;
  dateOfBirth: string | null;
  gender: string | null;
  heightCm: string | null;
  activityLevel: string;
  experienceLevel: string;
  avatarUrl: string | null;
  bio: string | null;
};

/**
 * Left as plain strings rather than unions.
 *
 * The server owns these vocabularies and may add a value before this build ships; a
 * narrow union would make an unrecognised one a type error at the boundary rather than
 * something the UI simply does not highlight.
 */
export type Settings = {
  unitSystem: string;
  theme: string;
  language: string;
  profileVisibility: string;
  aiTrainingOptIn: boolean;
  marketingEmailOptIn: boolean;
};

export type Me = {
  user: { id: string; email: string; displayName?: string };
  profile: Profile | null;
  settings: Settings;
  entitlements: string[];
};

export const ACTIVITY_LEVELS = [
  "sedentary",
  "light",
  "moderate",
  "active",
  "very_active",
] as const;

export const ACTIVITY_LABELS: Record<string, string> = {
  sedentary: "Sedentary",
  light: "Lightly active",
  moderate: "Moderately active",
  active: "Active",
  very_active: "Very active",
};

export const EXPERIENCE_LEVELS = ["beginner", "intermediate", "advanced"] as const;

export const EXPERIENCE_LABELS: Record<string, string> = {
  beginner: "Beginner",
  intermediate: "Intermediate",
  advanced: "Advanced",
};

export const settingsKeys = {
  all: ["settings"] as const,
  me: () => [...settingsKeys.all, "me"] as const,
};

export const settingsApi = {
  me: () => api.get<Me>("/v1/users/me"),

  updateProfile: (changes: {
    displayName?: string;
    dateOfBirth?: string | null;
    gender?: string | null;
    heightCm?: number | null;
    activityLevel?: string;
    experienceLevel?: string;
    bio?: string | null;
  }) => api.patch<Profile>("/v1/users/me", changes),

  updateSettings: (changes: Partial<Settings>) =>
    api.put<Settings>("/v1/users/me/settings", changes),

  /**
   * Schedule deletion.
   *
   * Soft-deletes immediately and signs out every session; permanent erasure follows a
   * 30-day grace period during which signing in cancels it. The grace period is the part
   * the UI must state, because "deleted" that can be undone and "deleted" that cannot are
   * different promises.
   */
  deleteAccount: () =>
    api.delete<{ scheduledFor: string; message: string }>("/v1/users/me"),
};

/** Centimetres to feet and inches, for the imperial display. */
export function toFeetInches(cm: number): { feet: number; inches: number } {
  const totalInches = cm / 2.54;
  const feet = Math.floor(totalInches / 12);
  // Rounded after the split, so 71.6" reads as 6'0" rather than 5'12".
  const inches = Math.round(totalInches - feet * 12);
  return inches === 12 ? { feet: feet + 1, inches: 0 } : { feet, inches };
}

/** `178 cm` or `5'10"`, whichever the user asked for. */
export function heightLabel(heightCm: string | null, unitSystem: string): string {
  const value = Number(heightCm ?? NaN);
  if (!Number.isFinite(value) || value <= 0) return "—";

  if (unitSystem === "imperial") {
    const { feet, inches } = toFeetInches(value);
    return `${feet}'${inches}"`;
  }
  return `${Math.round(value)} cm`;
}

/** Years, from a date of birth. Null when unknown or nonsensical. */
export function ageFrom(dateOfBirth: string | null, today = new Date()): number | null {
  if (!dateOfBirth) return null;
  const born = new Date(dateOfBirth);
  if (Number.isNaN(born.getTime())) return null;

  let age = today.getFullYear() - born.getFullYear();
  const monthDelta = today.getMonth() - born.getMonth();
  // Not yet had this year's birthday.
  if (monthDelta < 0 || (monthDelta === 0 && today.getDate() < born.getDate())) age -= 1;

  return age >= 0 && age < 130 ? age : null;
}
