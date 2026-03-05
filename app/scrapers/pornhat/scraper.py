from __future__ import annotations

import json
import re
import os
from typing import Any

import httpx
from bs4 import BeautifulSoup


def can_handle(host: str) -> bool:
    host_lower = host.lower()
    return "pornhat.com" in host_lower


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
        "Referer": "https://www.pornhat.com/",
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
    Pornhat uses jwplayer / a standard JSON sources array embedded in the page.
    It embeds a sources list like:
        sources: [{"file": "https://...mp4", "label": "720p"}, ...]
    or as a var config block.
    """
    streams: list[dict] = []
    hls_url = None

    # Pattern 1: jwplayer "sources" config array
    m = re.search(r"sources\s*:\s*(\[.*?\])", html, re.DOTALL)
    if m:
        try:
            src_list = json.loads(m.group(1))
            for item in src_list:
                file_url = item.get("file") or item.get("src") or item.get("url") or ""
                label = item.get("label") or item.get("res") or item.get("quality") or ""
                if not file_url:
                    continue
                fmt = "hls" if ".m3u8" in file_url else "mp4"
                q = str(label).replace("p", "").strip()
                if q.isdigit():
                    q = f"{q}p"
                else:
                    q = label or "unknown"
                stream = {"quality": q, "url": file_url, "format": fmt}
                if fmt == "hls":
                    hls_url = hls_url or file_url
                streams.append(stream)
        except Exception:
            pass

    # Pattern 2: "file": "..." scattered JSON
    if not streams:
        for fm in re.finditer(r'"file"\s*:\s*"(https?://[^"]+\.(?:mp4|m3u8)[^"]*)"', html):
            file_url = fm.group(1)
            fmt = "hls" if ".m3u8" in file_url else "mp4"
            # Try to extract quality from URL
            mq = re.search(r"(\d{3,4})[pP]", file_url)
            quality = f"{mq.group(1)}p" if mq else "unknown"
            streams.append({"quality": quality, "url": file_url, "format": fmt})
            if fmt == "hls":
                hls_url = hls_url or file_url

    # Pattern 3: raw mp4/m3u8 URLs embedded in JS variable assignments
    if not streams:
        for fm in re.finditer(r"(?:video_url|videoUrl)\s*[=:]\s*['\"]?(https?://[^'\"]+\.(?:mp4|m3u8)[^'\"]*)", html):
            file_url = fm.group(1)
            fmt = "hls" if ".m3u8" in file_url else "mp4"
            mq = re.search(r"(\d{3,4})[pP]", file_url)
            quality = f"{mq.group(1)}p" if mq else "default"
            streams.append({"quality": quality, "url": file_url, "format": fmt})
            if fmt == "hls":
                hls_url = hls_url or file_url

    # Sort descending by quality
    def _qval(s: dict) -> int:
        digits = "".join(filter(str.isdigit, str(s.get("quality", ""))))
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
        for suffix in [" - Pornhat", " | Pornhat", " - pornhat.com", " - PornHat"]:
            title = title.replace(suffix, "")

    # og:image for thumbnail
    thumbnail = None
    meta_thumb = soup.find("meta", property="og:image")
    if meta_thumb:
        thumbnail = meta_thumb.get("content")

    # Duration
    duration = None
    meta_dur = soup.find("meta", property="video:duration")
    if meta_dur:
        try:
            secs = int(meta_dur.get("content"))
            m_, s = divmod(secs, 60)
            h, m_ = divmod(m_, 60)
            duration = f"{h}:{m_:02d}:{s:02d}" if h else f"{m_}:{s:02d}"
        except Exception:
            pass

    if not duration:
        dur_el = soup.select_one(".duration, .video-duration, [itemprop='duration']")
        if dur_el:
            duration = dur_el.get_text(strip=True)

    # Views
    views = None
    v_el = soup.select_one(".views, .video-views, .view-count")
    if v_el:
        mv = re.search(r"[\d,]+", v_el.get_text())
        if mv:
            views = mv.group(0)

    # Uploader
    uploader = None
    u_el = soup.select_one(".username a, .uploader a, .video-uploader a, [itemprop='author'] a")
    if u_el:
        uploader = u_el.get_text(strip=True)

    # Tags
    tags: list[str] = []
    for t in soup.select(".tags a, .video-tags a, .tag-list a"):
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
        "category": "Pornhat",
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
    seen_hrefs: set[str] = set()

    # Pornhat video grid is inside #custom_list_videos_videos (or id starting with custom_list_videos)
    # Each card is div.item.thumb-bl-video (class "item thumb-bl thumb-bl-video video_N")
    # Scope to the video list container to skip non-video sections (channels, models, friends)
    video_list = (
        soup.select_one("#custom_list_videos_videos")
        or soup.select_one("[id^='custom_list_videos']")
        or soup  # fallback to full page
    )

    for card in video_list.select("div.item.thumb-bl-video, div.thumb-bl-video"):
        if len(items) >= limit:
            break
        try:
            # The main anchor has href="/video/slug/" and a title attribute
            a = card.select_one("a[href*='/video/']")
            if not a:
                continue

            href = a.get("href", "")
            if not href or href in seen_hrefs:
                continue
            seen_hrefs.add(href)

            if not href.startswith("http"):
                href = "https://www.pornhat.com" + href

            # Title from anchor's title attribute (most reliable)
            title = a.get("title", "")

            # Thumbnail from img data-original (lazy-loaded)
            thumb = None
            img = a.find("img") or card.find("img")
            if img:
                thumb = (
                    img.get("data-original")
                    or img.get("data-src")
                    or img.get("src")
                )
                if not title:
                    title = img.get("alt", "")

            # Preview video URL from data-preview-custom on the anchor
            preview = a.get("data-preview-custom") or a.get("data-preview") or thumb

            # ul.video-meta contains: duration (first li), date (fa-calendar-o), views (fa-eye)
            duration = "0:00"
            date_added = ""
            views = "0"

            meta_ul = card.select_one("ul.video-meta")
            if meta_ul:
                li_items = meta_ul.find_all("li")
                for li in li_items:
                    icon = li.find("i")
                    span = li.find("span")
                    text = span.get_text(strip=True) if span else li.get_text(strip=True)

                    if icon:
                        icon_cls = " ".join(icon.get("class", []))
                        if "calendar" in icon_cls:
                            date_added = text
                        elif "eye" in icon_cls:
                            views = text
                        elif "clock" in icon_cls or "time" in icon_cls:
                            duration = text
                    else:
                        # First li without icon is usually the duration
                        if duration == "0:00" and text:
                            duration = text

            # Fallback for duration from .duration element
            if duration == "0:00":
                dur_el = card.select_one(".duration, .time")
                if dur_el:
                    duration = dur_el.get_text(strip=True)

            # Uploader
            uploader = "Unknown"
            u_el = card.select_one(".username a, .uploader a, .author a")
            if u_el:
                uploader = u_el.get_text(strip=True)

            items.append({
                "url": href,
                "title": title or "Unknown",
                "thumbnail_url": thumb,
                "duration": duration,
                "views": views,
                "date": date_added,
                "uploader_name": uploader,
                "preview_url": preview,
            })
        except Exception:
            continue

    return items[:limit]


