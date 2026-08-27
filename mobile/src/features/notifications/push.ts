import * as Device from "expo-device";
import * as Notifications from "expo-notifications";
import { Platform } from "react-native";

import { api } from "@/lib/api/client";

import { CATEGORIES, type Category, CATEGORY_LABELS } from "./api";

/**
 * Getting a push token, and giving it to the server.
 *
 * The permission prompt is deliberately **not** requested here on launch. iOS gives an
 * app exactly one chance to ask: once someone taps "Don't Allow" the only way back is
 * through the system Settings app, which almost nobody does. So the prompt is triggered
 * from a screen that has just explained what the notifications are for, and this module
 * only ever reports the current state until something calls `requestAndRegister`.
 *
 * A token is a delivery address, not a secret — but it is still personal, so it is sent
 * to our own API and nowhere else, and never logged.
 */

export type PermissionState = "granted" | "denied" | "undetermined" | "unsupported";

/**
 * How a notification behaves while the app is open.
 *
 * Banners are shown in the foreground on purpose: the alternative is a notification that
 * arrives silently because the user happened to be looking at a different screen, which
 * reads as the feature being broken.
 */
Notifications.setNotificationHandler({
  handleNotification: () =>
    Promise.resolve({
      // SDK 54 split the old `shouldShowAlert` into these two. A banner is the
      // interruption; the list is Notification Centre, which should keep the record
      // even when the banner has been dismissed.
      shouldShowBanner: true,
      shouldShowList: true,
      shouldPlaySound: false,
      shouldSetBadge: true,
    }),
});

/**
 * Android needs its channels declared before anything arrives on them.
 *
 * One per category, matching the `channelId` the server sends, so the OS-level controls
 * mirror the in-app ones. Declaring a single channel would mean someone silencing
 * "weekly report" in Android settings also silences their PR celebrations.
 */
export async function configureAndroidChannels(): Promise<void> {
  if (Platform.OS !== "android") return;

  for (const category of CATEGORIES) {
    await Notifications.setNotificationChannelAsync(category, {
      name: CATEGORY_LABELS[category],
      importance: Notifications.AndroidImportance.DEFAULT,
      lockscreenVisibility: Notifications.AndroidNotificationVisibility.PRIVATE,
    });
  }
}

export async function permissionState(): Promise<PermissionState> {
  // A simulator cannot receive a push and cannot issue a token. Reporting that plainly
  // stops the UI offering a button that can only ever fail.
  if (!Device.isDevice) return "unsupported";

  const { status, canAskAgain } = await Notifications.getPermissionsAsync();
  if (status === Notifications.PermissionStatus.GRANTED) return "granted";
  // "Denied but we may ask again" is materially different from a final refusal: the
  // first can still be resolved in-app, the second needs the system Settings app.
  return status === Notifications.PermissionStatus.UNDETERMINED || canAskAgain
    ? "undetermined"
    : "denied";
}

/** The project id EAS stamps into the build. Required by Expo to mint a token. */
function projectId(): string | undefined {
  return (
    process.env.EXPO_PUBLIC_PROJECT_ID ??
    // Set by `expo-notifications` from app config in a built app.
    undefined
  );
}

export async function getPushToken(): Promise<string | null> {
  try {
    const id = projectId();
    const token = await Notifications.getExpoPushTokenAsync(id ? { projectId: id } : undefined);
    return token.data;
  } catch (error) {
    // A missing project id in a bare dev client is the common cause, and it is not
    // something the user can act on. Never log the token itself.
    console.warn("could not obtain a push token", error);
    return null;
  }
}

export async function registerToken(token: string): Promise<void> {
  await api.post("/v1/users/me/devices", {
    platform: Platform.OS === "ios" ? "ios" : Platform.OS === "android" ? "android" : "web",
    pushToken: token,
    deviceName: Device.deviceName ?? undefined,
  });
}

export async function unregisterToken(token: string): Promise<void> {
  await api.post("/v1/users/me/devices/unregister", { pushToken: token });
}

/**
 * Ask, then register. Call this from a screen that has already explained why.
 *
 * Returns the resulting permission state so the caller can say something useful about a
 * refusal rather than silently doing nothing.
 */
export async function requestAndRegister(): Promise<PermissionState> {
  if (!Device.isDevice) return "unsupported";

  const existing = await Notifications.getPermissionsAsync();
  let status = existing.status;

  if (status !== Notifications.PermissionStatus.GRANTED) {
    // iOS gives one chance to ask. Once it is spent, the only way back is the system
    // Settings app, so asking again here would show nothing and look broken.
    if (!existing.canAskAgain) return "denied";
    status = (await Notifications.requestPermissionsAsync()).status;
  }
  if (status !== Notifications.PermissionStatus.GRANTED) return "denied";

  await configureAndroidChannels();

  const token = await getPushToken();
  if (!token) return "granted";

  try {
    await registerToken(token);
  } catch (error) {
    // Permission was granted, which is the part the user did. A failed registration is
    // ours to retry on the next launch, not something to reverse their choice over.
    console.warn("could not register for push", error);
  }
  return "granted";
}

/**
 * Re-register on launch when permission is already granted.
 *
 * Tokens rotate — an OS update, a restore from backup, a reinstall — and the only
 * reliable way to notice is to fetch the current one and send it. Registration is
 * idempotent on the token, so doing this every launch costs one request and keeps a
 * rotated token from silently ending delivery.
 */
export async function refreshRegistration(): Promise<void> {
  if ((await permissionState()) !== "granted") return;

  const token = await getPushToken();
  if (!token) return;

  try {
    await registerToken(token);
  } catch (error) {
    console.warn("could not refresh push registration", error);
  }
}

/**
 * Give up this device's token, for sign-out.
 *
 * Best-effort and never allowed to fail the sign-out: the user asked to leave, and a
 * dead network is not a reason to keep them signed in. Worst case the server holds a
 * token that the next `DeviceNotRegistered` will clean up anyway.
 */
export async function unregisterCurrentDevice(): Promise<void> {
  try {
    if ((await permissionState()) !== "granted") return;
    const token = await getPushToken();
    if (token) await unregisterToken(token);
  } catch (error) {
    console.warn("could not unregister this device", error);
  }
}

/**
 * Where a tapped notification should go.
 *
 * Reads the `deepLink` the server put in the payload. Returns null for anything that is
 * not an app-relative path — a notification that lands somewhere unexpected is worse
 * than one that only opens the app, because the user has to work out where they are.
 */
export function routeFromNotification(
  response: Notifications.NotificationResponse,
): string | null {
  const data = response.notification.request.content.data as Record<string, unknown> | undefined;
  const link = data?.deepLink;
  return typeof link === "string" && link.startsWith("/") ? link : null;
}

/** The category a notification belongs to, when the payload carries one we know. */
export function categoryFromNotification(
  notification: Notifications.Notification,
): Category | null {
  const data = notification.request.content.data as Record<string, unknown> | undefined;
  const category = data?.category;
  return typeof category === "string" && (CATEGORIES as readonly string[]).includes(category)
    ? (category as Category)
    : null;
}
