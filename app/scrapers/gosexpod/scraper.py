import httpx
import re
import json
import os
from bs4 import BeautifulSoup
from typing import Any, Optional

BASE_URL = "https://www.gosexpod.com"

def get_categories() -> list[dict]:
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        json_path = os.path.join(current_dir, "categories.json")
        with open(json_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []

def can_handle(host: str) -> bool:
    return "gosexpod.com" in host.lower()

async def fetch_html(url: str) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Referer": BASE_URL + "/",
    }
    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0, headers=headers) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.text

def _make_absolute(src: str) -> str:
    """Convert relative URL to absolute."""
    if not src:
        return ""
    if src.startswith("http"):
        return src
    return BASE_URL + src if src.startswith("/") else src

async def scrape(url: str) -> dict:
    html = await fetch_html(url)
    soup = BeautifulSoup(html, 'lxml')

    # Title
    title_el = soup.select_one('h1') or soup.select_one('.video-title')
    title = title_el.get_text(strip=True) if title_el else ""

    # Thumbnail from og:image meta
    thumbnail = ""
    meta_img = soup.find('meta', property='og:image')
    if meta_img:
        thumbnail = _make_absolute(meta_img.get('content', ''))

    # Extract video source - Method 1: <video> tag
    video_url = None
    video_tag = soup.find('video')
    if video_tag:
        source = video_tag.find('source')
        video_url = source.get('src') if source else video_tag.get('src')
        if video_url:
            video_url = _make_absolute(video_url)

    # Method 2: Scripts - look for known patterns
    if not video_url:
        scripts = soup.find_all('script')
        for script in scripts:
            content = script.string or ""
            # Look for video_url, hls, or file patterns
            for pattern in [
                r'["\']?video_url["\']?\s*[=:]\s*["\']([^"\']+)["\']',
                r'["\']?hls["\']?\s*[=:]\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
                r'["\']?file["\']?\s*[=:]\s*["\']([^"\']+\.(?:mp4|m3u8)[^"\']*)["\']',
                r'source\s*=\s*["\']([^"\']+\.(?:mp4|m3u8)[^"\']*)["\']',
            ]:
                m = re.search(pattern, content, re.IGNORECASE)
                if m:
                    video_url = _make_absolute(m.group(1))
                    break
            if video_url:
                break

    # Method 3: iframe player
    hls_url = None
    if not video_url:
        iframe = soup.find('iframe', src=re.compile(r'player|embed', re.I))
        if iframe:
            iframe_src = iframe.get('src', '')
            if iframe_src:
                # If it's a gosexpod player URL, it may contain encoded video info
                video_url = _make_absolute(iframe_src)

    is_hls = video_url and '.m3u8' in video_url
    return {
        "url": url,
        "title": title,
        "thumbnail_url": thumbnail,
        "duration": None,
        "views": None,
        "uploader_name": "Gosexpod",
        "video": {
            "streams": [] if is_hls else ([{"quality": "720p", "url": video_url, "format": "mp4"}] if video_url else []),
            "hls": video_url if is_hls else None,
            "default": video_url,
            "has_video": video_url is not None
        }
    }

async def list_videos(base_url: str, page: int = 1, limit: int = 20) -> list[dict]:
    """List videos from Gosexpod.
    
    base_url can be:
    - A category URL like /categories/indexcat.php?category=milf
    - The main listing URL like /indexv2.php?righttab=mostrecent
    - A search URL
    - Defaults to latest videos if base_url is the site root
    """
    # Normalize the base_url
    if not base_url or base_url in (BASE_URL, BASE_URL + "/", "/"):
        listing_url = f"{BASE_URL}/indexv2.php?righttab=mostrecent&page={page}"
    elif base_url.startswith("http"):
        # Full URL - just append pagination
        if "?" in base_url:
            listing_url = f"{base_url}&page={page}"
        else:
            listing_url = f"{base_url}?page={page}"
    else:
        # Relative path
        full_url = BASE_URL + base_url if base_url.startswith("/") else BASE_URL + "/" + base_url
        if "?" in full_url:
            listing_url = f"{full_url}&page={page}"
        else:
            listing_url = f"{full_url}?page={page}"

    html = await fetch_html(listing_url)
    soup = BeautifulSoup(html, 'lxml')
    videos = []

    # Selectors: a.thumbs__item (confirmed from HTML analysis)
    cards = soup.select('a.thumbs__item')
    for card in cards:
        href = card.get('href')
        if not href:
            continue

        # Handle thumbnail - supports both eager and lazy loading
        img_el = card.select_one('.thumbs__img-holder img')
        if img_el:
            # Lazy-loaded images use data-src; early/eager ones use src with real path
            thumb = img_el.get('data-src') or img_el.get('src', '')
            # Skip placeholder images
            if 'include/320x180.png' in thumb:
                thumb = img_el.get('data-src', '') or ''
            thumb = _make_absolute(thumb)
        else:
            thumb = ""

        # Title
        title_el = card.select_one('p.thumbs__info_text')
        title = title_el.get_text(strip=True) if title_el else ""

        # Duration (in badge on right side)
        duration_el = card.select_one('.thumbs__bage_right .thumbs__bage_text')
        duration = duration_el.get_text(strip=True) if duration_el else None

        # Views (in badge on left side)
        views_el = card.select_one('.thumbs__bage_left .thumbs__bage_text')
        views_text = views_el.get_text(strip=True) if views_el else None
        # Keep as string to match ListItem.views: Optional[str] schema
        views = views_text  # e.g. "24 views"

        video_url = BASE_URL + href if href.startswith('/') else href

        videos.append({
            "url": video_url,
            "title": title,
            "thumbnail_url": thumb,
            "duration": duration,
            "views": views,
            "uploader_name": "Gosexpod"
        })

        if len(videos) >= limit:
            break

    return videos
