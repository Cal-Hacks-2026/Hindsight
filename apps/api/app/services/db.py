"""Supabase via PostgREST (no extra dependency), with the service-role key."""

import os

import httpx

from app.config import supabase_rest_url


class StoreError(Exception):
    status = 502


class StoreNotConfigured(StoreError):
    status = 503


def client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    rest_url, key = supabase_rest_url(), os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not rest_url or not key:
        raise StoreNotConfigured("Storage is not configured (SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY)")
    return httpx.Client(base_url=rest_url, headers={"apikey": key, "Authorization": f"Bearer {key}"},
                        timeout=15.0, transport=transport)
