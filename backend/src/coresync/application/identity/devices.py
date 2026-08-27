"""Registering the installations that can receive a push.

The whole point of this module is that a push token belongs to an *installation*, not to
an account. That distinction drives every rule below:

- The same phone signing in as somebody else must move the token, not duplicate it.
  Otherwise the previous account keeps receiving notifications on a device that is no
  longer theirs, which is a privacy failure rather than a bug.
- One account may hold several devices — a phone and a tablet — and each gets its own row.
- A token the provider rejects is deactivated rather than deleted, because the device
  still exists and will present a new token the next time the app runs.

Registration is therefore an upsert keyed on the token, not a create.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from coresync.application.common.unit_of_work import UnitOfWork
from coresync.core.clock import Clock
from coresync.core.errors import NotFoundError, ValidationError
from coresync.core.logging import get_logger
from coresync.domain.identity.entities import PLATFORMS, UserDevice

logger = get_logger(__name__)

#: Expo tokens look like `ExponentPushToken[xxxxxxxxxxxxxxxxxxxxxx]` or, on the newer
#: format, `ExpoPushToken[...]`. Validated loosely: the provider is the real authority on
#: what it will accept, and a client that has been updated ahead of us should not be
#: rejected here for a format we have not heard of yet.
MAX_TOKEN_LENGTH = 512


@dataclass(frozen=True, slots=True)
class RegisterDeviceCommand:
    user_id: UUID
    platform: str
    push_token: str
    device_name: str | None = None


@dataclass(frozen=True, slots=True)
class DeviceDTO:
    id: UUID
    platform: str
    device_name: str | None
    is_active: bool
    has_push_token: bool


def _dto(device: UserDevice) -> DeviceDTO:
    return DeviceDTO(
        id=device.id,
        platform=device.platform,
        device_name=device.device_name,
        is_active=device.is_active,
        # The token itself is never returned. It is a delivery credential for this
        # installation, and the client that registered it already has it.
        has_push_token=bool(device.push_token),
    )


class RegisterDeviceUseCase:
    """Idempotent on the token.

    Calling this repeatedly with the same token — which the mobile app does on every
    launch — updates one row rather than accumulating a new device per launch.
    """

    def __init__(self, *, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def execute(self, cmd: RegisterDeviceCommand) -> DeviceDTO:
        token = cmd.push_token.strip()
        if not token:
            raise ValidationError("A push token is required.")
        if len(token) > MAX_TOKEN_LENGTH:
            raise ValidationError("That push token is not a valid length.")
        if cmd.platform not in PLATFORMS:
            raise ValidationError(f"Unknown platform '{cmd.platform}'.")

        now = self._clock.now()
        async with self._uow:
            existing = await self._uow.devices.get_by_push_token(token)

            if existing is not None:
                if existing.user_id != cmd.user_id:
                    # The phone changed hands, or the account was switched in the app.
                    # The token must follow the installation: leaving it on the previous
                    # user means their notifications arrive on somebody else's screen.
                    existing.deactivate()
                    await self._uow.devices.update(existing)
                    logger.info(
                        "push_token_reassigned",
                        from_user=str(existing.user_id),
                        to_user=str(cmd.user_id),
                    )
                else:
                    existing.platform = cmd.platform
                    existing.device_name = cmd.device_name or existing.device_name
                    existing.register_token(token, now=now)
                    await self._uow.devices.update(existing)
                    await self._uow.commit()
                    return _dto(existing)

            device = UserDevice.create(
                user_id=cmd.user_id,
                platform=cmd.platform,
                device_name=cmd.device_name,
                now=now,
                push_token=token,
            )
            await self._uow.devices.add(device)
            await self._uow.commit()

        logger.info("device_registered", user_id=str(cmd.user_id), platform=cmd.platform)
        return _dto(device)


class ListDevicesUseCase:
    def __init__(self, *, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self, user_id: UUID) -> list[DeviceDTO]:
        async with self._uow:
            # Scoped to the caller by the repository. There is no path here that can
            # return somebody else's device.
            devices = await self._uow.devices.list_for_user(user_id)
        return [_dto(device) for device in devices]


class UnregisterDeviceUseCase:
    """Remove a device outright.

    Deletion rather than deactivation, because this is a deliberate act by the person who
    owns the account — signing out, or removing an old phone from the list. Keeping a row
    they asked to remove would be a small dishonesty in a settings screen.
    """

    def __init__(self, *, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self, user_id: UUID, device_id: UUID) -> None:
        async with self._uow:
            removed = await self._uow.devices.remove(device_id, user_id)
            if not removed:
                # Indistinguishable from "belongs to somebody else", deliberately: a
                # different answer would confirm the existence of another user's device.
                raise NotFoundError("device", device_id)
            await self._uow.commit()

        logger.info("device_unregistered", user_id=str(user_id))


class UnregisterTokenUseCase:
    """Remove whichever device holds this token, if it is the caller's.

    Sign-out is the reason this exists. The app knows its token but not its device id, and
    making it fetch the list first would be a round trip during a flow where the access
    token is about to be discarded anyway.
    """

    def __init__(self, *, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self, user_id: UUID, token: str) -> None:
        async with self._uow:
            device = await self._uow.devices.get_by_push_token(token.strip())
            # Silent when it is not the caller's: sign-out must not fail, and telling the
            # caller that a token belongs to somebody else is not information they need.
            if device is not None and device.user_id == user_id:
                await self._uow.devices.remove(device.id, user_id)
            await self._uow.commit()
