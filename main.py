import asyncio
import time
import json
import httpx
import random
import io
import logging
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from contextlib import asynccontextmanager

# ✅ Rate Limiting
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# ================= Config =================
CACHE = {}
CACHE_TTL = 240  # 4 minutes

TELEGRAM_BOT_TOKEN = "7652042264:AAGc6DQ-OkJ8PaBKJnc_NkcCseIwmfbHD-c"
TELEGRAM_CHAT_ID = "5029478739"

# ✅ Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("instagram-scraper")

# ✅ Async httpx client with connection pooling
async_client = httpx.AsyncClient(
    timeout=10.0,
    limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
    follow_redirects=True,
)

# ✅ Header pool
HEADERS_POOL = [
    {
        "x-ig-app-id": "936619743392459",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/123.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept": "*/*",
    },
    {
        "x-ig-app-id": "936619743392459",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) "
                      "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                      "Version/17.4 Safari/605.1.15",
        "Accept-Language": "en-GB,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept": "*/*",
    },
    {
        "x-ig-app-id": "936619743392459",
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/121.0.6167.86 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept": "*/*",
    },
    {
        "x-ig-app-id": "936619743392459",
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_3 like Mac OS X) "
                      "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                      "Version/17.3 Mobile/15E148 Safari/604.1",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept": "*/*",
    },
    {
        "x-ig-app-id": "936619743392459",
        "User-Agent": "Mozilla/5.0 (Linux; Android 14; Pixel 7 Pro) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/122.0.6261.105 Mobile Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept": "*/*",
    },
    {
        "x-ig-app-id": "936619743392459",
        "User-Agent": "Mozilla/5.0 (Linux; Android 14; Pixel 6) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/123.0.0.0 Mobile Safari/537.36 "
                      "Instagram 320.0.0.23.111 Android",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept": "*/*",
    },
]

# ================= Utils =================
def get_random_headers():
    return random.choice(HEADERS_POOL)

async def cache_cleaner():
    """Background task to clean expired cache"""
    while True:
        now = time.time()
        expired_keys = [k for k, v in CACHE.items() if v["expiry"] < now]
        for k in expired_keys:
            CACHE.pop(k, None)
        await asyncio.sleep(60)

async def notify_telegram(message: str):
    """Send Telegram notification"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
        async with httpx.AsyncClient() as client:
            await client.post(url, data=payload)
    except Exception as e:
        logger.error(f"Failed to send Telegram notification: {e}")

async def handle_error(status_code: int, detail: str, notify_msg: str = None):
    """Raise HTTPException and optionally notify Telegram"""
    if notify_msg:
        await notify_telegram(notify_msg)
    raise HTTPException(status_code=status_code, detail=detail)

# ================= Lifespan =================
@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(cache_cleaner())
    yield
    await async_client.aclose()

# ================= App Init =================
app = FastAPI(lifespan=lifespan)

# ✅ Rate Limiter
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

# ✅ CORS config
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For development only
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)

# ================= Error Handlers =================
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle FastAPI HTTPExceptions and notify Telegram"""
    await notify_telegram(
        f"⚠️ HTTPException\n"
        f"Status: {exc.status_code}\n"
        f"Detail: {exc.detail}\n"
        f"Path: {request.url}"
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": True,
            "status_code": exc.status_code,
            "detail": exc.detail,
            "path": str(request.url),
            "timestamp": time.time(),
        },
    )

@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    """Handle rate limit errors and notify Telegram"""
    await notify_telegram(
        f"🚫 Rate Limit Exceeded\n"
        f"Client: {request.client.host}\n"
        f"Path: {request.url}"
    )
    return JSONResponse(
        status_code=429,
        content={
            "error": True,
            "status_code": 429,
            "detail": "Rate limit exceeded. Try again later.",
            "path": str(request.url),
            "timestamp": time.time(),
        },
    )

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch-all handler for unexpected exceptions"""
    logger.error(f"Unexpected error: {exc}", exc_info=True)
    await notify_telegram(
        f"🔥 Unhandled Exception\n"
        f"Type: {type(exc).__name__}\n"
        f"Error: {str(exc)}\n"
        f"Path: {request.url}"
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": True,
            "status_code": 500,
            "detail": "Internal Server Error",
            "path": str(request.url),
            "timestamp": time.time(),
        },
    )

# ================= API Logic =================
async def scrape_user(username: str):
    username = username.lower()

    cached = CACHE.get(username)
    if cached and cached["expiry"] > time.time():
        return cached["data"]

    url = f"https://i.instagram.com/api/v1/users/web_profile_info/?username={username}"

    retries = 3
    result = None
    for attempt in range(retries):
        try:
            result = await async_client.get(url, headers=get_random_headers())
            if result.status_code == 200:
                break
            elif result.status_code in (401, 429, 502):
                await asyncio.sleep((2 ** attempt) + random.uniform(0, 1))
                continue
            else:
                await handle_error(
                    status_code=result.status_code,
                    detail=f"Instagram API returned {result.status_code}",
                    notify_msg=f"Instagram API error for {username}: {result.status_code}"
                )
        except httpx.RequestError as e:
            if attempt == retries - 1:
                await handle_error(
                    status_code=502,
                    detail=f"Network error: {str(e)}",
                    notify_msg=f"Network error while scraping {username}: {str(e)}"
                )
            await asyncio.sleep((2 ** attempt) + random.uniform(0, 1))

    if not result or result.status_code != 200:
        await handle_error(
            status_code=502,
            detail="Failed after retries",
            notify_msg=f"Failed to scrape {username} after {retries} retries"
        )

    try:
        data = result.json()
    except json.JSONDecodeError:
        await handle_error(
            status_code=500,
            detail="Invalid JSON response from Instagram",
            notify_msg=f"Invalid JSON response for {username}"
        )

    user = data.get("data", {}).get("user")
    if not user:
        await handle_error(
            status_code=404,
            detail="User data not found in response",
            notify_msg=f"User data not found in response for {username}"
        )

    user_data = {
        "username": user.get("username"),
        "profile_pic": user.get("profile_pic_url_hd"),
        "followers": user.get("edge_followed_by", {}).get("count"),
        "following": user.get("edge_follow", {}).get("count"),
        "post_count": user.get("edge_owner_to_timeline_media", {}).get("count"),
        "bio": user.get("biography"),
    }

    CACHE[username] = {"data": user_data, "expiry": time.time() + CACHE_TTL}
    return user_data

# ================= Routes =================
@app.get("/scrape/{username}")
@limiter.limit("10/10minute")  # 🔒 10 requests per 10 minutes per IP
async def get_user(username: str, request: Request):
    return await scrape_user(username)

@app.get("/proxy-image/")
@limiter.limit("10/10minute")
async def proxy_image(request: Request, url: str = Query(..., description="Image URL to proxy")):
    try:
        resp = await async_client.get(url)
        if resp.status_code != 200:
            await handle_error(
                status_code=resp.status_code,
                detail="Failed to fetch image",
                notify_msg=f"Image proxy failed for URL: {url}, status: {resp.status_code}"
            )
        return StreamingResponse(
            io.BytesIO(resp.content),
            media_type=resp.headers.get("content-type", "image/jpeg")
        )
    except httpx.RequestError as e:
        await handle_error(
            status_code=502,
            detail=f"Network error: {str(e)}",
            notify_msg=f"Image proxy network error for URL: {url}, error: {str(e)}"
        )

@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": time.time()}
