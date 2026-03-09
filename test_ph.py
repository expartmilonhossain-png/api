import asyncio, httpx
from bs4 import BeautifulSoup
async def t():
    from app.core.pool import pool
    session = await pool.get_session()
    async with session.get('https://pornhat.com') as r:
        html = await r.text()
    soup = BeautifulSoup(html, 'lxml')
    cards = soup.select('div.item.thumb-bl-video, div.thumb-bl-video, .video-box, .item')
    if cards:
        card = cards[1]
        for a in card.select('a'):
             print(f'HREF: {a.get("href")} TEXT: {a.get_text(strip=True)}')
asyncio.run(t())
