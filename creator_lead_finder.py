#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Public AI/3D creator lead finder with a small local web dashboard.

The tool only reads public search-result pages and public profile metadata.
It never logs into social platforms, sends messages, likes, follows, or
collects private contact information.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote_plus, unquote, urlencode, urljoin, urlparse
from urllib.request import Request, urlopen


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
RESULTS_FILE = DATA_DIR / "leads.json"
CSV_FILE = DATA_DIR / "leads.csv"
RULES_FILE = DATA_DIR / "rules.json"
LOCAL_ENV_FILE = DATA_DIR / ".env"

DEFAULT_KEYWORDS = [
    "ai",
    "3d ai",
    "game",
    "ai game",
    "roblox",
    "steam",
    "combos",
    "comfyui",
    "tripo",
    "meshy",
    "blender",
    "glb",
    "astra",
    "opus",
    "vibe coding",
    "aigc",
]

LEAD_RULES = {
    "audience": "KOC / 素人创作者",
    "follower_tiers": [100, 300, 500, 1000, 5000, 10000],
    "minimum_followers": 100,
    "minimum_related_posts": 2,
    "minimum_views_per_post": 100,
    "platform_priority": [
        {"platform": "X", "weight": "高"},
        {"platform": "Reddit", "weight": "高"},
        {"platform": "GitHub", "weight": "高"},
        {"platform": "YouTube", "weight": "高"},
        {"platform": "小红书", "weight": "中高"},
        {"platform": "抖音", "weight": "低"},
    ],
    "keywords": DEFAULT_KEYWORDS,
    "platforms": ["x"],
    "daily_run_time": "09:00",
    "daily_limit": 100,
}

PLATFORM_DOMAINS = {
    "x": {"x.com", "twitter.com"},
    "reddit": {"reddit.com", "www.reddit.com"},
    "youtube": {"youtube.com", "www.youtube.com", "youtu.be"},
    "xhs": {"xiaohongshu.com", "www.xiaohongshu.com", "xhslink.com"},
    "douyin": {"douyin.com", "www.douyin.com"},
    "instagram": {"instagram.com"},
    "tiktok": {"tiktok.com"},
    "artstation": {"artstation.com"},
    "behance": {"behance.net"},
    "github": {"github.com"},
    "linkedin": {"linkedin.com"},
}

PLATFORM_LABELS = {
    "x": "X",
    "reddit": "Reddit",
    "youtube": "YouTube",
    "xhs": "小红书",
    "douyin": "抖音",
    "instagram": "Instagram",
    "tiktok": "TikTok",
    "artstation": "ArtStation",
    "behance": "Behance",
    "github": "GitHub",
    "linkedin": "LinkedIn",
}

PROFILE_BLOCKLIST = {
    "home",
    "explore",
    "search",
    "login",
    "signup",
    "settings",
    "i",
    "intent",
    "hashtag",
    "compose",
    "notifications",
    "messages",
    "bookmarks",
    "groups",
}

CATEGORY_TERMS = {
    "AI 图像": ["ai artist", "ai art", "generative art", "stable diffusion", "midjourney", "flux", "comfyui", "生成艺术", "ai绘画"],
    "AI 视频": ["ai video", "ai filmmaker", "text to video", "image to video", "runway", "kling", "pika", "sora", "ai电影", "ai视频"],
    "3D / Blender": ["3d", "blender", "cinema 4d", "c4d", "maya", "houdini", "mesh", "建模", "blender"],
    "游戏 / 实时引擎": ["game art", "game dev", "unreal", "unity", "godot", "real-time", "虚幻", "游戏开发"],
    "动画 / VFX": ["animation", "motion design", "motion graphics", "vfx", "visual effects", "动画", "特效", "动态设计"],
    "3D 打印 / 实体": ["3d printing", "3d print", "printable", "maker", "cad", "3d打印", "实体创作"],
    "教程 / 教育": ["tutorial", "course", "educator", "workshop", "教学", "教程", "课程", "工作坊"],
    "工具 / 工作流": ["workflow", "tool builder", "developer", "api", "plugin", "comfy", "插件", "开发者", "工作流"],
}

POSITIVE_TERMS = {
    "creator": 4,
    "artist": 4,
    "designer": 4,
    "filmmaker": 5,
    "director": 4,
    "animator": 4,
    "visual": 2,
    "generative": 4,
    "ai": 3,
    "3d": 4,
    "blender": 4,
    "vfx": 4,
    "motion": 3,
    "game": 2,
    "tutorial": 2,
    "workshop": 2,
    "open to collab": 6,
    "collab": 3,
    "合作": 4,
    "创作者": 4,
    "艺术家": 4,
    "设计师": 4,
}

ORGANIZATION_TERMS = [
    "official",
    "company",
    "studio",
    "platform",
    "agency",
    "technologies",
    "technology",
    "labs",
    "research",
    "foundation",
    "university",
    "inc",
    "llc",
    "ltd",
    "media",
    "magazine",
    "network",
    "community",
    "software",
    "games",
    "团队",
    "官方",
    "公司",
    "工作室",
    "实验室",
    "研究院",
    "基金会",
]

ORGANIZATION_TOKEN_RE = re.compile(
    r"(?<![a-z0-9])(?:" + "|".join(re.escape(term) for term in ORGANIZATION_TERMS if term.isascii()) + r")(?![a-z0-9])",
    re.I,
)

URL_RE = re.compile(r"https?://[^\s<>\"'，。；、！？）》】]+", re.I)
HANDLE_RE = re.compile(r"(?<![\w])@([A-Za-z0-9_]{1,32})")
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
WHITESPACE_RE = re.compile(r"\s+")


@dataclass
class Lead:
    platform: str
    name: str
    handle: str
    profile_url: str
    bio: str = ""
    categories: list[str] = field(default_factory=list)
    score: int = 0
    creator_type: str = "个人创作者"
    source_query: str = ""
    source_url: str = ""
    contact_route: str = "先看主页和作品，再通过平台公开入口联系"
    captured_at: str = ""
    followers: int | None = None
    follower_tier: str = "待核验"
    follower_verified: bool = False
    follower_verified_at: str = ""
    follower_source: str = ""
    related_posts: int | None = None
    min_views: int | None = None
    activity_score: int = 0
    activity_feedback: str = "待核验公开活跃度"
    featured_work_urls: list[str] = field(default_factory=list)
    contact_links: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    verification_status: str = "待核验"
    data_quality: str = "搜索摘要"
    last_post_at: str = ""
    hicreator_verified: bool = False
    hicreator_verified_at: str = ""
    hicreator_source: str = ""
    public_email: str = ""
    creator_location: str = ""
    hicreator_selected_posts: int | None = None
    views_average: int | None = None
    views_max: int | None = None
    likes_average: int | None = None
    reposts_average: int | None = None
    engagement_rate: float | None = None
    posts_30d: int | None = None
    weekly_post_frequency: float | None = None
    avg_post_interval_days: float | None = None
    last_post_age: str = ""


class SearchResultParser(HTMLParser):
    """Parse ordinary visible result blocks from Bing and similar pages."""

    def __init__(self) -> None:
        super().__init__()
        self.blocks: list[dict] = []
        self.block_stack: list[dict] = []
        self.anchor: dict | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if tag == "li" and ("b_algo" in classes or "result" in classes):
            block = {"text": [], "links": []}
            self.block_stack.append(block)
        if tag == "a" and self.block_stack:
            self.anchor = {"href": attributes.get("href") or "", "text": []}

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.anchor is not None:
            if self.block_stack:
                self.block_stack[-1]["links"].append(
                    {"href": self.anchor["href"], "text": clean_text(" ".join(self.anchor["text"]))}
                )
            self.anchor = None
        if tag == "li" and self.block_stack:
            block = self.block_stack.pop()
            text = clean_text(" ".join(block["text"]))
            if text and block["links"]:
                self.blocks.append({"text": text, "links": block["links"]})

    def handle_data(self, data: str) -> None:
        if not data.strip():
            return
        if self.block_stack:
            self.block_stack[-1]["text"].append(data)
        if self.anchor is not None:
            self.anchor["text"].append(data)


class MetaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self.meta: dict[str, str] = {}
        self._title_depth = 0
        self._title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "title":
            self._title_depth = 1
        if tag == "meta":
            key = attributes.get("name") or attributes.get("property") or ""
            value = attributes.get("content") or ""
            if key and value:
                self.meta[key.lower()] = clean_text(html.unescape(value))

    def handle_endtag(self, tag: str) -> None:
        if tag == "title" and self._title_depth:
            self.title = clean_text(" ".join(self._title_parts))
            self._title_depth = 0

    def handle_data(self, data: str) -> None:
        if self._title_depth:
            self._title_parts.append(data)


def clean_text(value: str) -> str:
    return WHITESPACE_RE.sub(" ", html.unescape(value or "")).strip()


def parse_metric(value: str | int | float | None) -> int | None:
    """Convert public counters such as 1.2K / 3万 into integers."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = clean_text(str(value)).lower().replace(",", "")
    match = re.search(r"(\d+(?:\.\d+)?)\s*(万|w|k|千|m|百万)?", text)
    if not match:
        return None
    number = float(match.group(1))
    unit = match.group(2) or ""
    multiplier = {"万": 10000, "w": 10000, "千": 1000, "k": 1000, "m": 1000000, "百万": 1000000}.get(unit, 1)
    return int(number * multiplier)


def first_metric(text: str, labels: Iterable[str]) -> int | None:
    lowered = clean_text(text).lower()
    label_pattern = "|".join(re.escape(label.lower()) for label in labels)
    match = re.search(rf"(?:{label_pattern})\s*[:：]?\s*(\d+(?:\.\d+)?\s*(?:万|w|k|千|m|百万)?)", lowered)
    return parse_metric(match.group(1)) if match else None


def metric_before_label(text: str, labels: Iterable[str]) -> int | None:
    lowered = clean_text(text).lower()
    label_pattern = "|".join(re.escape(label.lower()) for label in labels)
    match = re.search(rf"(\d+(?:\.\d+)?\s*(?:万|w|k|千|m|百万)?)\s*(?:{label_pattern})\b", lowered)
    return parse_metric(match.group(1)) if match else None


def follower_tier(followers: int | None) -> str:
    if followers is None:
        return "待核验"
    tiers = LEAD_RULES["follower_tiers"]
    matched = max((tier for tier in tiers if followers >= tier), default=0)
    return f">={matched:,}" if matched else "<100"


def activity_feedback(related_posts: int | None, min_views: int | None, last_post_at: str = "") -> tuple[int, str, str]:
    """Return a transparent activity score, feedback and verification label."""
    score = 0
    reasons: list[str] = []
    if related_posts is not None:
        if related_posts >= 2:
            score += 40
            reasons.append(f"相关内容 {related_posts} 条")
        else:
            reasons.append(f"相关内容 {related_posts} 条，未达 2 条")
    else:
        reasons.append("相关内容待核验")
    if min_views is not None:
        if min_views > 100:
            score += 40
            reasons.append(f"最高公开播放/浏览 {min_views:,}")
        else:
            reasons.append(f"最高公开播放/浏览 {min_views:,}，未超过 100")
    else:
        reasons.append("播放/浏览量待核验")
    if last_post_at:
        score += 20
        reasons.append(f"最近活动：{last_post_at[:10]}")
    status = "已达内容门槛" if related_posts is not None and related_posts >= 2 and min_views is not None and min_views > 100 else "待核验"
    return score, "；".join(reasons), status


def qualification_status(lead: Lead) -> str:
    if not lead.follower_verified or lead.followers is None:
        return "待核验粉丝量"
    if lead.followers < LEAD_RULES["minimum_followers"]:
        return "低于100粉"
    if lead.related_posts is not None and lead.related_posts >= LEAD_RULES["minimum_related_posts"] and lead.min_views is not None and lead.min_views > LEAD_RULES["minimum_views_per_post"]:
        return "正式候选"
    return "粉丝已核验，内容待核验"


def contact_links_from_text(text: str, profile_url: str) -> list[str]:
    links: list[str] = []
    for email in EMAIL_RE.findall(text):
        links.append(f"mailto:{email}")
    for url in URL_RE.findall(text):
        host = domain_for(url)
        if host in {"linktr.ee", "beacons.ai", "stan.store", "solo.to", "bio.site", "hoo.be", "campsite.bio"}:
            links.append(url.rstrip(".,;"))
    return list(dict.fromkeys(links))[:8]


def request_text(url: str, timeout: int = 20) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/131 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.8,en;q=0.6",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def search_bing(query: str) -> tuple[str, list[dict]]:
    url = "https://www.bing.com/search?q=" + quote_plus(query) + "&setlang=en"
    try:
        page = request_text(url)
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        return url, [{"error": str(error)}]
    parser = SearchResultParser()
    parser.feed(page)
    return url, parser.blocks


def domain_for(url: str) -> str:
    host = (urlparse(url).netloc or "").lower().removeprefix("www.")
    return host


def normalise_result_url(url: str, base_url: str = "https://www.bing.com") -> str:
    if not url:
        return ""
    url = urljoin(base_url, html.unescape(url))
    parsed = urlparse(url)
    if parsed.netloc.endswith("bing.com") and parsed.path.startswith("/ck/a"):
        query = parse_qs(parsed.query)
        if query.get("u"):
            encoded = query["u"][0]
            if encoded.startswith("a1"):
                encoded = encoded[2:]
            try:
                return unquote(encoded)
            except Exception:
                pass
    return url


def platform_for_url(url: str, requested: Iterable[str]) -> str | None:
    host = domain_for(url)
    for platform in requested:
        if host in PLATFORM_DOMAINS.get(platform, set()):
            return platform
    return None


def profile_url_for(platform: str, url: str) -> str | None:
    parsed = urlparse(url)
    parts = [unquote(part).strip() for part in parsed.path.split("/") if part.strip()]
    if not parts:
        return None
    first = parts[0].lstrip("@").strip()
    if first.lower() in PROFILE_BLOCKLIST:
        return None
    if platform in {"x", "instagram", "tiktok", "github", "linkedin", "behance", "artstation"}:
        if platform == "x" and ("status" in [part.lower() for part in parts] or len(parts) > 2):
            return None
        return f"https://{parsed.netloc}/{first}"
    if platform == "youtube":
        if first.startswith("@"):
            return f"https://{parsed.netloc}/{first}"
        if first in {"channel", "c"} and len(parts) > 1:
            return f"https://{parsed.netloc}/{'/'.join(parts[:2])}"
        if first == "user" and len(parts) > 1:
            return f"https://{parsed.netloc}/user/{parts[1]}"
    return None


def categories_for(text: str) -> list[str]:
    lowered = text.lower()
    matches = []
    for category, terms in CATEGORY_TERMS.items():
        if any(term.lower() in lowered for term in terms):
            matches.append(category)
    return matches or ["待确认方向"]


def score_lead(text: str, platform: str) -> tuple[int, str]:
    lowered = text.lower()
    score = 0
    for term, weight in POSITIVE_TERMS.items():
        if term in lowered:
            score += weight
    if platform == "x":
        score += 3
    if organization_signal(text):
        score -= 4
    if "http" in lowered:
        score += 2
    creator_type = "机构 / 工作室" if organization_signal(text) else "个人创作者"
    return max(score, 0), creator_type


def organization_signal(text: str) -> bool:
    lowered = clean_text(text).lower()
    if any(term in lowered for term in ("官方", "公司", "工作室", "实验室", "研究院", "基金会")):
        return True
    return bool(ORGANIZATION_TOKEN_RE.search(lowered))


def likely_individual_creator(name: str, bio: str, platform: str, account_type: str = "") -> bool:
    if account_type and account_type.lower() not in {"user", "person", "individual"}:
        return False
    text = clean_text(f"{name} {bio}")
    if organization_signal(text):
        return False
    lowered = text.lower()
    handle = clean_text(name).lower().replace("@", "")
    if any(token in handle for token in ("official", "_inc", "-inc", "_llc", "-llc", "_studio", "-studio", "_labs", "-labs")):
        return False
    if platform == "github" and account_type == "Organization":
        return False
    return True


def infer_name(handle: str, anchor_text: str, block_text: str) -> str:
    text = clean_text(anchor_text)
    if text and len(text) <= 100:
        text = re.sub(r"@[A-Za-z0-9_]{1,32}", "", text)
        text = re.sub(r"\bVerified account\b", "", text, flags=re.I)
        text = re.sub(r"\s*[|·-]\s*(X|Twitter|Instagram|TikTok).*$", "", text, flags=re.I)
        text = text.strip()
        if text and "http" not in text.lower():
            return text[:100]
    match = HANDLE_RE.search(block_text)
    return "@" + match.group(1) if match else ("@" + handle if handle else "未命名创作者")


def enrich_profile(url: str) -> tuple[str, str]:
    """Read only public metadata; many platforms may return a login shell."""
    try:
        page = request_text(url, timeout=10)
    except (HTTPError, URLError, TimeoutError, OSError):
        return "", ""
    parser = MetaParser()
    parser.feed(page[:1_500_000])
    title = parser.title or parser.meta.get("og:title", "")
    description = parser.meta.get("description") or parser.meta.get("og:description", "")
    return clean_text(title), clean_text(description)


def inspect_profile(url: str) -> dict:
    """Read public metadata and counters when a platform exposes them."""
    try:
        page = request_text(url, timeout=12)
    except (HTTPError, URLError, TimeoutError, OSError):
        return {}
    parser = MetaParser()
    parser.feed(page[:2_000_000])
    title = clean_text(parser.title or parser.meta.get("og:title", ""))
    description = clean_text(parser.meta.get("description") or parser.meta.get("og:description", ""))
    visible = clean_text(re.sub(r"<[^>]+>", " ", page[:2_000_000]))
    combined = clean_text(" ".join([title, description, visible[:120_000]]))
    followers = first_metric(combined, ["followers", "follower", "粉丝", "订阅者", "订阅"])
    related_posts = first_metric(combined, ["posts", "videos", "作品", "videos", "posts"])
    min_views = first_metric(combined, ["views", "view", "播放", "浏览", "观看"])
    contact_links = contact_links_from_text(combined, url)
    return {
        "title": title,
        "description": description,
        "followers": followers,
        "related_posts": related_posts,
        "min_views": min_views,
        "contact_links": contact_links,
        "page_text": combined,
    }


def build_queries(keywords: list[str], platforms: list[str]) -> list[str]:
    queries = []
    for keyword in keywords:
        for platform in platforms:
            domains = " OR ".join(f"site:{domain}" for domain in sorted(PLATFORM_DOMAINS[platform]))
            query = f"({domains}) {keyword} -inurl:status"
            queries.append(query)
    return queries


def request_json(url: str, timeout: int = 20) -> dict | list:
    headers = {
        "User-Agent": "AI-Creator-Radar/1.0 (public research tool)",
        "Accept": "application/json",
    }
    github_token = os.environ.get("GITHUB_TOKEN", "").strip()
    if github_token and urlparse(url).hostname == "api.github.com":
        headers["Authorization"] = f"Bearer {github_token}"
    request = Request(
        url,
        headers=headers,
    )
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def read_youtube_api_key() -> str:
    key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if key:
        return key
    if not LOCAL_ENV_FILE.exists():
        return ""
    try:
        for line in LOCAL_ENV_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith("YOUTUBE_API_KEY="):
                return line.partition("=")[2].strip().strip('"').strip("'")
    except OSError:
        return ""
    return ""


def request_youtube_json(resource: str, params: dict[str, str | int]) -> dict:
    api_key = read_youtube_api_key()
    if not api_key:
        raise RuntimeError("未配置 YOUTUBE_API_KEY")
    query = {**params, "key": api_key}
    payload = request_json(f"https://www.googleapis.com/youtube/v3/{resource}?{urlencode(query)}")
    if not isinstance(payload, dict):
        raise RuntimeError("YouTube API 返回格式异常")
    if payload.get("error"):
        error = payload["error"]
        message = error.get("message") if isinstance(error, dict) else str(error)
        raise RuntimeError(f"YouTube API：{message or '请求失败'}")
    return payload


def extract_youtube_initial_data(page: str) -> dict:
    """Extract the public search data embedded in a YouTube HTML page."""
    patterns = (
        r"var ytInitialData\s*=\s*(\{.*?\});</script>",
        r"ytInitialData\s*=\s*(\{.*?\});</script>",
    )
    for pattern in patterns:
        match = re.search(pattern, page, flags=re.DOTALL)
        if not match:
            continue
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    raise RuntimeError("YouTube 公开搜索页暂时没有返回结果")


def youtube_runs_text(value: object) -> str:
    if not isinstance(value, dict):
        return ""
    runs = value.get("runs")
    if isinstance(runs, list):
        return clean_text("".join(str(item.get("text", "")) for item in runs if isinstance(item, dict)))
    simple_text = value.get("simpleText")
    return clean_text(str(simple_text or ""))


def iter_youtube_renderers(value: object, renderer_name: str) -> Iterable[dict]:
    if isinstance(value, dict):
        renderer = value.get(renderer_name)
        if isinstance(renderer, dict):
            yield renderer
        for child in value.values():
            yield from iter_youtube_renderers(child, renderer_name)
    elif isinstance(value, list):
        for child in value:
            yield from iter_youtube_renderers(child, renderer_name)


def youtube_channel_metadata(channel_url: str) -> tuple[int | None, str]:
    """Read subscriber count and description when the public channel page exposes them."""
    about_url = channel_url.rstrip("/") + "/about"
    try:
        page = request_text(about_url, timeout=15)
    except (HTTPError, URLError, TimeoutError, OSError):
        return None, ""
    subscriber_match = re.search(
        r"([0-9]+(?:[.,][0-9]+)?\s*(?:K|M|B|万|千)?)\s*(?:subscribers|subscriber|位订阅者|订阅者)",
        page,
        flags=re.IGNORECASE,
    )
    subscribers = parse_metric(subscriber_match.group(1)) if subscriber_match else None
    parser = MetaParser()
    parser.feed(page[:1_500_000])
    description = parser.meta.get("description") or parser.meta.get("og:description", "")
    if not description:
        description_match = re.search(r'"description"\s*:\s*\{"simpleText":"(.*?)"\}', page)
        if description_match:
            description = bytes(description_match.group(1), "utf-8").decode("unicode_escape", errors="ignore")
    return subscribers, clean_text(description)


def search_youtube_public(keywords: list[str], limit: int) -> tuple[list[Lead], list[str]]:
    """Find public YouTube creator channels without requiring an API key."""
    channel_rows: dict[str, dict] = {}
    errors: list[str] = []
    max_results = min(20, max(8, limit // 2))

    for keyword in keywords:
        search_url = f"https://www.youtube.com/results?search_query={quote_plus(keyword)}"
        try:
            page = request_text(search_url, timeout=25)
            payload = extract_youtube_initial_data(page)
        except Exception as error:
            errors.append(f"YouTube {keyword}: {error}")
            continue
        for video in list(iter_youtube_renderers(payload, "videoRenderer"))[:max_results]:
            video_id = clean_text(str(video.get("videoId") or ""))
            if not video_id:
                continue
            owner = video.get("longBylineText") or video.get("ownerText") or {}
            runs = owner.get("runs") if isinstance(owner, dict) else []
            first_run = runs[0] if isinstance(runs, list) and runs and isinstance(runs[0], dict) else {}
            endpoint = first_run.get("navigationEndpoint") or {}
            browse_endpoint = endpoint.get("browseEndpoint") or {}
            channel_id = clean_text(str(browse_endpoint.get("browseId") or ""))
            if not channel_id:
                continue
            command = endpoint.get("commandMetadata") or {}
            web_metadata = command.get("webCommandMetadata") or {}
            relative_url = clean_text(str(web_metadata.get("url") or ""))
            owner_name = youtube_runs_text(owner) or channel_id
            row = channel_rows.setdefault(
                channel_id,
                {
                    "channel_id": channel_id,
                    "channel_name": owner_name,
                    "channel_url": urljoin("https://www.youtube.com", relative_url) if relative_url else f"https://www.youtube.com/channel/{channel_id}",
                    "videos": {},
                    "keywords": set(),
                },
            )
            row["videos"][video_id] = {
                "title": youtube_runs_text(video.get("title") or {}),
                "view_count": parse_metric(youtube_runs_text(video.get("viewCountText") or {})),
                "published": youtube_runs_text(video.get("publishedTimeText") or {}),
            }
            row["keywords"].add(keyword)
        time.sleep(0.2)

    leads: list[Lead] = []
    rows = sorted(channel_rows.values(), key=lambda item: (-len(item["videos"]), item["channel_name"].lower()))[: max(limit, 50)]
    for row in rows:
        name = clean_text(row["channel_name"])
        profile_url = row["channel_url"]
        subscribers, description = youtube_channel_metadata(profile_url)
        if not likely_individual_creator(name, description, "youtube"):
            continue
        videos = list(row["videos"].items())
        videos.sort(key=lambda item: item[1].get("view_count") or 0, reverse=True)
        views = [item[1]["view_count"] for item in videos if item[1].get("view_count") is not None]
        work_urls = [f"https://www.youtube.com/watch?v={video_id}" for video_id, _ in videos[:8]]
        lead = make_lead(
            platform="youtube",
            name=name,
            handle=profile_url.rstrip("/").rsplit("/", 1)[-1],
            profile_url=profile_url,
            bio=description or "YouTube 公开频道（无需 API 抓取）",
            source_query="、".join(sorted(row["keywords"])),
            source_url=work_urls[0] if work_urls else profile_url,
            featured_work_urls=work_urls,
            followers=subscribers,
            related_posts=len(videos),
            min_views=max(views) if views else None,
        )
        lead.follower_verified = subscribers is not None
        lead.follower_verified_at = datetime.now(timezone.utc).isoformat(timespec="seconds") if subscribers is not None else ""
        lead.follower_source = "YouTube 公开频道页" if subscribers is not None else ""
        lead.data_quality = "YouTube 公开搜索页"
        lead.activity_feedback = (
            f"相关视频 {len(videos)} 条；最高公开播放 {max(views):,}"
            if views
            else f"相关视频 {len(videos)} 条；播放量待核验"
        )
        lead.verification_status = qualification_status(lead)
        leads.append(lead)
        if len(leads) >= limit:
            break
        time.sleep(0.15)

    return sorted(leads, key=lambda item: (-item.score, -item.activity_score, item.handle.lower()))[:limit], errors


def search_youtube(keywords: list[str], limit: int) -> tuple[list[Lead], list[str]]:
    """Use the official API when configured, otherwise use public YouTube HTML."""
    if read_youtube_api_key():
        return search_youtube_api(keywords, limit)
    return search_youtube_public(keywords, limit)


def read_x_bearer_token() -> str:
    token = os.environ.get("X_BEARER_TOKEN", "").strip()
    if token:
        return token
    if not LOCAL_ENV_FILE.exists():
        return ""
    try:
        for line in LOCAL_ENV_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith("X_BEARER_TOKEN="):
                return line.partition("=")[2].strip().strip('"').strip("'")
    except OSError:
        return ""
    return ""


def normalize_x_bearer_token(token: str) -> str:
    token = str(token or "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if not token:
        raise ValueError("请先粘贴 Bearer Token")
    if not token.isascii():
        raise ValueError("复制内容包含中文或特殊字符，请只复制 Bearer Token 本身")
    if any(character.isspace() for character in token):
        raise ValueError("Token 中不能包含空格或换行，请只复制 Bearer Token 本身")
    if len(token) < 20:
        raise ValueError("Token 格式不完整，请重新复制 Bearer Token")
    return token


def has_valid_x_bearer_token() -> bool:
    try:
        normalize_x_bearer_token(read_x_bearer_token())
    except ValueError:
        return False
    return True


def save_x_bearer_token(token: str) -> None:
    token = normalize_x_bearer_token(token)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOCAL_ENV_FILE.write_text(f"X_BEARER_TOKEN={token}\n", encoding="utf-8")
    try:
        LOCAL_ENV_FILE.chmod(0o600)
    except OSError:
        pass


def request_x_json(url: str, timeout: int = 30) -> dict | list:
    try:
        token = normalize_x_bearer_token(read_x_bearer_token())
    except ValueError as error:
        raise RuntimeError("当前保存的内容不是有效的 Bearer Token，请到 X 的 Keys & Tokens 页面重新复制") from error
    request = Request(
        url,
        headers={
            "User-Agent": "AI-Creator-Radar/1.0",
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8", errors="replace"))
    except HTTPError as error:
        if error.code == 402:
            raise RuntimeError("X API 已连接，但当前账号没有可用额度，请到 Developer Console 的 Credits 购买额度或兑换 Voucher") from error
        if error.code == 401:
            raise RuntimeError("X API 未接受当前 Token，请重新生成并复制 Bearer Token") from error
        raise


def make_lead(
    *,
    platform: str,
    name: str,
    handle: str,
    profile_url: str,
    bio: str,
    source_query: str,
    source_url: str,
    featured_work_urls: list[str] | None = None,
    followers: int | None = None,
    related_posts: int | None = None,
    min_views: int | None = None,
    contact_links: list[str] | None = None,
    last_post_at: str = "",
) -> Lead:
    combined = clean_text(f"{name} {bio} {source_query}")
    score, creator_type = score_lead(combined, platform)
    activity_score, feedback, verification = activity_feedback(related_posts, min_views, last_post_at)
    return Lead(
        platform=PLATFORM_LABELS.get(platform, platform),
        name=name,
        handle=handle,
        profile_url=profile_url,
        bio=bio[:700],
        categories=categories_for(combined),
        topics=[keyword for keyword in LEAD_RULES["keywords"] if keyword.lower() in combined.lower()][:8],
        score=score + round(activity_score / 20),
        creator_type=creator_type,
        source_query=source_query,
        source_url=source_url,
        captured_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        followers=followers,
        follower_tier=follower_tier(followers),
        related_posts=related_posts,
        min_views=min_views,
        activity_score=activity_score,
        activity_feedback=feedback,
        featured_work_urls=(featured_work_urls or [])[:8],
        contact_links=(contact_links or [])[:8],
        verification_status=verification,
        data_quality="公开 API" if platform in {"reddit", "github"} else "搜索摘要",
        last_post_at=last_post_at,
    )


def merge_lead(existing: Lead, incoming: Lead) -> Lead:
    """Keep the strongest public evidence seen across daily runs."""
    for field_name in ("bio", "source_query", "source_url", "last_post_at"):
        if len(str(getattr(incoming, field_name))) > len(str(getattr(existing, field_name))):
            setattr(existing, field_name, getattr(incoming, field_name))
    existing.score = max(existing.score, incoming.score)
    existing.activity_score = max(existing.activity_score, incoming.activity_score)
    existing.categories = sorted(set(existing.categories + incoming.categories))
    existing.topics = sorted(set(existing.topics + incoming.topics))
    existing.featured_work_urls = list(dict.fromkeys(existing.featured_work_urls + incoming.featured_work_urls))[:8]
    existing.contact_links = list(dict.fromkeys(existing.contact_links + incoming.contact_links))[:8]
    for field_name in (
        "public_email",
        "creator_location",
        "last_post_age",
        "hicreator_source",
        "hicreator_verified_at",
    ):
        incoming_value = getattr(incoming, field_name)
        if incoming_value and not getattr(existing, field_name):
            setattr(existing, field_name, incoming_value)
    for field_name in (
        "hicreator_selected_posts",
        "views_average",
        "views_max",
        "likes_average",
        "reposts_average",
        "posts_30d",
        "weekly_post_frequency",
        "avg_post_interval_days",
        "engagement_rate",
    ):
        incoming_value = getattr(incoming, field_name)
        if incoming_value is not None:
            setattr(existing, field_name, incoming_value)
    for field_name in ("followers", "related_posts", "min_views"):
        incoming_value = getattr(incoming, field_name)
        if incoming.follower_verified and incoming.data_quality == "X 主页公开页面" and incoming_value is not None:
            setattr(existing, field_name, incoming_value)
            continue
        if incoming_value is not None and (getattr(existing, field_name) is None or incoming_value > getattr(existing, field_name)):
            setattr(existing, field_name, incoming_value)
    if incoming.follower_verified:
        existing.follower_verified = True
        existing.follower_verified_at = incoming.follower_verified_at or existing.follower_verified_at
        existing.follower_source = incoming.follower_source or existing.follower_source
        if incoming.data_quality:
            existing.data_quality = incoming.data_quality
    if incoming.hicreator_verified:
        existing.hicreator_verified = True
        existing.hicreator_verified_at = incoming.hicreator_verified_at or existing.hicreator_verified_at
        existing.hicreator_source = incoming.hicreator_source or existing.hicreator_source
        if incoming.public_email:
            existing.public_email = incoming.public_email
        if incoming.creator_location:
            existing.creator_location = incoming.creator_location
    existing.follower_tier = follower_tier(existing.followers)
    _, existing.activity_feedback, existing.verification_status = activity_feedback(existing.related_posts, existing.min_views, existing.last_post_at)
    existing.verification_status = qualification_status(existing)
    if incoming.data_quality == "公开 API":
        existing.data_quality = incoming.data_quality
    return existing


def search_x_api(keywords: list[str], limit: int) -> tuple[list[Lead], list[str]]:
    grouped: dict[str, Lead] = {}
    errors: list[str] = []
    for keyword in keywords:
        query = f'"{keyword}" -is:retweet -is:reply'
        params = urlencode({
            "query": query,
            "max_results": 100,
            "tweet.fields": "created_at,public_metrics,author_id,attachments",
            "expansions": "author_id",
            "user.fields": "name,username,description,public_metrics,profile_image_url,verified",
        })
        source_url = f"https://api.x.com/2/tweets/search/recent?{params}"
        try:
            payload = request_x_json(source_url)
        except Exception as error:
            errors.append(f"X {keyword}: {error}")
            continue
        users = {str(user.get("id")): user for user in payload.get("includes", {}).get("users", [])}
        for tweet in payload.get("data", []) if isinstance(payload, dict) else []:
            author_id = str(tweet.get("author_id", ""))
            user = users.get(author_id)
            if not user or not user.get("username"):
                continue
            username = str(user["username"])
            if not likely_individual_creator(str(user.get("name") or username), str(user.get("description") or ""), "x"):
                continue
            profile_url = f"https://x.com/{username}"
            metrics = tweet.get("public_metrics") or {}
            view_count = parse_metric(metrics.get("impression_count") or metrics.get("view_count"))
            tweet_url = f"https://x.com/{username}/status/{tweet.get('id')}"
            followers = parse_metric((user.get("public_metrics") or {}).get("followers_count"))
            bio = clean_text(str(user.get("description") or ""))
            lead = make_lead(
                platform="x",
                name=str(user.get("name") or username),
                handle=f"@{username}",
                profile_url=profile_url,
                bio=bio,
                source_query=keyword,
                source_url=source_url,
                featured_work_urls=[tweet_url],
                followers=followers,
                related_posts=1,
                min_views=view_count,
                last_post_at=str(tweet.get("created_at") or ""),
            )
            lead.follower_verified = followers is not None
            lead.follower_verified_at = datetime.now(timezone.utc).isoformat(timespec="seconds") if followers is not None else ""
            lead.follower_source = "X API" if followers is not None else ""
            lead.data_quality = "X 官方 API"
            lead.activity_feedback = f"已发现相关公开帖子；当前关键词：{keyword}"
            lead.verification_status = "待继续累计内容"
            key = profile_url.lower()
            if key in grouped:
                grouped[key] = merge_lead(grouped[key], lead)
                grouped[key].related_posts = (grouped[key].related_posts or 0) + 1
                grouped[key].activity_score, grouped[key].activity_feedback, grouped[key].verification_status = activity_feedback(grouped[key].related_posts, grouped[key].min_views, grouped[key].last_post_at)
                grouped[key].data_quality = "X 官方 API"
            else:
                grouped[key] = lead
        time.sleep(0.2)
    ordered = sorted(grouped.values(), key=lambda item: (-item.score, -item.activity_score, item.handle.lower()))
    return ordered[:limit], errors


def search_github(keywords: list[str], limit: int) -> tuple[list[Lead], list[str]]:
    leads: dict[str, Lead] = {}
    errors: list[str] = []
    for keyword in keywords:
        query = urlencode({"q": f"{keyword} in:bio", "per_page": min(limit, 30)})
        source_url = f"https://api.github.com/search/users?{query}"
        try:
            payload = request_json(source_url)
        except Exception as error:
            errors.append(f"GitHub {keyword}: {error}")
            continue
        for item in payload.get("items", []) if isinstance(payload, dict) else []:
            login = str(item.get("login", "")).strip()
            if not login:
                continue
            profile_url = f"https://github.com/{login}"
            try:
                profile = request_json(f"https://api.github.com/users/{quote_plus(login)}")
                repos = request_json(f"https://api.github.com/users/{quote_plus(login)}/repos?sort=updated&per_page=5")
            except Exception as error:
                errors.append(f"GitHub @{login}: {error}")
                profile, repos = item, []
            if not likely_individual_creator(
                str(profile.get("name") or login),
                str(profile.get("bio") or ""),
                "github",
                str(profile.get("type") or item.get("type") or ""),
            ):
                continue
            repo_urls = [str(repo.get("html_url")) for repo in repos if repo.get("html_url")]
            repo_stars = [int(repo.get("stargazers_count", 0) or 0) for repo in repos]
            bio = clean_text(str(profile.get("bio") or item.get("login") or ""))
            lead = make_lead(
                platform="github",
                name=str(profile.get("name") or login),
                handle=f"@{login}",
                profile_url=profile_url,
                bio=f"{bio}；公开仓库 {profile.get('public_repos', 0)} 个",
                source_query=keyword,
                source_url=source_url,
                featured_work_urls=repo_urls,
                followers=parse_metric(profile.get("followers")),
                related_posts=parse_metric(profile.get("public_repos")),
                min_views=None,
                contact_links=[str(profile.get("blog"))] if profile.get("blog") else [],
            )
            lead.activity_feedback = f"公开仓库 {profile.get('public_repos', 0)} 个；最高仓库 Stars {max(repo_stars) if repo_stars else 0}（GitHub 不公开播放量）"
            lead.verification_status = "API 已确认，内容门槛需人工复核"
            key = profile_url.lower()
            leads[key] = merge_lead(leads[key], lead) if key in leads else lead
        time.sleep(0.3)
    return list(leads.values())[:limit], errors


def search_reddit(keywords: list[str], limit: int) -> tuple[list[Lead], list[str]]:
    grouped: dict[str, dict] = {}
    errors: list[str] = []
    for keyword in keywords:
        source_url = "https://www.reddit.com/search.json?" + urlencode({"q": keyword, "restrict_sr": "0", "sort": "new", "t": "year", "limit": 50})
        try:
            payload = request_json(source_url)
        except Exception as error:
            errors.append(f"Reddit {keyword}: {error}")
            continue
        for child in payload.get("data", {}).get("children", []) if isinstance(payload, dict) else []:
            data = child.get("data", {})
            author = str(data.get("author") or "").strip()
            if not author or author in {"[deleted]", "AutoModerator"}:
                continue
            row = grouped.setdefault(author.lower(), {"author": author, "posts": [], "keywords": set()})
            row["posts"].append(data)
            row["keywords"].add(keyword)
    leads = []
    for row in grouped.values():
        posts = sorted(row["posts"], key=lambda post: int(post.get("created_utc", 0) or 0), reverse=True)
        first = posts[0]
        profile_url = f"https://www.reddit.com/user/{row['author']}/"
        work_urls = [urljoin("https://www.reddit.com", str(post.get("permalink", ""))) for post in posts[:8] if post.get("permalink")]
        scores = [int(post.get("score", 0) or 0) for post in posts]
        subreddits = sorted({str(post.get("subreddit_name_prefixed", "")) for post in posts if post.get("subreddit_name_prefixed")})
        bio = f"Reddit 公开发帖 {len(posts)} 条；活跃板块：{'、'.join(subreddits[:5])}"
        lead = make_lead(
            platform="reddit",
            name=row["author"],
            handle=f"u/{row['author']}",
            profile_url=profile_url,
            bio=bio,
            source_query="、".join(sorted(row["keywords"])),
            source_url=work_urls[0] if work_urls else "https://www.reddit.com/",
            featured_work_urls=work_urls,
            related_posts=len(posts),
            min_views=None,
        )
        lead.activity_feedback = f"相关公开发帖 {len(posts)} 条；最高帖子得分 {max(scores) if scores else 0}（Reddit 未公开浏览量）"
        lead.verification_status = "已确认发帖活跃，浏览量待核验"
        leads.append(lead)
    return sorted(leads, key=lambda item: (-item.related_posts if item.related_posts is not None else 0, -item.score))[:limit], errors


def search_youtube_api(keywords: list[str], limit: int) -> tuple[list[Lead], list[str]]:
    """Find individual creator channels through the official YouTube Data API."""
    channel_rows: dict[str, dict] = {}
    errors: list[str] = []
    max_results = min(50, max(10, limit))

    for keyword in keywords:
        try:
            payload = request_youtube_json(
                "search",
                {
                    "part": "snippet",
                    "q": keyword,
                    "type": "video",
                    "order": "relevance",
                    "maxResults": max_results,
                },
            )
        except Exception as error:
            errors.append(f"YouTube {keyword}: {error}")
            continue
        for item in payload.get("items", []):
            snippet = item.get("snippet") or {}
            channel_id = str(snippet.get("channelId") or "").strip()
            video_id = str((item.get("id") or {}).get("videoId") or "").strip()
            if not channel_id or not video_id:
                continue
            row = channel_rows.setdefault(
                channel_id,
                {
                    "channel_id": channel_id,
                    "video_ids": set(),
                    "video_snippets": {},
                    "keywords": set(),
                },
            )
            row["video_ids"].add(video_id)
            row["video_snippets"][video_id] = snippet
            row["keywords"].add(keyword)

    if not channel_rows:
        return [], errors

    channel_details: dict[str, dict] = {}
    channel_ids = list(channel_rows)
    for start in range(0, len(channel_ids), 50):
        batch = channel_ids[start : start + 50]
        try:
            payload = request_youtube_json(
                "channels",
                {"part": "snippet,statistics", "id": ",".join(batch)},
            )
        except Exception as error:
            errors.append(f"YouTube 频道信息：{error}")
            continue
        for item in payload.get("items", []):
            channel_details[str(item.get("id") or "")] = item

    video_details: dict[str, dict] = {}
    video_ids = [video_id for row in channel_rows.values() for video_id in row["video_ids"]]
    for start in range(0, len(video_ids), 50):
        batch = video_ids[start : start + 50]
        try:
            payload = request_youtube_json(
                "videos",
                {"part": "snippet,statistics", "id": ",".join(batch)},
            )
        except Exception as error:
            errors.append(f"YouTube 视频信息：{error}")
            continue
        for item in payload.get("items", []):
            video_details[str(item.get("id") or "")] = item

    leads: list[Lead] = []
    for channel_id, row in channel_rows.items():
        channel = channel_details.get(channel_id)
        if not channel:
            continue
        snippet = channel.get("snippet") or {}
        statistics = channel.get("statistics") or {}
        name = clean_text(str(snippet.get("title") or channel_id))
        description = clean_text(str(snippet.get("description") or ""))
        if not likely_individual_creator(name, description, "youtube"):
            continue

        videos = [video_details[video_id] for video_id in row["video_ids"] if video_id in video_details]
        videos.sort(
            key=lambda item: int((item.get("statistics") or {}).get("viewCount", 0) or 0),
            reverse=True,
        )
        view_counts = [parse_metric((video.get("statistics") or {}).get("viewCount")) for video in videos]
        view_counts = [value for value in view_counts if value is not None]
        published_dates = [
            str((video.get("snippet") or {}).get("publishedAt") or "")
            for video in videos
            if (video.get("snippet") or {}).get("publishedAt")
        ]
        custom_url = str(snippet.get("customUrl") or "").strip()
        if custom_url:
            profile_url = f"https://www.youtube.com/{custom_url.lstrip('/')}"
        else:
            profile_url = f"https://www.youtube.com/channel/{channel_id}"
        work_urls = [
            f"https://www.youtube.com/watch?v={video.get('id')}"
            for video in videos[:8]
            if video.get("id")
        ]
        subscribers = parse_metric(statistics.get("subscriberCount"))
        lead = make_lead(
            platform="youtube",
            name=name,
            handle=custom_url or f"@{channel_id}",
            profile_url=profile_url,
            bio=description or "YouTube 公开频道",
            source_query="、".join(sorted(row["keywords"])),
            source_url=work_urls[0] if work_urls else profile_url,
            featured_work_urls=work_urls,
            followers=subscribers,
            related_posts=len(videos),
            min_views=max(view_counts) if view_counts else None,
            last_post_at=max(published_dates) if published_dates else "",
        )
        lead.follower_verified = subscribers is not None
        lead.follower_verified_at = datetime.now(timezone.utc).isoformat(timespec="seconds") if subscribers is not None else ""
        lead.follower_source = "YouTube Data API" if subscribers is not None else ""
        lead.data_quality = "YouTube 官方 API"
        lead.activity_feedback = (
            f"相关视频 {len(videos)} 条；最高公开播放 {max(view_counts):,}"
            if view_counts
            else f"相关视频 {len(videos)} 条；播放量待核验"
        )
        lead.verification_status = qualification_status(lead)
        leads.append(lead)

    ordered = sorted(leads, key=lambda item: (-item.score, -item.activity_score, item.handle.lower()))
    return ordered[:limit], errors


def collect_leads(keywords: list[str], platforms: list[str], limit: int = 50, enrich: bool = True) -> tuple[list[Lead], list[str]]:
    leads: dict[str, Lead] = {}
    errors: list[str] = []
    per_platform_limit = max(10, min(limit, 100))
    x_api_used = False

    if "x" in platforms and read_x_bearer_token():
        x_api_used = True
        x_leads, x_errors = search_x_api(keywords, per_platform_limit)
        errors.extend(x_errors)
        for lead in x_leads:
            key = lead.profile_url.rstrip("/").lower()
            leads[key] = merge_lead(leads[key], lead) if key in leads else lead
        if not x_leads and x_errors:
            x_api_used = False

    if "github" in platforms:
        github_leads, github_errors = search_github(keywords, per_platform_limit)
        errors.extend(github_errors)
        for lead in github_leads:
            key = lead.profile_url.rstrip("/").lower()
            leads[key] = merge_lead(leads[key], lead) if key in leads else lead

    if "reddit" in platforms:
        reddit_leads, reddit_errors = search_reddit(keywords, per_platform_limit)
        errors.extend(reddit_errors)
        for lead in reddit_leads:
            key = lead.profile_url.rstrip("/").lower()
            leads[key] = merge_lead(leads[key], lead) if key in leads else lead

    if "youtube" in platforms:
        youtube_leads, youtube_errors = search_youtube(keywords, per_platform_limit)
        errors.extend(youtube_errors)
        for lead in youtube_leads:
            key = lead.profile_url.rstrip("/").lower()
            leads[key] = merge_lead(leads[key], lead) if key in leads else lead

    search_platforms = [platform for platform in platforms if platform not in {"github", "reddit", "youtube"} and not (platform == "x" and x_api_used)]
    queries = build_queries(keywords, search_platforms)
    for query in queries:
        source_url, blocks = search_bing(query)
        for block in blocks:
            if "error" in block:
                errors.append(f"{query}: {block['error']}")
                continue
            block_text = clean_text(block.get("text", ""))
            for link in block.get("links", []):
                raw_url = normalise_result_url(link.get("href", ""))
                platform = platform_for_url(raw_url, search_platforms)
                if not platform:
                    continue
                profile_url = profile_url_for(platform, raw_url)
                if not profile_url:
                    continue
                key = profile_url.rstrip("/").lower()
                anchor_text = link.get("text", "")
                title = infer_name(key.rsplit("/", 1)[-1], anchor_text, block_text)
                lead = make_lead(
                    platform=platform,
                    name=title,
                    handle="@" + key.rsplit("/", 1)[-1],
                    profile_url=profile_url,
                    bio=block_text,
                    source_query=query,
                    source_url=source_url,
                    featured_work_urls=[raw_url] if raw_url != profile_url else [],
                    contact_links=contact_links_from_text(block_text, profile_url),
                )
                leads[key] = merge_lead(leads[key], lead) if key in leads else lead
        if len(leads) >= limit * 2:
            break
        time.sleep(0.4)

    ordered = [lead for lead in sorted(leads.values(), key=lambda item: (-item.score, -item.activity_score, item.platform, item.handle.lower())) if likely_individual_creator(lead.name, lead.bio, lead.platform.lower())][:limit]
    if enrich:
        for index, lead in enumerate(ordered):
            if lead.data_quality == "公开 API":
                continue
            inspected = inspect_profile(lead.profile_url)
            title = inspected.get("title", "")
            description = inspected.get("description", "")
            page_text = inspected.get("page_text", "")
            if title and lead.name.startswith("@"):
                lead.name = title[:100]
            if description and len(description) > 30:
                lead.bio = description[:700]
            combined = clean_text(f"{lead.name} {lead.bio} {page_text}")
            lead.categories = sorted(set(lead.categories + categories_for(combined)))
            lead.topics = sorted(set(lead.topics + [keyword for keyword in keywords if keyword.lower() in combined.lower()]))[:8]
            lead.followers = inspected.get("followers") or lead.followers
            lead.related_posts = inspected.get("related_posts") or lead.related_posts
            lead.min_views = inspected.get("min_views") or lead.min_views
            lead.follower_tier = follower_tier(lead.followers)
            lead.contact_links = list(dict.fromkeys(lead.contact_links + inspected.get("contact_links", [])))[:8]
            lead.featured_work_urls = list(dict.fromkeys(lead.featured_work_urls + [url for url in URL_RE.findall(page_text) if url != lead.profile_url]))[:8]
            lead.activity_score, lead.activity_feedback, lead.verification_status = activity_feedback(lead.related_posts, lead.min_views, lead.last_post_at)
            lead.data_quality = "公开页面摘要" if inspected else lead.data_quality
            if index < len(ordered) - 1:
                time.sleep(0.2)
    return ordered, errors


def write_results(leads: list[Lead], preserve_existing: bool = True) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    existing_rows = read_results() if preserve_existing else []
    merged: dict[str, Lead] = {}
    for row in existing_rows:
        if not isinstance(row, dict) or not row.get("profile_url"):
            continue
        allowed = {key: value for key, value in row.items() if key in Lead.__dataclass_fields__}
        for list_field in ("categories", "featured_work_urls", "contact_links", "topics"):
            if isinstance(allowed.get(list_field), str):
                allowed[list_field] = [item for item in allowed[list_field].split("、") if item]
        try:
            old_lead = Lead(**allowed)
        except TypeError:
            continue
        old_lead.verification_status = qualification_status(old_lead)
        merged[old_lead.profile_url.rstrip("/").lower()] = old_lead
    for lead in leads:
        key = lead.profile_url.rstrip("/").lower()
        merged[key] = merge_lead(merged[key], lead) if key in merged else lead
    final_leads = sorted(merged.values(), key=lambda item: (-item.score, -item.activity_score, item.platform, item.handle.lower()))
    payload = [asdict(lead) for lead in final_leads]
    RESULTS_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    fields = list(Lead.__dataclass_fields__.keys())
    with CSV_FILE.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for lead in final_leads:
            row = asdict(lead)
            for list_field in ("categories", "featured_work_urls", "contact_links", "topics"):
                row[list_field] = "、".join(row[list_field])
            writer.writerow(row)


def import_pasted_x_text(text: str, source_url: str = "https://x.com/search") -> list[Lead]:
    """Turn copied, visible X search text into reviewable lead rows."""
    leads: dict[str, Lead] = {}
    lines = [clean_text(line) for line in text.splitlines() if clean_text(line)]
    candidates = []
    seen_profiles = set()
    for index, line in enumerate(lines):
        nearby = " ".join(lines[index : min(len(lines), index + 2)])
        line_urls = URL_RE.findall(line)
        x_urls = []
        for url in line_urls:
            if domain_for(url) not in PLATFORM_DOMAINS["x"]:
                continue
            profile = profile_url_for("x", url)
            if profile:
                x_urls.append(profile)
        if x_urls:
            for profile in x_urls:
                if profile.lower() not in seen_profiles:
                    candidates.append((profile, line, nearby))
                    seen_profiles.add(profile.lower())
            continue
        line_handles = HANDLE_RE.findall(line)
        lowered_line = line.lower()
        mention_context = any(label in lowered_line for label in ("instagram", "insta", "tiktok", "youtube", "twitch", "roblox"))
        if mention_context:
            continue
        for handle in line_handles:
            standalone_handle = bool(re.fullmatch(r"@[A-Za-z0-9_]{1,32}", line.strip()))
            explicit_x_context = any(marker in lowered_line for marker in ("twitter", "x.com", "x followers", "x account"))
            if not standalone_handle and not explicit_x_context:
                continue
            profile = f"https://x.com/{handle}"
            if profile.lower() not in seen_profiles:
                candidates.append((profile, line, nearby))
                seen_profiles.add(profile.lower())
    for profile_url, anchor_text, context in candidates:
        key = profile_url.lower()
        if key in leads:
            continue
        handle = profile_url.rsplit("/", 1)[-1]
        surrounding = clean_text(context[:700])
        combined = f"{anchor_text} {surrounding}"
        keyword_match = re.search(r"(?:X\s+keyword|关键词)\s*:\s*([^\n]+)", combined, re.I)
        source_query = (
            f"X 公开搜索关键词：{clean_text(keyword_match.group(1))}（公开结果）"
            if keyword_match
            else "粘贴导入：X 公开搜索结果"
        )
        leads[key] = make_lead(
            platform="x",
            name=infer_name(handle, anchor_text, surrounding),
            handle="@" + handle,
            profile_url=profile_url,
            bio=surrounding,
            source_query=source_query,
            source_url=source_url,
            featured_work_urls=[url for url in URL_RE.findall(combined) if url != profile_url],
            followers=first_metric(combined, ["followers", "粉丝"]),
            related_posts=first_metric(combined, ["posts", "tweets", "作品", "帖子"]),
            min_views=first_metric(combined, ["views", "播放", "浏览"]),
            contact_links=contact_links_from_text(combined, profile_url),
        )
    return sorted(leads.values(), key=lambda item: (-item.score, item.handle.lower()))


def read_results() -> list[dict]:
    if not RESULTS_FILE.exists():
        return []
    try:
        payload = json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    return [row for row in payload if isinstance(row, dict) and row.get("platform")]


X_VERIFY_LOCK = threading.Lock()
X_VERIFY_QUEUE: list[str] = []
X_VERIFY_TOTAL = 0
X_VERIFY_DONE = 0
X_VERIFY_ACTIVE = False

DAILY_TASK_LOCK = threading.RLock()
DAILY_TASK = {
    "active": False,
    "phase": "idle",
    "started_at": "",
    "finished_at": "",
    "collection_updated": 0,
    "collection_new": 0,
    "collection_errors": [],
}


def daily_task_status() -> dict:
    with DAILY_TASK_LOCK:
        status = dict(DAILY_TASK)
        status["collection_errors"] = list(DAILY_TASK.get("collection_errors", []))
    with X_VERIFY_LOCK:
        status["verification"] = {
            "active": X_VERIFY_ACTIVE,
            "total": X_VERIFY_TOTAL,
            "done": X_VERIFY_DONE,
            "remaining": len(X_VERIFY_QUEUE),
        }
    return status


def _finish_daily_task_if_ready() -> None:
    with DAILY_TASK_LOCK:
        if DAILY_TASK["active"] and not X_VERIFY_ACTIVE and not X_VERIFY_QUEUE:
            DAILY_TASK["active"] = False
            DAILY_TASK["phase"] = "completed"
            DAILY_TASK["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")


def _run_daily_task(keywords: list[str], platforms: list[str], limit: int) -> None:
    try:
        with DAILY_TASK_LOCK:
            DAILY_TASK["phase"] = "collecting"
        leads, errors = run_collection(keywords, platforms, limit)
        with DAILY_TASK_LOCK:
            DAILY_TASK["collection_updated"] = len(leads)
            DAILY_TASK["collection_new"] = sum(
                1 for lead in leads if str(lead.captured_at or "").startswith(datetime.now(timezone.utc).date().isoformat())
            )
            DAILY_TASK["collection_errors"] = errors[:20]
            DAILY_TASK["phase"] = "verifying"
        verification = start_x_profile_verification()
        if not verification["active"]:
            _finish_daily_task_if_ready()
    except Exception as error:
        with DAILY_TASK_LOCK:
            DAILY_TASK["active"] = False
            DAILY_TASK["phase"] = "failed"
            DAILY_TASK["collection_errors"] = [str(error)]
            DAILY_TASK["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")


def start_daily_task() -> dict:
    with DAILY_TASK_LOCK:
        if DAILY_TASK["active"]:
            return daily_task_status()
        with X_VERIFY_LOCK:
            if X_VERIFY_ACTIVE:
                DAILY_TASK.update({
                    "phase": "blocked",
                    "collection_errors": ["已有 X 主页核验任务正在运行，请等它完成后再开始今日任务。"],
                })
                return daily_task_status()
        DAILY_TASK.update({
            "active": True,
            "phase": "starting",
            "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "finished_at": "",
            "collection_updated": 0,
            "collection_new": 0,
            "collection_errors": [],
        })
    threading.Thread(
        target=_run_daily_task,
        args=(DEFAULT_KEYWORDS, ["x"], int(LEAD_RULES.get("daily_limit", 100))),
        daemon=True,
    ).start()
    return daily_task_status()


def x_profile_from_url(url: str) -> str | None:
    parsed = urlparse(str(url or ""))
    if domain_for(url) not in PLATFORM_DOMAINS["x"]:
        return None
    parts = [unquote(part).strip() for part in parsed.path.split("/") if part.strip()]
    if len(parts) != 1 or parts[0].lower() in PROFILE_BLOCKLIST or not re.fullmatch(r"[A-Za-z0-9_]{1,32}", parts[0]):
        return None
    return f"https://x.com/{parts[0]}"


METRIC_TOKEN_RE = r"\d[\d,.]*(?:\.\d+)?\s*(?:万|w|k|千|m|百万)?"


def parse_rate(value: str | None) -> float | None:
    if not value:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)\s*%", value)
    return float(match.group(1)) if match else None


def first_metric_row(text: str, label: str, *, rate: bool = False) -> list[str]:
    token = r"\d+(?:\.\d+)?\s*%" if rate else METRIC_TOKEN_RE
    match = re.search(rf"{re.escape(label)}\s+({token})\s+({token})\s+({token})\s+({token})", text, re.I)
    return list(match.groups()) if match else []


def parse_hicreator_payload(payload: object) -> dict:
    if not isinstance(payload, dict):
        return {}
    profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else {}
    contents = payload.get("contents") if isinstance(payload.get("contents"), list) else []
    contents = [item for item in contents if isinstance(item, dict)]
    stats = payload.get("stats") if isinstance(payload.get("stats"), dict) else {}
    metric_values = {
        key: [parse_metric(item.get(key)) for item in contents if parse_metric(item.get(key)) is not None]
        for key in ("views", "likes", "shares", "comments")
    }
    views = metric_values["views"]
    likes = metric_values["likes"]
    shares = metric_values["shares"]
    comments = metric_values["comments"]
    published = sorted(
        [
            float(item.get("publishedAt"))
            for item in contents
            if isinstance(item.get("publishedAt"), (int, float)) and float(item.get("publishedAt")) > 0
        ],
        reverse=True,
    )
    now_ms = time.time() * 1000
    recent_30d = [stamp for stamp in published if stamp >= now_ms - 30 * 86400000]
    intervals = [
        (published[index] - published[index + 1]) / 86400000
        for index in range(len(published) - 1)
        if published[index] > published[index + 1]
    ]
    total_views = sum(views)
    total_engagement = sum(likes) + sum(comments) + sum(shares)
    result = {
        "followers": parse_metric(profile.get("followerCount")),
        "creator_location": clean_text(str(profile.get("location") or profile.get("region") or profile.get("accountBasedIn") or "")),
        "external_links": [str(item) for item in profile.get("externalLinks", []) if item] if isinstance(profile.get("externalLinks"), list) else [],
        "hicreator_selected_posts": parse_metric(payload.get("selectedPosts")) or (len(contents) or None),
        "views_average": parse_metric(stats.get("viewsAverage")) if stats.get("viewsAverage") is not None else (round(sum(views) / len(views)) if views else None),
        "views_max": parse_metric(stats.get("viewsMax")) if stats.get("viewsMax") is not None else (max(views) if views else None),
        "likes_average": parse_metric(stats.get("likesAverage")) if stats.get("likesAverage") is not None else (round(sum(likes) / len(likes)) if likes else None),
        "reposts_average": parse_metric(stats.get("repostsAverage")) if stats.get("repostsAverage") is not None else (round(sum(shares) / len(shares)) if shares else None),
        "engagement_rate": parse_rate(str(stats.get("engagementRate"))) if stats.get("engagementRate") is not None else (round(total_engagement / total_views * 100, 2) if total_views else None),
        "posts_30d": parse_metric(payload.get("posts30d")) or (len(recent_30d) or None),
        "weekly_post_frequency": float(payload.get("weeklyPostFrequency")) if payload.get("weeklyPostFrequency") is not None else (round(len(recent_30d) / (30 / 7), 2) if recent_30d else None),
        "avg_post_interval_days": float(payload.get("avgPostIntervalDays")) if payload.get("avgPostIntervalDays") is not None else (round(sum(intervals) / len(intervals), 2) if intervals else None),
        "last_post_age": "",
        "hicreator_verified": bool(profile or contents),
        "featured_work_urls": [str(item.get("url")) for item in contents if item.get("url")][:8],
    }
    if payload.get("lastPostAge"):
        result["last_post_age"] = clean_text(str(payload["lastPostAge"]))
    if published:
        age_seconds = max(0, time.time() - published[0] / 1000)
        if age_seconds < 3600:
            result["last_post_age"] = f"{max(1, round(age_seconds / 60))} 分钟前"
        elif age_seconds < 86400:
            result["last_post_age"] = f"{max(1, round(age_seconds / 3600))} 小时前"
        else:
            result["last_post_age"] = f"{max(1, round(age_seconds / 86400))} 天前"
    return result


def public_contact_links(text: str, extra_links: Iterable[str] | None = None) -> list[str]:
    allowed_hosts = {
        "linktr.ee",
        "beacons.ai",
        "stan.store",
        "solo.to",
        "bio.site",
        "hoo.be",
        "campsite.bio",
        "passionfroot.me",
        "calendly.com",
        "contra.com",
        "ko-fi.com",
        "buymeacoffee.com",
    }
    links = contact_links_from_text(text, "")
    for raw_url in extra_links or []:
        url = str(raw_url or "").strip().rstrip(".,;)")
        host = domain_for(url)
        if host in allowed_hosts:
            links.append(url)
    return list(dict.fromkeys(links))[:8]


def parse_x_profile_text(text: str, extra_links: Iterable[str] | None = None, hicreator_data: object = None) -> dict:
    visible = clean_text(text)
    card_match = re.search(r"hiCreator(?:\s+达人信息卡)?", visible, re.I)
    hicreator_text = visible[card_match.start():] if card_match else ""
    hicreator_ready = bool(card_match and ("达人公开信息" in hicreator_text or "数据分析" in hicreator_text))

    x_followers = metric_before_label(visible, ["followers", "follower", "粉丝"]) or first_metric(visible, ["followers", "follower", "粉丝"])
    hicreator_followers = metric_before_label(hicreator_text, ["粉丝", "followers"]) or first_metric(hicreator_text, ["粉丝", "followers"])
    followers = hicreator_followers or x_followers

    view_values = [
        parse_metric(match.group(1))
        for match in re.finditer(rf"({METRIC_TOKEN_RE})\s*(?:views?|播放|浏览|观看)", visible, re.I)
    ]
    view_values = [value for value in view_values if value is not None]
    post_count = max((parse_metric(match.group(1)) or 0 for match in re.finditer(rf"({METRIC_TOKEN_RE})\s+posts?", visible, re.I)), default=0)

    views_row = first_metric_row(hicreator_text, "播放量")
    likes_row = first_metric_row(hicreator_text, "点赞量")
    reposts_row = first_metric_row(hicreator_text, "转帖量")
    engagement_row = first_metric_row(hicreator_text, "互动率", rate=True)
    selected_match = re.search(r"基于\s*(\d+)\s*条所选内容", hicreator_text, re.I)
    posts_30d_match = re.search(r"30天发布\s*(?:≥\s*)?(\d+(?:\.\d+)?)", hicreator_text, re.I)
    interval_match = re.search(r"平均间隔\s*(\d+(?:\.\d+)?)\s*天", hicreator_text, re.I)
    weekly_match = re.search(r"周发布频率\s*(?:≥\s*)?(\d+(?:\.\d+)?)", hicreator_text, re.I)
    last_post_match = re.search(r"最近发布\s*(\d+\s*(?:分钟|小时|天|周)前)", hicreator_text, re.I)

    location = ""
    if hicreator_followers is not None:
        location_match = re.search(r"粉丝\s+(.+?)(?=\s+(?:达人公开信息|数据分析|受众报告|内容表现)|$)", hicreator_text, re.I)
        if location_match:
            location = clean_text(location_match.group(1))
    emails = EMAIL_RE.findall(visible)
    extra_link_list = [str(link) for link in (extra_links or []) if link]
    featured_links = list(dict.fromkeys(
        [url for url in URL_RE.findall(visible) if "/status/" in url]
        + [url for url in extra_link_list if "/status/" in url]
    ))[:8]
    parsed = {
        "followers": followers,
        "related_posts": int(selected_match.group(1)) if selected_match else (max(0, min(post_count, len(view_values))) if view_values else None),
        "min_views": parse_metric(views_row[3]) if len(views_row) == 4 else (max(view_values) if view_values else None),
        "hicreator_verified": hicreator_ready,
        "hicreator_selected_posts": int(selected_match.group(1)) if selected_match else None,
        "views_average": parse_metric(views_row[2]) if len(views_row) == 4 else None,
        "views_max": parse_metric(views_row[3]) if len(views_row) == 4 else None,
        "likes_average": parse_metric(likes_row[2]) if len(likes_row) == 4 else None,
        "reposts_average": parse_metric(reposts_row[2]) if len(reposts_row) == 4 else None,
        "engagement_rate": parse_rate(engagement_row[2]) if len(engagement_row) == 4 else None,
        "posts_30d": parse_metric(posts_30d_match.group(1)) if posts_30d_match else None,
        "weekly_post_frequency": float(weekly_match.group(1)) if weekly_match else None,
        "avg_post_interval_days": float(interval_match.group(1)) if interval_match else None,
        "last_post_age": clean_text(last_post_match.group(1)) if last_post_match else "",
        "public_email": emails[0] if emails else "",
        "creator_location": location,
        "contact_links": public_contact_links(visible, extra_link_list),
        "featured_work_urls": featured_links,
        "page_text": visible,
    }
    structured = parse_hicreator_payload(hicreator_data)
    if structured:
        for field_name, value in structured.items():
            if value is not None and value != "":
                parsed[field_name] = value
        parsed["contact_links"] = list(dict.fromkeys(parsed.get("contact_links", []) + [str(item) for item in (structured.get("external_links") or [])]))[:8]
    return parsed


def apply_x_profile_verification(profile_url: str, text: str, source_url: str = "", extra_links: Iterable[str] | None = None, hicreator_data: object = None) -> dict | None:
    canonical = x_profile_from_url(profile_url) or x_profile_from_url(source_url)
    if not canonical:
        return None
    parsed = parse_x_profile_text(text, extra_links, hicreator_data)
    if parsed.get("followers") is None and not parsed.get("hicreator_verified"):
        return None
    rows = read_results()
    target = next(
        (
            row
            for row in rows
            if (x_profile_from_url(str(row.get("profile_url", ""))) or "").rstrip("/").lower()
            == canonical.rstrip("/").lower()
        ),
        None,
    )
    if target is None:
        return None
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if parsed.get("followers") is not None:
        target["followers"] = parsed["followers"]
        target["follower_tier"] = follower_tier(parsed["followers"])
        target["follower_verified"] = True
        target["follower_verified_at"] = now
        target["follower_source"] = "hiCreator / X 主页公开页面" if parsed.get("hicreator_verified") else "X 主页公开页面"
    target["data_quality"] = "hiCreator 卡片 + X 主页公开页面" if parsed.get("hicreator_verified") else "X 主页公开页面"
    target["source_url"] = source_url or canonical
    if parsed.get("related_posts") is not None:
        target["related_posts"] = parsed["related_posts"]
    if parsed.get("min_views") is not None:
        target["min_views"] = parsed["min_views"]
    if parsed.get("hicreator_verified"):
        target["hicreator_verified"] = True
        target["hicreator_verified_at"] = now
        target["hicreator_source"] = "hiCreator 浏览器公开卡片"
        for field_name in (
            "public_email",
            "creator_location",
            "hicreator_selected_posts",
            "views_average",
            "views_max",
            "likes_average",
            "reposts_average",
            "engagement_rate",
            "posts_30d",
            "weekly_post_frequency",
            "avg_post_interval_days",
            "last_post_age",
        ):
            if parsed.get(field_name) is not None and parsed.get(field_name) != "":
                target[field_name] = parsed[field_name]
        target["contact_links"] = list(dict.fromkeys(target.get("contact_links", []) + parsed.get("contact_links", [])))[:8]
        target["featured_work_urls"] = list(dict.fromkeys(target.get("featured_work_urls", []) + parsed.get("featured_work_urls", [])))[:8]
        if parsed.get("public_email"):
            target["contact_links"] = list(dict.fromkeys([f"mailto:{parsed['public_email']}"] + target["contact_links"]))[:8]
    score, feedback, _ = activity_feedback(target.get("related_posts"), target.get("min_views"), target.get("last_post_at", ""))
    target["activity_score"] = max(int(target.get("activity_score", 0) or 0), score)
    target["activity_feedback"] = feedback
    target["verification_status"] = qualification_status(Lead(**{key: value for key, value in target.items() if key in Lead.__dataclass_fields__}))
    write_results([Lead(**{key: value for key, value in target.items() if key in Lead.__dataclass_fields__})])
    return target


def start_x_profile_verification() -> dict:
    global X_VERIFY_QUEUE, X_VERIFY_TOTAL, X_VERIFY_DONE, X_VERIFY_ACTIVE
    rows = read_results()
    queue = [
        str(row.get("profile_url", ""))
        for row in rows
        if x_profile_from_url(str(row.get("profile_url", "")))
        and (
            not bool(row.get("follower_verified"))
            or (bool(row.get("hicreator_verified")) and row.get("views_average") is None)
        )
    ]
    with X_VERIFY_LOCK:
        X_VERIFY_QUEUE = queue
        X_VERIFY_TOTAL = len(queue)
        X_VERIFY_DONE = 0
        X_VERIFY_ACTIVE = bool(queue)
        return {"active": X_VERIFY_ACTIVE, "total": X_VERIFY_TOTAL, "done": X_VERIFY_DONE, "remaining": len(queue)}


def next_x_profile_verification() -> dict:
    global X_VERIFY_ACTIVE
    with X_VERIFY_LOCK:
        if not X_VERIFY_QUEUE:
            X_VERIFY_ACTIVE = False
            return {"active": False, "url": "", "total": X_VERIFY_TOTAL, "done": X_VERIFY_DONE, "remaining": 0}
        return {"active": True, "url": X_VERIFY_QUEUE.pop(0), "total": X_VERIFY_TOTAL, "done": X_VERIFY_DONE, "remaining": len(X_VERIFY_QUEUE)}


def finish_x_profile_verification() -> None:
    global X_VERIFY_DONE, X_VERIFY_ACTIVE
    with X_VERIFY_LOCK:
        X_VERIFY_DONE += 1
        if not X_VERIFY_QUEUE:
            X_VERIFY_ACTIVE = False
    _finish_daily_task_if_ready()


def write_run_log(
    platforms: list[str],
    keywords: list[str],
    leads: list[Lead],
    errors: list[str],
    *,
    source: str = "公开采集",
    new_count: int = 0,
    total_after: int = 0,
) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    log_file = DATA_DIR / "runs.jsonl"
    payload = {
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "platforms": platforms,
        "keywords": keywords,
        "new_or_updated": len(leads),
        "new_count": new_count,
        "total_after": total_after,
        "qualified_after": sum(1 for lead in leads if lead.verification_status == "已达内容门槛"),
        "source": source,
        "errors": errors[:20],
    }
    with log_file.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False) + "\n")


def read_run_logs() -> list[dict]:
    log_file = DATA_DIR / "runs.jsonl"
    if not log_file.exists():
        return []
    rows: list[dict] = []
    try:
        for line in log_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            if isinstance(item, dict):
                rows.append(item)
    except (OSError, json.JSONDecodeError):
        return []
    return list(reversed(rows[-90:]))


def run_collection(keywords: list[str], platforms: list[str], limit: int, replace_existing: bool = False) -> tuple[list[Lead], list[str]]:
    before_profiles = set() if replace_existing else {str(row.get("profile_url", "")).rstrip("/").lower() for row in read_results()}
    leads, errors = collect_leads(keywords, platforms, limit=limit, enrich=True)
    if leads:
        write_results(leads, preserve_existing=not replace_existing)
    after_rows = read_results()
    new_count = sum(
        1
        for lead in leads
        if lead.profile_url.rstrip("/").lower() not in before_profiles
    )
    write_run_log(
        platforms,
        keywords,
        leads,
        errors,
        source="公开采集",
        new_count=new_count,
        total_after=len(after_rows),
    )
    return leads, errors


def run_daily(keywords: list[str], platforms: list[str], limit: int, interval_hours: float) -> None:
    while True:
        started = datetime.now(timezone.utc).isoformat(timespec="seconds")
        print(f"[{started}] 开始每日公开名单采集：{', '.join(PLATFORM_LABELS.get(item, item) for item in platforms)}")
        try:
            leads, errors = run_collection(keywords, platforms, limit)
            print(json.dumps({"updated": len(leads), "errors": errors[:5]}, ensure_ascii=False))
        except Exception as error:
            print(f"每日采集失败：{error}")
        time.sleep(max(3600, int(interval_hours * 3600)))


HTML_PAGE = r"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI 创作者雷达</title>
<style>
:root{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",sans-serif;color:#172033;background:#f5f7fb}
body{margin:0}.wrap{max-width:1180px;margin:0 auto;padding:28px 20px 56px}.hero{background:linear-gradient(135deg,#182a58,#4a56bc);color:#fff;border-radius:22px;padding:28px 30px;box-shadow:0 14px 40px #263b8930}.hero h1{margin:0 0 8px;font-size:30px}.hero p{margin:0;color:#dbe1ff}.panel{background:#fff;border:1px solid #e8ebf3;border-radius:18px;padding:20px;margin-top:18px;box-shadow:0 8px 24px #24355d0a}.row{display:flex;gap:12px;flex-wrap:wrap;align-items:center}label{font-size:14px;color:#4e5a73}.input{flex:1;min-width:300px;border:1px solid #d7dcea;border-radius:10px;padding:12px 13px;font-size:15px}.limit{width:80px}.checks{display:flex;gap:12px;flex-wrap:wrap;margin-top:14px}.check{background:#f4f6fb;border-radius:999px;padding:7px 12px;font-size:13px}.btn{border:0;border-radius:10px;padding:12px 18px;font-size:14px;font-weight:600;cursor:pointer}.primary{background:#4053c8;color:#fff}.secondary{background:#edf0ff;color:#34449d}.hint{font-size:13px;color:#78839b;margin-top:12px}.status{margin-top:16px;color:#415071;min-height:22px}.table-wrap{overflow:auto;margin-top:14px}table{border-collapse:collapse;width:100%;min-width:980px}th,td{text-align:left;padding:12px 10px;border-bottom:1px solid #edf0f5;vertical-align:top;font-size:13px}th{color:#65708a;background:#fafbfe;position:sticky;top:0}a{color:#3c51bb;text-decoration:none}a:hover{text-decoration:underline}.score{font-weight:700;color:#b35b14}.tag{display:inline-block;background:#eef1ff;color:#4753a6;border-radius:999px;padding:3px 8px;margin:2px;font-size:12px}.empty{text-align:center;color:#78839b;padding:32px}.footer{font-size:12px;color:#8a93a5;margin-top:16px}
</style></head><body><main class="wrap"><section class="hero"><h1>AI 创作者雷达</h1><p>从公开搜索结果发现 AI、3D、视频、游戏、动画和工具工作流创作者，自动去重和排序。</p></section>
<section class="panel"><div class="row"><input id="keywords" class="input" placeholder="关键词，用逗号分隔" value="ai, 3d ai, game, ai game, roblox, steam, comfyui, tripo, meshy, blender, glb, astra, opus, vibe coding, aigc"><label>数量 <input id="limit" class="input limit" type="number" min="10" max="200" value="100"></label><button class="btn primary" onclick="runSearch()">补充找名单</button><button class="btn secondary" onclick="downloadCsv()">导出 CSV</button></div>
<div class="checks" id="platforms"></div><div class="hint">目标：KOC / 素人；最低 100 粉，按 100、300、500、1000、5000、10000 分层；至少 2 条相关内容，且播放/浏览量超过 100。只读取公开信息，不会私信、点赞、关注，也不会抓取私人联系方式。</div><div id="status" class="status"></div></section>
<section class="panel"><strong>补充导入 X 结果</strong><div class="hint">在 Chrome 的 X 搜索结果页复制你看得到的文字或主页链接，粘贴到下面；程序只抽取公开的 X 主页地址。</div><textarea id="paste" class="input" style="width:100%;min-height:90px;margin-top:12px;box-sizing:border-box" placeholder="例如：@creator_name\nhttps://x.com/creator_name"></textarea><div class="row" style="margin-top:10px"><button class="btn secondary" onclick="importPasted()">导入复制内容</button><span id="importStatus" class="hint"></span></div></section>
<section class="panel"><div class="row"><strong>名单预览</strong><span id="count" class="hint"></span></div><div class="hint">当前列表是公开线索候选池；粉丝层级、至少 2 条相关内容和播放/浏览量 >100 会在每日任务中继续核验。</div><div class="table-wrap"><table><thead><tr><th>评分</th><th>平台</th><th>创作者</th><th>方向</th><th>公开简介/搜索摘要</th><th>来源</th></tr></thead><tbody id="tbody"></tbody></table></div><div class="footer">建议触达顺序：先看近期开源作品或教程，再通过平台公开入口联系；程序不自动发送任何内容。</div></section></main>
<script>
const platformOptions=[['x','X'],['youtube','YouTube']];
document.getElementById('platforms').innerHTML=platformOptions.map(([v,l])=>`<label class="check"><input type="checkbox" value="${v}" checked> ${l}</label>`).join('');
async function runSearch(){const status=document.getElementById('status');status.textContent='正在读取公开搜索结果，请稍等…';const keywords=document.getElementById('keywords').value.split(/[,，\n]+/).map(x=>x.trim()).filter(Boolean);const platforms=[...document.querySelectorAll('#platforms input:checked')].map(x=>x.value);const limit=Number(document.getElementById('limit').value||50);try{const res=await fetch('/api/search',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({keywords,platforms,limit})});const data=await res.json();if(!res.ok)throw new Error(data.error||'搜索失败');render(data.leads||[]);status.textContent=data.leads.length?`已完成：找到 ${data.leads.length} 条候选名单。${data.errors?.length?'部分来源不可访问，已跳过。':''}`:'公开搜索引擎没有返回可用的 X 主页。请在 Chrome 的 X 搜索结果页复制公开内容，再用下面的“导入复制内容”；这是因为 X 的登录搜索结果不会被普通搜索引擎直接开放给程序。';}catch(e){status.textContent='暂时无法完成搜索：'+e.message;}}
function render(leads){document.getElementById('count').textContent=`共 ${leads.length} 条候选`;const body=document.getElementById('tbody');body.innerHTML=leads.length?leads.map(x=>`<tr><td class="score">${x.score}</td><td>${x.platform}</td><td><a href="${x.profile_url}" target="_blank">${esc(x.name)}</a><br><span class="hint">${esc(x.handle)}</span></td><td>${(x.categories||[]).map(t=>`<span class="tag">${esc(t)}</span>`).join('')}</td><td>${esc(x.bio||'')}</td><td>${esc(x.source_query||'')}</td></tr>`).join(''):'<tr><td colspan="6" class="empty">还没有名单，先点击“补充找名单”。</td></tr>';}
function esc(s){return String(s||'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));}
function downloadCsv(){window.location='/api/export?format=csv';}
async function importPasted(){const text=document.getElementById('paste').value.trim();if(!text){document.getElementById('importStatus').textContent='请先粘贴公开内容。';return;}const status=document.getElementById('importStatus');status.textContent='正在导入…';try{const res=await fetch('/api/import',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text})});const data=await res.json();if(!res.ok)throw new Error(data.error||'导入失败');render(data.leads||[]);status.textContent=`已导入 ${data.leads.length} 个公开主页。`;}catch(e){status.textContent='导入失败：'+e.message;}}
fetch('/api/results').then(r=>r.json()).then(render).catch(()=>render([]));
</script></body></html>"""

PLATFORM_HTML_FILE = BASE_DIR / "dashboard.html"
if PLATFORM_HTML_FILE.exists():
    HTML_PAGE = PLATFORM_HTML_FILE.read_text(encoding="utf-8")


class AppHandler(BaseHTTPRequestHandler):
    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send(204, "text/plain; charset=utf-8", b"")

    def do_GET(self) -> None:  # noqa: N802
        path, _, query = self.path.partition("?")
        if path == "/":
            self._send(200, "text/html; charset=utf-8", HTML_PAGE.encode("utf-8"))
            return
        if path == "/api/results":
            self._send(200, "application/json; charset=utf-8", json.dumps(read_results(), ensure_ascii=False).encode("utf-8"))
            return
        if path == "/api/rules":
            self._send(200, "application/json; charset=utf-8", json.dumps(LEAD_RULES, ensure_ascii=False).encode("utf-8"))
            return
        if path == "/api/stats":
            rows = read_results()
            runs = read_run_logs()
            today = datetime.now(timezone.utc).date().isoformat()
            today_rows = [row for row in rows if str(row.get("captured_at", "")).startswith(today)]
            today_run = next((run for run in runs if str(run.get("run_at", "")).startswith(today)), {})
            stats = {
                "total": len(rows),
                "qualified": sum(1 for row in rows if row.get("verification_status") == "正式候选"),
                "platforms": {label: sum(1 for row in rows if row.get("platform") == label) for label in PLATFORM_LABELS.values()},
                "last_run": rows[0].get("captured_at", "") if rows else "",
                "today_count": len(today_rows),
                "today_new": int(today_run.get("new_count", 0) or 0),
                "today_run": today_run,
            }
            self._send(200, "application/json; charset=utf-8", json.dumps(stats, ensure_ascii=False).encode("utf-8"))
            return
        if path == "/api/daily":
            self._send(200, "application/json; charset=utf-8", json.dumps(read_run_logs(), ensure_ascii=False).encode("utf-8"))
            return
        if path == "/api/daily/task":
            self._send(200, "application/json; charset=utf-8", json.dumps(daily_task_status(), ensure_ascii=False).encode("utf-8"))
            return
        if path == "/api/config":
            configured = bool(read_x_bearer_token())
            body = json.dumps(
                {
                    "x_token_configured": configured and has_valid_x_bearer_token(),
                    "x_token_needs_recopy": configured and not has_valid_x_bearer_token(),
                },
                ensure_ascii=False,
            ).encode("utf-8")
            self._send(200, "application/json; charset=utf-8", body)
            return
        if path == "/api/x-verify/next":
            self._send(200, "application/json; charset=utf-8", json.dumps(next_x_profile_verification(), ensure_ascii=False).encode("utf-8"))
            return
        if path == "/api/x-verify/status":
            with X_VERIFY_LOCK:
                body = {"active": X_VERIFY_ACTIVE, "total": X_VERIFY_TOTAL, "done": X_VERIFY_DONE, "remaining": len(X_VERIFY_QUEUE)}
            self._send(200, "application/json; charset=utf-8", json.dumps(body, ensure_ascii=False).encode("utf-8"))
            return
        if path == "/api/export":
            params = parse_qs(query)
            if params.get("format", [""])[0] == "csv" and CSV_FILE.exists():
                content = CSV_FILE.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", "attachment; filename=ai_creator_leads.csv")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return
        self._send(404, "text/plain; charset=utf-8", b"Not found")

    def do_POST(self) -> None:  # noqa: N802
        if self.path not in {"/api/search", "/api/import", "/api/capture", "/api/config", "/api/daily/start", "/api/x-verify/start", "/api/x-verify/result"}:
            self._send(404, "application/json; charset=utf-8", b'{"error":"Not found"}')
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            if self.path == "/api/config":
                save_x_bearer_token(str(payload.get("x_bearer_token", "")))
                self._send(200, "application/json; charset=utf-8", b'{"saved":true,"x_token_configured":true}')
                return
            if self.path == "/api/daily/start":
                self._send(200, "application/json; charset=utf-8", json.dumps(start_daily_task(), ensure_ascii=False).encode("utf-8"))
                return
            if self.path == "/api/x-verify/start":
                self._send(200, "application/json; charset=utf-8", json.dumps(start_x_profile_verification(), ensure_ascii=False).encode("utf-8"))
                return
            if self.path == "/api/x-verify/result":
                profile_url = str(payload.get("profile_url", ""))
                result = apply_x_profile_verification(
                    profile_url,
                    str(payload.get("text", "")),
                    str(payload.get("source_url", "")),
                    payload.get("links", []),
                    payload.get("hicreator_data"),
                )
                finish_x_profile_verification()
                next_item = next_x_profile_verification()
                self._send(200, "application/json; charset=utf-8", json.dumps({"updated": bool(result), "lead": result, "next": next_item}, ensure_ascii=False).encode("utf-8"))
                return
            if self.path in {"/api/import", "/api/capture"}:
                before_profiles = {str(row.get("profile_url", "")).rstrip("/").lower() for row in read_results()}
                source_url = str(payload.get("source_url", ""))
                verified_profile = x_profile_from_url(source_url)
                verified_row = apply_x_profile_verification(
                    verified_profile or source_url,
                    str(payload.get("text", "")),
                    source_url,
                    payload.get("links", []),
                    payload.get("hicreator_data"),
                ) if verified_profile else None
                leads = import_pasted_x_text(str(payload.get("text", ""))) if not verified_row else []
                write_results(leads)
                after_rows = read_results()
                new_count = sum(
                    1
                    for lead in leads
                    if lead.profile_url.rstrip("/").lower() not in before_profiles
                )
                write_run_log(
                    ["x"],
                    ["X 主页粉丝核验" if verified_row else ("Wednesday / 自动同步" if self.path == "/api/capture" else "Wednesday / 手动导入")],
                    leads,
                    [],
                    source="X 主页粉丝核验" if verified_row else ("Wednesday / 自动同步" if self.path == "/api/capture" else "Wednesday / 手动导入"),
                    new_count=new_count,
                    total_after=len(after_rows),
                )
                body = json.dumps(
                    {"leads": after_rows, "imported": len(leads), "new_count": new_count, "verified": bool(verified_row), "source": payload.get("source", "")},
                    ensure_ascii=False,
                ).encode("utf-8")
                self._send(200, "application/json; charset=utf-8", body)
                return
            keywords = [clean_text(str(item)) for item in payload.get("keywords", []) if clean_text(str(item))]
            platforms = [str(item) for item in payload.get("platforms", []) if str(item) in PLATFORM_DOMAINS]
            limit = min(max(int(payload.get("limit", 50)), 10), 200)
            if not keywords:
                keywords = DEFAULT_KEYWORDS
            if not platforms:
                platforms = ["x"]
            leads, errors = run_collection(keywords, platforms, limit)
            if leads:
                result_rows = read_results()
            else:
                result_rows = read_results()
                errors.append("本次公开搜索没有返回可用结果，已保留已有名单。")
            body = json.dumps({"leads": result_rows, "errors": errors}, ensure_ascii=False).encode("utf-8")
            self._send(200, "application/json; charset=utf-8", body)
        except Exception as error:  # the UI receives a readable error instead of a broken connection
            self._send(500, "application/json; charset=utf-8", json.dumps({"error": str(error)}, ensure_ascii=False).encode("utf-8"))

    def log_message(self, *_args) -> None:
        return


def run_server(host: str, port: int) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not RULES_FILE.exists():
        RULES_FILE.write_text(json.dumps(LEAD_RULES, ensure_ascii=False, indent=2), encoding="utf-8")
    server = ThreadingHTTPServer((host, port), AppHandler)
    print(f"AI 创作者雷达已启动：http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="公开 AI/3D 创作者名单工具")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--once", action="store_true", help="只执行一次搜索并退出")
    parser.add_argument("--daily", action="store_true", help="持续每天执行一次公开采集")
    parser.add_argument("--interval-hours", type=float, default=24, help="每日采集间隔，默认 24 小时")
    parser.add_argument("--platforms", default="x")
    parser.add_argument("--keywords", default=", ".join(DEFAULT_KEYWORDS))
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--replace", action="store_true", help="用本轮严格筛选结果替换旧名单")
    args = parser.parse_args()
    keywords = [item.strip() for item in args.keywords.split(",") if item.strip()]
    platforms = [item.strip() for item in args.platforms.split(",") if item.strip() in PLATFORM_DOMAINS]
    if not platforms:
        platforms = ["x"]
    if args.once:
        leads, errors = run_collection(keywords, platforms, args.limit, replace_existing=args.replace)
        print(json.dumps({"count": len(leads), "errors": errors}, ensure_ascii=False, indent=2))
        return
    if args.daily:
        run_daily(keywords, platforms, args.limit, args.interval_hours)
        return
    run_server(args.host, args.port)


if __name__ == "__main__":
    main()
