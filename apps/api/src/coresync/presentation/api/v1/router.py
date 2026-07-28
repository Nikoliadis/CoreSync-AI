"""v1 router assembly.

Routers are registered here rather than in ``main`` so the API surface is one readable
list, and so tests can mount a subset.
"""

from __future__ import annotations

from fastapi import APIRouter

from coresync.presentation.api.v1 import auth, system, users

api_router = APIRouter(prefix="/v1")

api_router.include_router(system.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)

# Phase 2+ mount here: exercises, routines, sessions, nutrition, progress, ai, social.
