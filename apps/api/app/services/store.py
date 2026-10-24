"""In-memory stand-in for Supabase during Phase 0. Lost on restart."""

from app.models import Course, Profile

profiles: dict[str, Profile] = {}
courses: dict[str, list[Course]] = {}
