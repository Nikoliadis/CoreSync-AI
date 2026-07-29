"""v1 router assembly.

Routers are registered here rather than in ``main`` so the API surface is one readable
list, and so tests can mount a subset.
"""

from __future__ import annotations

from fastapi import APIRouter

from coresync.presentation.api.v1 import auth, exercises, routines, sessions, system, users

api_router = APIRouter(prefix="/v1")

api_router.include_router(system.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(exercises.router)
api_router.include_router(routines.router)
# Sessions last: its `/workouts/sessions/{id}` route would otherwise shadow the more
# specific `/workouts/routines/...` paths that share the `/workouts` prefix.
api_router.include_router(sessions.router)

# Phase 3+ mount here: nutrition, progress, ai, social.
