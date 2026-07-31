/**
 * Mirrors the backend's auth schemas (`presentation/schemas/auth.py`).
 *
 * Hand-written for now. docs/07 §2 calls for `openapi-typescript` output in
 * `lib/api/generated/`; that needs a running backend to export the spec, and
 * these few shapes are stable enough to type by hand until the generation step
 * is wired into CI. Field names are camelCase because the API serialises that
 * way (`to_camel` on `ApiModel`).
 */

export type AuthenticatedUser = {
  id: string;
  email: string;
  role: string;
  tier: string;
  status: string;
  emailVerified: boolean;
  timezone: string;
};

export type TokenResponse = {
  accessToken: string;
  tokenType: string;
  expiresIn: number;
  /** Absent for web clients — delivered as an httpOnly cookie instead. */
  refreshToken?: string | null;
  user: AuthenticatedUser;
  isNewUser?: boolean;
  requiresOnboarding?: boolean;
};

export type RegisterPayload = {
  email: string;
  password: string;
  displayName: string;
  timezone: string;
  acceptedTerms: boolean;
};

export type LoginPayload = {
  email: string;
  password: string;
};

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
  age: number | null;
  isOnboarded: boolean;
};

/** The app-boot payload: everything the first screen needs in one round trip. */
export type MeResponse = {
  user: AuthenticatedUser;
  profile: Profile | null;
  goal: unknown | null;
  targets: unknown | null;
  settings: Record<string, unknown>;
  entitlements: string[];
};
