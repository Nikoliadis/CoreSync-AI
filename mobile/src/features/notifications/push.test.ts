import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Push registration and the tap that routes.
 *
 * The permission logic carries the most weight. iOS grants an app exactly one chance to
 * show the system prompt: once it is spent, the only way back is the Settings app, which
 * almost nobody visits. So "denied but we can ask again" and "denied for good" must stay
 * distinct — conflating them either wastes the one prompt or offers a button that can
 * never do anything.
 */

const notifications = vi.hoisted(() => ({
  PermissionStatus: { GRANTED: "granted", DENIED: "denied", UNDETERMINED: "undetermined" },
  AndroidImportance: { DEFAULT: 3 },
  AndroidNotificationVisibility: { PRIVATE: 0 },
  setNotificationHandler: vi.fn(),
  setNotificationChannelAsync: vi.fn(),
  getPermissionsAsync: vi.fn(),
  requestPermissionsAsync: vi.fn(),
  getExpoPushTokenAsync: vi.fn(),
}));

const device = vi.hoisted(() => ({ isDevice: true, deviceName: "Test Phone" }));
const client = vi.hoisted(() => ({ api: { post: vi.fn() } }));

vi.mock("expo-notifications", () => notifications);
vi.mock("expo-device", () => device);
vi.mock("@/lib/api/client", () => client);
vi.mock("react-native", () => ({ Platform: { OS: "ios" } }));

const {
  permissionState,
  requestAndRegister,
  refreshRegistration,
  unregisterCurrentDevice,
  routeFromNotification,
  categoryFromNotification,
} = await import("./push");

function response(data: unknown) {
  return {
    notification: { request: { content: { data } } },
  } as unknown as import("expo-notifications").NotificationResponse;
}

beforeEach(() => {
  vi.clearAllMocks();
  device.isDevice = true;
  notifications.getExpoPushTokenAsync.mockResolvedValue({ data: "ExponentPushToken[abc]" });
  client.api.post.mockResolvedValue(undefined);
});

describe("permission state", () => {
  it("reports granted", async () => {
    notifications.getPermissionsAsync.mockResolvedValue({
      status: "granted",
      canAskAgain: false,
    });
    expect(await permissionState()).toBe("granted");
  });

  it("reports undetermined when the prompt has never been shown", async () => {
    notifications.getPermissionsAsync.mockResolvedValue({
      status: "undetermined",
      canAskAgain: true,
    });
    expect(await permissionState()).toBe("undetermined");
  });

  it("distinguishes a final refusal from one we can still ask about", async () => {
    // Conflating these either burns the single iOS prompt or shows a button that cannot
    // work. They need different copy and different actions.
    notifications.getPermissionsAsync.mockResolvedValue({
      status: "denied",
      canAskAgain: false,
    });
    expect(await permissionState()).toBe("denied");

    notifications.getPermissionsAsync.mockResolvedValue({
      status: "denied",
      canAskAgain: true,
    });
    expect(await permissionState()).toBe("undetermined");
  });

  it("reports a simulator as unsupported rather than undetermined", async () => {
    // A simulator can never issue a token. Offering "Allow notifications" there is
    // offering a button that always fails.
    device.isDevice = false;
    expect(await permissionState()).toBe("unsupported");
  });
});

describe("requesting and registering", () => {
  it("asks, then registers the token", async () => {
    notifications.getPermissionsAsync.mockResolvedValue({
      status: "undetermined",
      canAskAgain: true,
    });
    notifications.requestPermissionsAsync.mockResolvedValue({ status: "granted" });

    expect(await requestAndRegister()).toBe("granted");

    const [path, body] = client.api.post.mock.calls[0] as [string, Record<string, unknown>];
    expect(path).toBe("/v1/users/me/devices");
    expect(body.pushToken).toBe("ExponentPushToken[abc]");
    expect(body.platform).toBe("ios");
  });

  it("does not re-prompt when permission is already granted", async () => {
    notifications.getPermissionsAsync.mockResolvedValue({
      status: "granted",
      canAskAgain: false,
    });

    await requestAndRegister();
    expect(notifications.requestPermissionsAsync).not.toHaveBeenCalled();
  });

  it("does not prompt when the one chance is already spent", async () => {
    // Calling requestPermissionsAsync here shows nothing and resolves denied, which
    // looks to the user like the button is broken.
    notifications.getPermissionsAsync.mockResolvedValue({
      status: "denied",
      canAskAgain: false,
    });

    expect(await requestAndRegister()).toBe("denied");
    expect(notifications.requestPermissionsAsync).not.toHaveBeenCalled();
  });

  it("registers nothing when the user refuses", async () => {
    notifications.getPermissionsAsync.mockResolvedValue({
      status: "undetermined",
      canAskAgain: true,
    });
    notifications.requestPermissionsAsync.mockResolvedValue({ status: "denied" });

    expect(await requestAndRegister()).toBe("denied");
    expect(client.api.post).not.toHaveBeenCalled();
  });

  it("keeps the granted state when registration fails", async () => {
    // Permission is the part the user did. A failed request is ours to retry next
    // launch, not a reason to represent their choice as a refusal.
    notifications.getPermissionsAsync.mockResolvedValue({
      status: "granted",
      canAskAgain: false,
    });
    client.api.post.mockRejectedValue(new Error("offline"));

    expect(await requestAndRegister()).toBe("granted");
  });

  it("survives the token call failing", async () => {
    notifications.getPermissionsAsync.mockResolvedValue({
      status: "granted",
      canAskAgain: false,
    });
    notifications.getExpoPushTokenAsync.mockRejectedValue(new Error("no project id"));

    expect(await requestAndRegister()).toBe("granted");
    expect(client.api.post).not.toHaveBeenCalled();
  });

  it("does nothing on a simulator", async () => {
    device.isDevice = false;
    expect(await requestAndRegister()).toBe("unsupported");
    expect(notifications.requestPermissionsAsync).not.toHaveBeenCalled();
  });
});

describe("refreshing on launch", () => {
  it("re-sends the current token so a rotated one is noticed", async () => {
    // Tokens rotate on reinstall and restore. Without this, delivery ends silently and
    // the only symptom is notifications quietly stopping.
    notifications.getPermissionsAsync.mockResolvedValue({
      status: "granted",
      canAskAgain: false,
    });

    await refreshRegistration();
    expect(client.api.post).toHaveBeenCalledOnce();
  });

  it("stays quiet when permission was never granted", async () => {
    notifications.getPermissionsAsync.mockResolvedValue({
      status: "undetermined",
      canAskAgain: true,
    });

    await refreshRegistration();
    expect(client.api.post).not.toHaveBeenCalled();
  });

  it("never throws, so a launch cannot fail on it", async () => {
    notifications.getPermissionsAsync.mockResolvedValue({
      status: "granted",
      canAskAgain: false,
    });
    client.api.post.mockRejectedValue(new Error("offline"));

    await expect(refreshRegistration()).resolves.toBeUndefined();
  });
});

describe("signing out", () => {
  it("gives up the token so the next user does not receive it", async () => {
    notifications.getPermissionsAsync.mockResolvedValue({
      status: "granted",
      canAskAgain: false,
    });

    await unregisterCurrentDevice();

    const [path, body] = client.api.post.mock.calls[0] as [string, Record<string, unknown>];
    expect(path).toBe("/v1/users/me/devices/unregister");
    expect(body.pushToken).toBe("ExponentPushToken[abc]");
  });

  it("never blocks sign-out when the network is gone", async () => {
    // Being offline is not a reason to keep somebody signed in.
    notifications.getPermissionsAsync.mockResolvedValue({
      status: "granted",
      canAskAgain: false,
    });
    client.api.post.mockRejectedValue(new Error("offline"));

    await expect(unregisterCurrentDevice()).resolves.toBeUndefined();
  });
});

describe("routing a tapped notification", () => {
  it("follows the deep link the server sent", () => {
    expect(routeFromNotification(response({ deepLink: "/workout/abc" }))).toBe("/workout/abc");
  });

  it("ignores a payload with no link", () => {
    expect(routeFromNotification(response({}))).toBeNull();
    expect(routeFromNotification(response(undefined))).toBeNull();
  });

  it("refuses an external link rather than opening it", () => {
    // A notification that lands somewhere unexpected is worse than one that only opens
    // the app, and an attacker-supplied link is worse still.
    expect(routeFromNotification(response({ deepLink: "https://example.com" }))).toBeNull();
  });

  it("ignores a link that is not a string", () => {
    expect(routeFromNotification(response({ deepLink: 42 }))).toBeNull();
  });

  it("reads a known category", () => {
    const notification = {
      request: { content: { data: { category: "pr_celebration" } } },
    } as unknown as import("expo-notifications").Notification;
    expect(categoryFromNotification(notification)).toBe("pr_celebration");
  });

  it("ignores a category this build does not know", () => {
    const notification = {
      request: { content: { data: { category: "something_new" } } },
    } as unknown as import("expo-notifications").Notification;
    expect(categoryFromNotification(notification)).toBeNull();
  });
});
