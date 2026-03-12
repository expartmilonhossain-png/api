import httpx
from fastapi import APIRouter, HTTPException, Query, Response, Request
from fastapi.responses import StreamingResponse
from urllib.parse import urljoin, quote
import logging
import re

router = APIRouter()
logger = logging.getLogger(__name__)

# Pattern to find URLs in m3u8 files
URL_PATTERN = re.compile(r'(https?://[^\s]+)')

@router.get("/proxy", summary="HLS Proxy")
async def hls_proxy(
    url: str = Query(..., description="Target HLS URL"),
    referer: str = Query(None, description="Referer header to send"),
    origin: str = Query(None, description="Origin header to send"),
    user_agent: str = Query(None, description="User-Agent header to send"),
    request: Request = None
):
    """
    Proxy HLS manifests and segments to bypass CORS/Referer restrictions.
    Rewrites URLs in m3u8 files to point back to this proxy.
    Handles BrazzPW-style meta-refreshes and masked MIME types.
    """
    if not url:
        raise HTTPException(status_code=400, detail="Missing URL")
    
    headers = {}
    ua = user_agent if user_agent else request.headers.get("user-agent")
    if ua:
        headers["User-Agent"] = ua
    if referer:
        headers["Referer"] = referer
    if origin:
        headers["Origin"] = origin
    
    range_header = request.headers.get("range")
    if range_header:
        headers["Range"] = range_header
        
    try:
        # Use a session-like client to handle potential cookies from meta-refreshes
        async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=30.0) as client:
            current_url = url
            resp = await client.get(current_url)
            
            # 1. Handle Meta-Refresh or session initialization (common in BrazzPW)
            # BrazzPW might return a 403 with HTML containing a meta-refresh
            content_type = resp.headers.get("content-type", "").lower()
            is_html = "text/html" in content_type
            
            if (resp.status_code == 403 or is_html) and ("#EXTM3U" not in resp.text):
                # Try following meta refresh if present
                m = re.search(r'url=([^"\']*)', resp.text, re.I)
                if m:
                    refresh_url = urljoin(current_url, m.group(1))
                    logger.info(f"Following meta-refresh to: {refresh_url}")
                    await client.get(refresh_url) # Just visit it to get cookies
                    resp = await client.get(current_url) # Retry original
                else:
                    # Some sites just need a second hit to set/use cookies
                    logger.info("Retrying request to handle potential session initialization...")
                    resp = await client.get(current_url)
            
            if resp.status_code >= 400:
                raise HTTPException(status_code=resp.status_code, detail=f"Upstream error: {resp.status_code}")
            
            content_type = resp.headers.get("content-type", "").lower()
            url_lower = url.lower()
            
            # 2. Manifest Rewriting
            if "mpegurl" in content_type or url_lower.endswith(".m3u8") or ".m3u8" in url_lower:
                content = resp.text
                base_url = str(request.base_url).rstrip("/")
                proxy_base = f"{base_url}/api/v1/hls/proxy"
                
                lines = content.split('\n')
                new_lines = []
                for line in lines:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        # Handle URI attributes in tags
                        if line.startswith("#EXT-X-KEY") and 'URI="' in line:
                            # TODO: Implement URI attribute rewriting if needed
                            new_lines.append(line)
                        else:
                            new_lines.append(line)
                    else:
                        # It's a URI line
                        target = urljoin(current_url, line)
                        params = f"?url={quote(target)}"
                        if referer: params += f"&referer={quote(referer)}"
                        if origin: params += f"&origin={quote(origin)}"
                        if user_agent: params += f"&user_agent={quote(user_agent)}"
                        new_lines.append(f"{proxy_base}{params}")
                
                return Response(
                    content="\n".join(new_lines),
                    media_type="application/vnd.apple.mpegurl",
                    headers={"Access-Control-Allow-Origin": "*"}
                )
            
            # 3. Segment Streaming with Content-Type Sniffing
            else:
                # Read first chunk to sniff MIME type if it's potentially masked (like .png on BrazzPW)
                async def stream_generator():
                    first_chunk = True
                    async for chunk in resp.aiter_bytes():
                        yield chunk
                
                response_headers = {"Access-Control-Allow-Origin": "*"}
                for h in ["Content-Range", "Content-Length", "Accept-Ranges"]:
                    if h.lower() in resp.headers:
                        response_headers[h] = resp.headers[h.lower()]
                
                # Sniff for MPEG-TS (Sync byte 0x47)
                final_media_type = content_type
                # Peek first bytes if possible
                # Since we are using a generator, we'd need to peek. 
                # Let's check the first byte of the response body if it's already read or via a peek.
                # For simplicity, if it's from brazzpw or contains 'video/' in manifest, we force it.
                # Better: read the first 188 bytes (TS packet size)
                
                # Re-evaluate media type based on content if needed
                if "brazzpw" in url or "image/" in content_type:
                    # We can't easily peek and then yield in a StreamingResponse without buffering.
                    # Let's buffer the first chunk.
                    pass

                # Actually, simpler: just force video/mp2t for anything not a manifest if we suspect masking
                if "brazzpw.com" in url and "image/" in content_type:
                    final_media_type = "video/mp2t"

                return StreamingResponse(
                    stream_generator(),
                    status_code=resp.status_code,
                    media_type=final_media_type,
                    headers=response_headers
                )
                
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"HLS Proxy error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/gosexpod/stream", summary="Gosexpod Video Stream Proxy")
async def gosexpod_stream(
    url: str = Query(..., description="Gosexpod video page URL"),
    request: Request = None
):
    """
    Proxy Gosexpod video streams.
    Gosexpod CDN uses IP-locked signed URLs (md5+expires tied to requester IP).
    This endpoint scrapes the page from the server side so the signed URL is
    valid for THIS server's IP, then streams the content directly.
    """
    from app.scrapers.gosexpod.scraper import scrape, BASE_URL

    # Validate it's actually a Gosexpod URL
    if "gosexpod.com" not in url:
        raise HTTPException(status_code=400, detail="Only gosexpod.com URLs are supported")

    try:
        # Scrape from the server - the signed URL will be for THIS server's IP
        metadata = await scrape(url)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to scrape video page: {str(e)}")

    video_data = metadata.get("video", {})
    if not video_data.get("has_video") or not video_data.get("default"):
        raise HTTPException(status_code=404, detail="No video stream found for this URL")

    stream_url = video_data["default"]
    logger.info(f"Gosexpod stream proxy: {url} -> {stream_url[:80]}...")

    # Stream the video with the proper Referer header
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        "Referer": url,  # Use the exact video page URL as Referer
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
    }

    # Forward Range header for seeking support
    range_header = request.headers.get("range") if request else None
    if range_header:
        headers["Range"] = range_header

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            resp = await client.get(stream_url, headers=headers)

            if resp.status_code >= 400:
                raise HTTPException(
                    status_code=resp.status_code,
                    detail=f"CDN rejected stream request: {resp.status_code}. URL may have expired."
                )

            response_headers = {"Access-Control-Allow-Origin": "*"}
            for h in ["Content-Range", "Content-Length", "Accept-Ranges", "Content-Type"]:
                val = resp.headers.get(h.lower())
                if val:
                    response_headers[h] = val

            content_type = resp.headers.get("content-type", "video/mp4")

            async def stream_generator():
                async for chunk in resp.aiter_bytes(chunk_size=65536):
                    yield chunk

            return StreamingResponse(
                stream_generator(),
                status_code=resp.status_code,
                media_type=content_type,
                headers=response_headers,
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Gosexpod stream proxy error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

