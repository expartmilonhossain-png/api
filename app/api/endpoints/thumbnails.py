import httpx
from fastapi import APIRouter, HTTPException, Query, Response, Request
from fastapi.responses import StreamingResponse
from urllib.parse import quote
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/proxy", summary="Thumbnail Proxy")
async def thumbnail_proxy(
    url: str = Query(..., description="Target Thumbnail URL"),
    referer: str = Query(None, description="Referer header to send"),
    user_agent: str = Query(None, description="User-Agent header to send"),
    request: Request = None
):
    """
    Proxy thumbnail images to bypass network or Referer restrictions.
    """
    if not url:
        raise HTTPException(status_code=400, detail="Missing URL")
    
    if "hqporner.com" not in url.lower():
        raise HTTPException(status_code=403, detail="Only HQPorner thumbnails are allowed")
    
    # Headers to send to upstream
    headers = {}
    
    # Forward User-Agent from request if available, or allow override via query
    ua = user_agent if user_agent else request.headers.get("user-agent")
    if ua:
        headers["User-Agent"] = ua
        
    if referer:
        headers["Referer"] = referer
    else:
        headers["Referer"] = "https://hqporner.com/"

    try:
        # Use a single-use client for simplicity, though a pooled one is better for high volume
        async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=15.0) as client:
            resp = await client.get(url)
            
            if resp.status_code >= 400:
                logger.warning(f"Thumbnail proxy upstream error {resp.status_code} for {url}")
                raise HTTPException(status_code=resp.status_code, detail=f"Upstream returned {resp.status_code}")
            
            content_type = resp.headers.get("content-type", "image/jpeg")
            
            # Forward the image content
            return Response(
                content=resp.content,
                media_type=content_type,
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Cache-Control": "public, max-age=86400",  # 24 hour cache
                    "X-Proxy-Origin": "AppHub-Thumbnail-Proxy"
                }
            )
                
    except httpx.RequestError as e:
        logger.error(f"Thumbnail Proxy request error: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to connect to upstream: {str(e)}")
    except Exception as e:
        logger.error(f"Thumbnail Proxy unexpected error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

def wrap_thumbnail_url(url: str, api_base_url: str) -> str:
    """Helper to wrap HQPorner thumbnails in the proxy URL."""
    if not url or "hqporner.com" not in url.lower():
        return url
    
    # If already proxied, don't double wrap
    if "/thumbnails/proxy?url=" in url:
        return url
        
    return f"{api_base_url.rstrip('/')}/api/v1/thumbnails/proxy?url={quote(url)}"
