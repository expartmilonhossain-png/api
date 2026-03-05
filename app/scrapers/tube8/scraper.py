from __future__ import annotations

import json
import re
import os
from typing import Any

import httpx
from bs4 import BeautifulSoup


def can_handle(host: str) -> bool:
    host_lower = host.lower()
    return "tube8.com" in host_lower


def get_categories() -> list[dict]:
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        json_path = os.path.join(current_dir, "categories.json")
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


async def fetch_html(url: str) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Referer": "https://www.tube8.com/",
    }
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(30.0, connect=30.0),
        headers=headers,
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.text


def _extract_video_streams(html: str) -> dict[str, Any]:
    """
    Tube8 is on MindGeek/Aylo network — same mediaDefinitions structure as PornHub/RedTube.
    """
    streams: list[dict] = []
    hls_url = None

    # Try page_params (Tube8/RedTube standard) first, then flashvars as fallback
    m = re.search(r"mediaDefinitions[\"']?\s*:\s*(\[.*?\])", html, re.DOTALL)
    if not m:
        m = re.search(r"var\s+page_params\s*=\s*(\{.*?\});", html, re.DOTALL)

    if m:
        try:
            raw = m.group(1)
            if raw.startswith("["):
                data = json.loads(raw)
            else:
                full = json.loads(raw)
                data = full.get("mediaDefinitions", [])
                if not data and "video" in full:
                    data = full["video"].get("mediaDefinitions", [])

            for md in data:
                video_url = md.get("videoUrl")
                if not video_url:
                    continue

                fmt = md.get("format", "mp4")
                quality = md.get("quality", "")

                if isinstance(quality, int):
                    quality = str(quality)
                elif isinstance(quality, list):
                    quality = str(quality[0]) if quality else ""

                if video_url.startswith("/"):
                    video_url = "https://www.tube8.com" + video_url

                stream = {
                    "quality": quality or "unknown",
                    "url": video_url,
                    "format": fmt,
                }

                if fmt == "hls" or ".m3u8" in video_url:
                    q = quality or ""
                    if isinstance(q, str) and q.isdigit():
                        q = f"{q}p"
                    elif not q:
                        q = "adaptive"
                    mq = re.search(r"(\d{3,4})[pP]?[_/]", video_url)
                    if mq and q == "adaptive":
                        q = f"{mq.group(1)}p"
                    stream["quality"] = q
                    stream["format"] = "hls"
                    if "/" not in (video_url or ""):
                        pass
                    if not hls_url:
                        hls_url = video_url

                streams.append(stream)
        except Exception:
            pass

    # Sort by quality descending
    def _qval(s: dict) -> int:
        q = s.get("quality", "")
        digits = "".join(filter(str.isdigit, str(q)))
        return int(digits) if digits else 0

    streams.sort(key=_qval, reverse=True)

    default_url = hls_url or (streams[0]["url"] if streams else None)
    return {"streams": streams, "default": default_url, "has_video": bool(streams)}


def parse_page(html: str, url: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")

    # Title
    title = None
    t_tag = soup.find("title")
    if t_tag:
        title = t_tag.get_text(strip=True)
        for suffix in [" - Tube8", " | Tube8", " - tube8.com"]:
            title = title.replace(suffix, "")

    # Thumbnail from og:image
    thumbnail = None
    meta_thumb = soup.find("meta", property="og:image")
    if meta_thumb:
        thumbnail = meta_thumb.get("content")

    # Duration from video:duration meta or page_params
    duration = None
    meta_dur = soup.find("meta", property="video:duration")
    if meta_dur:
        try:
            secs = int(meta_dur.get("content"))
            m, s = divmod(secs, 60)
            h, m = divmod(m, 60)
            duration = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
        except Exception:
            pass

    # Views
    views = None
    v_el = soup.select_one(".video-views, .views, .video_views")
    if v_el:
        m = re.search(r"[\d,]+", v_el.get_text())
        if m:
            views = m.group(0)

    # Uploader
    uploader = None
    u_el = soup.select_one(".video-channels-item a, .video-uploaded-by a, .video_channel a")
    if u_el:
        uploader = u_el.get_text(strip=True)

    # Tags
    tags: list[str] = []
    for t in soup.select(".video-tags a, .tag a"):
        txt = t.get_text(strip=True)
        if txt:
            tags.append(txt)

    video_data = _extract_video_streams(html)

    return {
        "url": url,
        "title": title,
        "description": None,
        "thumbnail_url": thumbnail,
        "duration": duration,
        "views": views,
        "uploader_name": uploader,
        "category": "Tube8",
        "tags": tags,
        "video": video_data,
        "related_videos": [],
        "preview_url": None,
    }


async def scrape(url: str) -> dict[str, Any]:
    html = await fetch_html(url)
    return parse_page(html, url)


async def list_videos(base_url: str, page: int = 1, limit: int = 20) -> list[dict[str, Any]]:
    url = base_url.rstrip("/")

    if page > 1:
        sep = "&" if "?" in url else "?"
        url += f"{sep}page={page}"

    try:
        html = await fetch_html(url)
    except Exception:
        return []

    soup = BeautifulSoup(html, "lxml")
    items: list[dict] = []

    # Tube8 uses similar card structure to RedTube
    for box in soup.select("li.videoblock_list, .video-item, .pcVideoListItem"):
        try:
            # Title & link
            title_tag = box.select_one(
                ".video-title-text, .video_title a, .title a, a.img-wrapper[title]"
            )
            link_tag = box.select_one("a.video_link, a.img-wrapper, a[href*='/video/']")

            href = None
            title = None

            if title_tag:
                title = title_tag.get_text(strip=True)
                href = title_tag.get("href")

            if not href and link_tag:
                href = link_tag.get("href")
                if not title:
                    title = link_tag.get("title", "")

            if not href:
                continue

            if not href.startswith("http"):
                href = "https://www.tube8.com" + href

            # Thumbnail
            thumb = None
            img = box.select_one("img.thumb, img.lazy, img[data-src], img[data-thumb_url]")
            if img:
                thumb = img.get("data-src") or img.get("data-thumb_url") or img.get("src")
                if not title and img.get("alt"):
                    title = img.get("alt")

            # Duration
            dur_el = box.select_one(".tm_video_duration, .duration, .video_duration")
            duration = dur_el.get_text(strip=True) if dur_el else "0:00"

            # Views
            views = "0"
            v_el = box.select_one("span.info-views, .views, .video_views")
            if v_el:
                views = v_el.get_text(strip=True).replace("views", "").strip()

            # Uploader
            uploader = "Unknown"
            u_el = box.select_one(".author-title-text, .username a, .video-uploader a")
            if u_el:
                uploader = u_el.get_text(strip=True)

            items.append({
                "url": href,
                "title": title or "Unknown",
                "thumbnail_url": thumb,
                "duration": duration,
                "views": views,
                "uploader_name": uploader,
                "preview_url": thumb,
            })
        except Exception:
            continue

    return items[:limit]
