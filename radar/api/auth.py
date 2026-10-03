"""Passwords and usernames for the accounts people make themselves.

scrypt from the standard library (no new dependency). One hash takes tens of milliseconds and ~16 MB, so it
runs in a worker thread behind a small semaphore: the API and the scheduler share one event loop, and a burst of
logins must not pause polling or use up a 1 GB box. Only the hashing runs in the thread; every database call
stays on the loop."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import re
import secrets

N, R, P = 2 ** 14, 8, 1
MIN_PASSWORD, MAX_PASSWORD = 10, 128  # long is good, composition rules are not; the cap bounds the hashing work
USERNAME = re.compile(r"^[a-z0-9_]{3,24}$")
RESERVED = frozenset({"guest", "admin", "root", "system", "radar", "api", "support", "null", "undefined"})
_slots = asyncio.Semaphore(2)


def _scrypt(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=N, r=R, p=P, maxmem=64 * 1024 * 1024, dklen=32)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    return f"scrypt${N}${R}${P}${base64.b64encode(salt).decode()}${base64.b64encode(_scrypt(password, salt)).decode()}"


def check_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, digest = stored.split("$")
        if (int(n), int(r), int(p)) != (N, R, P):
            return False
        return hmac.compare_digest(_scrypt(password, base64.b64decode(salt)), base64.b64decode(digest))
    except (ValueError, TypeError):
        return False


async def hash_password_async(password: str) -> str:
    async with _slots:
        return await asyncio.to_thread(hash_password, password)


async def check_password_async(password: str, stored: str) -> bool:
    async with _slots:
        return await asyncio.to_thread(check_password, password, stored)


# A real hash of a throwaway password: an unknown username is checked against it, so "no such user" and
# "wrong password" take the same time and return the same answer.
DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def normalize_username(raw: str) -> str:
    return (raw or "").strip().lower()


def username_problem(username: str) -> str | None:
    if not USERNAME.match(username):
        return "A username is 3 to 24 letters, numbers or underscores."
    if username in RESERVED:
        return "That username is taken."
    return None


def password_problem(password: str) -> str | None:
    if len(password) < MIN_PASSWORD:
        return f"A password needs at least {MIN_PASSWORD} characters."
    if len(password) > MAX_PASSWORD:
        return f"A password can be at most {MAX_PASSWORD} characters."
    return None


def new_session_token() -> tuple[str, str]:
    """(token to hand the browser, hash to store)."""
    token = secrets.token_urlsafe(32)
    return token, hashlib.sha256(token.encode()).hexdigest()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
