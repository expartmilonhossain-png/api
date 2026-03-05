from __future__ import annotations

import json
import re
import os
from typing import Any

import httpx
from bs4 import BeautifulSoup


from app.core.pool import fetch_html as pool_fetch_html


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
        "Referer": "https://www.tube8.com/",
        "Cookie": "platform=pc" # Force desktop layout for consistent script tags
    }
    return await pool_fetch_html(url, headers=headers)


def _extract_video_streams(html: str) -> dict[str, Any]:
    """
    Tube8 is on MindGeek/Aylo network — same mediaDefinitions structure as PornHub/RedTube.
    """
    streams: list[dict] = []
    hls_url = None

    # Try page_params (Tube8 standard)
    m = re.search(r"var\s+page_params\s*=\s*(\{.*?\});", html, re.DOTALL)

    if m:
        try:
            raw = m.group(1)
            full = json.loads(raw)
            
            # Navigate to mediaDefinitions: page_params -> video_player_setup -> playervars -> mediaDefinitions
            setup = full.get("video_player_setup", {})
            playervars = setup.get("playervars", {})
            data = playervars.get("mediaDefinitions", [])
            
            if not data:
                # Fallback to general mediaDefinitions search
                m_alt = re.search(r"mediaDefinitions[\"']?\s*:\s*(\[.*?\])", html, re.DOTALL)
                if m_alt:
                    data = json.loads(m_alt.group(1))

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
                    mq = re.search(r"/(\d{3,4})[pP]?/", video_url)
                    if not mq:
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
    # Check if this is a direct Tube8 media JSON URL (user requested)
    if "/media/hls/" in url or "/media/mp4/" in url:
        return await scrape_json_media(url)
    
    # Check if this is a direct .m3u8 URL
    if ".m3u8" in url.lower():
        streams = await resolve_hls_master(url)
        if streams:
            video_data = {
                "streams": streams,
                "default": url,
                "has_video": True
            }
            return {
                "url": url,
                "title": "Tube8 HLS Playlist",
                "description": None,
                "thumbnail_url": None,
                "duration": None,
                "views": None,
                "uploader_name": "Tube8",
                "category": "Tube8",
                "tags": [],
                "video": video_data,
                "related_videos": [],
                "preview_url": None,
            }
        
    html = await fetch_html(url)
    return parse_page(html, url)


async def scrape_json_media(url: str) -> dict[str, Any]:
    """
    Directly scrape the HLS/MP4 JSON endpoints provided by Tube8.
    Recursively follows related media endpoints (e.g. HLS can point to MP4).
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        "Referer": "https://www.tube8.com/",
        "Cookie": "platform=pc"
    }
    
    all_streams = []
    raw_media_definitions = []
    processed_urls = {url}
    urls_to_process = [url]
    
    async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
        while urls_to_process:
            current_url = urls_to_process.pop(0)
            try:
                resp = await client.get(current_url, headers=headers)
                if resp.status_code != 200:
                    continue
                    
                data = resp.json()
                # Preserve raw quality objects for high-fidelity frontend support
                if isinstance(data, list):
                    raw_media_definitions.extend(data)
                
                for item in data:
                    video_url = item.get("videoUrl")
                    if not video_url:
                        continue
                        
                    # Check if this is another JSON endpoint to follow
                    if ("/media/hls/" in video_url or "/media/mp4/" in video_url) and video_url not in processed_urls:
                        urls_to_process.append(video_url)
                        processed_urls.add(video_url)
                        continue

                    quality = str(item.get("quality", "adaptive"))
                    if quality.isdigit():
                        quality = f"{quality}p"
                        
                    fmt = item.get("format", "hls")
                    if "/media/mp4/" in current_url:
                        fmt = "mp4"
                    
                    stream = {
                        "quality": quality,
                        "url": video_url,
                        "format": fmt
                    }
                    all_streams.append(stream)
                    
                    # If it's an adaptive HLS, try to resolve the master playlist right away
                    if quality == "adaptive" and ".m3u8" in video_url:
                        try:
                            resolved = await resolve_hls_master(video_url)
                            if resolved:
                                all_streams.extend(resolved)
                        except Exception:
                            pass
            except Exception:
                continue

        # Deduplicate and sort
        seen = set()
        unique_streams = []
        for s in all_streams:
            key = (s["quality"], s["url"])
            if key not in seen:
                unique_streams.append(s)
                seen.add(key)

        def _qval(s: dict) -> int:
            digits = "".join(filter(str.isdigit, s["quality"]))
            return int(digits) if digits else 0
        
        unique_streams.sort(key=_qval, reverse=True)

        # Default URL: Prefer HLS adaptive, then highest quality
        default_url = url
        for s in unique_streams:
            if s["quality"] == "adaptive":
                default_url = s["url"]
                break
        if default_url == url and unique_streams:
            default_url = unique_streams[0]["url"]

        video_data = {
            "streams": unique_streams,
            "default": default_url,
            "has_video": bool(unique_streams),
            "media_definitions": raw_media_definitions
        }
        
        return {
            "url": url,
            "title": "Tube8 Media Stream",
            "description": None,
            "thumbnail_url": None,
            "duration": None,
            "views": None,
            "uploader_name": "Tube8",
            "category": "Tube8",
            "tags": [],
            "video": video_data,
            "related_videos": [],
            "preview_url": None,
        }


async def resolve_hls_master(url: str) -> list[dict[str, Any]]:
    """
    Parses an HLS master playlist (.m3u8) into individual quality streams.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    }
    
    async with httpx.AsyncClient(follow_redirects=True, timeout=10.0) as client:
        resp = await client.get(url, headers=headers)
        if resp.status_code != 200:
            return []
            
        content = resp.text
        if "#EXT-X-STREAM-INF" not in content:
            return []
            
        streams = []
        lines = content.splitlines()
        
        base_url = url.rsplit("/", 1)[0] + "/"
        
        for i, line in enumerate(lines):
            line = line.strip()
            if line.startswith("#EXT-X-STREAM-INF:"):
                # Extract resolution or bandwidth
                quality = "adaptive"
                res_match = re.search(r"RESOLUTION=(\d+x\d+)", line)
                if res_match:
                    res = res_match.group(1)
                    height = res.split("x")[1]
                    quality = f"{height}p"
                else:
                    bw_match = re.search(r"BANDWIDTH=(\d+)", line)
                    if bw_match:
                        bw = int(bw_match.group(1))
                        # Rough mapping if resolution is missing
                        if bw > 5000000: quality = "1080p"
                        elif bw > 2500000: quality = "720p"
                        elif bw > 1000000: quality = "480p"
                        elif bw > 500000: quality = "360p"
                        else: quality = "240p"

                # Next line should be the URL
                if i + 1 < len(lines):
                    stream_url = lines[i+1].strip()
                    if not stream_url.startswith("http"):
                        if stream_url.startswith("/"):
                            # Absolute path on same host
                            parsed_root = url.split("/", 3)[:3]
                            root = "/".join(parsed_root)
                            stream_url = root + stream_url
                        else:
                            # Relative path
                            stream_url = base_url + stream_url
                    
                    streams.append({
                        "quality": quality,
                        "url": stream_url,
                        "format": "hls"
                    })
        
        # Sort by quality
        def _qval(s: dict) -> int:
            digits = "".join(filter(str.isdigit, s["quality"]))
            return int(digits) if digits else 0
        
        streams.sort(key=_qval, reverse=True)
        return streams


async def list_videos(base_url: str, page: int = 1, limit: int = 100) -> list[dict[str, Any]]:
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

    def _make_item(href: str, title: str, thumb: str | None, container) -> dict | None:
        """Build a list item dict given the resolved fields and a container element for metadata."""
        if not href:
            return None
        
        # Normalize URL for deduplication
        if not href.startswith("http"):
            href = "https://www.tube8.com" + ("/" if not href.startswith("/") else "") + href
        href = href.split("?")[0].rstrip("/") # Simple normalization
        
        if href in seen_hrefs:
            return None
        seen_hrefs.add(href)

        # Duration
        duration = "0:00"
        if container is not None:
            dur_el = container.select_one(".tm_video_duration, .video-duration, .duration, .video-duration-text")
            if dur_el:
                txt = dur_el.get_text(strip=True)
                if txt:
                    duration = txt

        # Views
        views = "0"
        if container is not None:
            v_el = container.select_one(".info-views, .views, .video_views, .video-views-text")
            if v_el:
                raw_views = v_el.get_text(strip=True).lower()
                v_match = re.search(r"(\d+[\d\.,]*[km]?)", raw_views)
                if v_match:
                    views = v_match.group(1).upper()
                elif raw_views.strip():
                    views = raw_views.replace("views", "").strip()

        # Uploader
        uploader = "Unknown"
        if container is not None:
            u_el = container.select_one(".author-title-text, .video-author-text, .username, .uploader")
            if not u_el:
                u_el = container.select_one('a[href*="/user/"], a[href*="/profiles/"]')
            
            if u_el:
                txt = u_el.get_text(strip=True)
                if txt:
                    uploader = txt

        return {
            "url": href,
            "title": title or "Unknown",
            "thumbnail_url": thumb,
            "duration": duration,
            "views": views,
            "uploader_name": uploader,
            "preview_url": thumb,
        }

    # ── Layout A: homepage – a.gtm-event-thumb-click / a.video-thumb ──────────
    for a in soup.select("a.gtm-event-thumb-click, a.video-thumb"):
        if len(items) >= limit:
            break
        try:
            href = a.get("href", "")
            thumb = None
            img = a.find("img")
            if img:
                thumb = img.get("data-src") or img.get("data-thumb_url") or img.get("src")

            # Container for metadata is usually a parent div (video-card or item)
            # The title often lives in a sibling but the container for _make_item should be the shared parent
            card = a.parent
            # Some layouts have a wrapper around the link and info
            if card and card.name != "div":
                card = card.parent
            
            title = ""
            title_el = card.select_one("a.video-title-text, .video-title a, .title a") if card else None
            if title_el:
                title = title_el.get("title") or title_el.get_text(strip=True)
            if not title:
                title = (img.get("alt") if img else None) or a.get("title") or a.get("data-label2") or ""

            item = _make_item(href, title, thumb, card)
            if item:
                items.append(item)
        except Exception:
            continue

    # ── Layout B: category / sorted pages – a.tm_video_link ───────────────────
    if not items:
        for a in soup.select("a.tm_video_link"):
            if len(items) >= limit:
                break
            try:
                href = a.get("href", "")
                thumb = None
                img = a.find("img")
                if img:
                    thumb = img.get("data-src") or img.get("data-thumb_url") or img.get("src")

                # Title is in img alt attribute or a video-title link
                card = a.parent
                if card and card.name != "div":
                    card = card.parent
                
                title = ""
                title_el = card.select_one(".video-title-text, .tm_video_title") if card else None
                if title_el:
                    title = title_el.get("title") or title_el.get_text(strip=True)
                if not title:
                    title = (img.get("alt") if img else None) or a.get("title") or ""

                item = _make_item(href, title, thumb, card)
                if item:
                    items.append(item)
            except Exception:
                continue

    return items[:limit]


