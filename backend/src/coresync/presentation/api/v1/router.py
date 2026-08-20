"""v1 router assembly.

Routers are registered here rather than in ``main`` so the API surface is one readable
list, and so tests can mount a subset.
"""

from __future__ import annotations

from fastapi import APIRouter

from coresync.presentation.api.v1 import (
    achievements,
    admin,
    ai,
    auth,
    exercises,
    notifications,
    nutrition,
    progress,
    routines,
    sessions,
    system,
    users,
)

api_router = APIRouter(prefix="/v1")

api_router.include_router(system.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(exercises.router)
api_router.include_router(routines.router)
# Sessions last: its `/workouts/sessions/{id}` route would otherwise shadow the more
# specific `/workouts/routines/...` paths that share the `/workouts` prefix.
api_router.include_router(sessions.router)
api_router.include_router(progress.router)
api_router.include_router(nutrition.router)
api_router.include_router(ai.router)
api_router.include_router(notifications.router)
api_router.include_router(achievements.router)
# Admin last: an internal surface should never shadow a user-facing route.
api_router.include_router(admin.router)

# Phase 8 mounts here: social.
