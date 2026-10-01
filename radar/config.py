"""Settings (env) and validated YAML config (watchlist, profile)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from radar.errors import ConfigError

CONFIG_DIR = Path(os.getenv("RADAR_CONFIG_DIR", "config"))
ATS_KINDS = ("greenhouse", "lever", "ashby", "workable", "smartrecruiters", "workday")
FEED_KINDS = ("rss", "atom", "json", "html")
TIERS = ("S", "A", "B", "C")


@dataclass(frozen=True)
class Settings:
    ig_sessionid: str = ""
    apify_token: str = ""
    anthropic_api_key: str = ""
    ntfy_topic: str = ""
    google_service_account_json: str = ""
    db_path: str = "data/radar.db"
    config_dir: Path = CONFIG_DIR


def load_settings(env=None) -> Settings:
    env = os.environ if env is None else env
    return Settings(
        ig_sessionid=env.get("IG_SESSIONID", ""),
        apify_token=env.get("APIFY_TOKEN", ""),
        anthropic_api_key=env.get("ANTHROPIC_API_KEY", ""),
        ntfy_topic=env.get("NTFY_TOPIC", ""),
        google_service_account_json=env.get("GOOGLE_SERVICE_ACCOUNT_JSON", ""),
        db_path=env.get("RADAR_DB_PATH", "data/radar.db"),
        config_dir=Path(env.get("RADAR_CONFIG_DIR", "config")),
    )


@dataclass(frozen=True)
class Company:
    name: str
    ats: str
    slug: str
    tier: str = "B"


@dataclass(frozen=True)
class InstagramAccount:
    username: str
    interval_s: float = 300.0
    priority: int = 5


@dataclass(frozen=True)
class Feed:
    url: str
    kind: str = "rss"


@dataclass(frozen=True)
class Repo:
    name: str          # owner/name
    path: str = ""


@dataclass(frozen=True)
class Watchlist:
    companies: tuple[Company, ...] = ()
    instagram: tuple[InstagramAccount, ...] = ()
    feeds: tuple[Feed, ...] = ()
    repos: tuple[Repo, ...] = ()


@dataclass(frozen=True)
class Profile:
    roles: tuple[str, ...] = ()
    grad_year: int | None = None
    locations: tuple[str, ...] = ()
    company_tiers: dict = field(default_factory=dict)   # company name -> tier
    keywords: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()


@dataclass(frozen=True)
class User:
    """One person this process serves: their own watchlist and profile."""
    id: str
    watchlist: Watchlist
    profile: Profile


# ---- validation helpers -------------------------------------------------

def _read_yaml(path: Path) -> dict:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"{path}: cannot read file ({exc.strerror or exc})") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: invalid YAML: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: top level must be a mapping, got {type(data).__name__}")
    return data


def _section(data: dict, key: str, path: Path) -> list:
    value = data.get(key) or []
    if not isinstance(value, list):
        raise ConfigError(f"{path}: '{key}' must be a list")
    return value


def _entry(entry, where: str, path: Path) -> dict:
    if not isinstance(entry, dict):
        raise ConfigError(f"{path}: {where} must be a mapping")
    return entry


def _require_str(entry: dict, key: str, where: str, path: Path) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{path}: {where} needs a non-empty string '{key}'")
    return value.strip()


def _choice(value, choices, key: str, where: str, path: Path):
    if value not in choices:
        raise ConfigError(f"{path}: {where} '{key}' must be one of {list(choices)}, got {value!r}")
    return value


def _number(entry: dict, key: str, default, where: str, path: Path):
    value = entry.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ConfigError(f"{path}: {where} '{key}' must be a positive number, got {value!r}")
    return value


def _str_list(data: dict, key: str, path: Path) -> tuple[str, ...]:
    value = data.get(key) or []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"{path}: '{key}' must be a list of strings")
    return tuple(value)


# ---- loaders -------------------------------------------------------------

def load_watchlist(path=None) -> Watchlist:
    path = Path(path) if path else CONFIG_DIR / "watchlist.yaml"
    data = _read_yaml(path)
    companies = []
    for i, raw in enumerate(_section(data, "companies", path)):
        where = f"companies[{i}]"
        e = _entry(raw, where, path)
        companies.append(Company(
            name=_require_str(e, "name", where, path),
            ats=_choice(e.get("ats"), ATS_KINDS, "ats", where, path),
            slug=_require_str(e, "slug", where, path),
            tier=_choice(e.get("tier", "B"), TIERS, "tier", where, path),
        ))
    accounts = []
    for i, raw in enumerate(_section(data, "instagram", path)):
        where = f"instagram[{i}]"
        e = _entry(raw, where, path)
        accounts.append(InstagramAccount(
            username=_require_str(e, "username", where, path).lstrip("@"),
            interval_s=float(_number(e, "interval_s", 300, where, path)),
            priority=int(_number(e, "priority", 5, where, path)),
        ))
    if len(accounts) > 5:
        raise ConfigError(f"{path}: 'instagram' supports at most 5 accounts, got {len(accounts)}")
    feeds = []
    for i, raw in enumerate(_section(data, "feeds", path)):
        where = f"feeds[{i}]"
        e = _entry(raw, where, path)
        url = _require_str(e, "url", where, path)
        if not url.startswith(("http://", "https://")):
            raise ConfigError(f"{path}: {where} 'url' must start with http:// or https://, got {url!r}")
        feeds.append(Feed(url=url, kind=_choice(e.get("kind", "rss"), FEED_KINDS, "kind", where, path)))
    repos = []
    for i, raw in enumerate(_section(data, "repos", path)):
        where = f"repos[{i}]"
        e = _entry(raw, where, path)
        name = _require_str(e, "name", where, path)
        if name.count("/") != 1 or not all(name.split("/")):
            raise ConfigError(f"{path}: {where} 'name' must look like owner/name, got {name!r}")
        repos.append(Repo(name=name, path=str(e.get("path") or "")))
    return Watchlist(tuple(companies), tuple(accounts), tuple(feeds), tuple(repos))


def load_profile(path=None) -> Profile:
    path = Path(path) if path else CONFIG_DIR / "profile.yaml"
    data = _read_yaml(path)
    grad_year = data.get("grad_year")
    if grad_year is not None and (isinstance(grad_year, bool) or not isinstance(grad_year, int)
                                  or not 2000 <= grad_year <= 2100):
        raise ConfigError(f"{path}: 'grad_year' must be a year like 2027, got {grad_year!r}")
    tiers = data.get("company_tiers") or {}
    if not isinstance(tiers, dict):
        raise ConfigError(f"{path}: 'company_tiers' must be a mapping of company name to tier")
    for name, tier in tiers.items():
        _choice(tier, TIERS, "company_tiers", f"'{name}'", path)
    return Profile(
        roles=_str_list(data, "roles", path),
        grad_year=grad_year,
        locations=_str_list(data, "locations", path),
        company_tiers=dict(tiers),
        keywords=_str_list(data, "keywords", path),
        exclude=_str_list(data, "exclude", path),
    )


def load_users(path=None) -> tuple[User, ...]:
    """Each user names their own watchlist/profile files, relative to users.yaml
    (not a 'config/<id>/' convention: the first user's files predate this and
    stay at the top of config/)."""
    path = Path(path) if path else CONFIG_DIR / "users.yaml"
    data = _read_yaml(path)
    entries = _section(data, "users", path)
    if not entries:
        raise ConfigError(f"{path}: 'users' must list at least one user")
    users = []
    for i, raw in enumerate(entries):
        where = f"users[{i}]"
        e = _entry(raw, where, path)
        users.append(User(
            id=_require_str(e, "id", where, path),
            watchlist=load_watchlist(path.parent / _require_str(e, "watchlist", where, path)),
            profile=load_profile(path.parent / _require_str(e, "profile", where, path)),
        ))
    ids = [u.id for u in users]
    if len(ids) != len(set(ids)):
        raise ConfigError(f"{path}: duplicate user id(s): {sorted({i for i in ids if ids.count(i) > 1})}")
    return tuple(users)
