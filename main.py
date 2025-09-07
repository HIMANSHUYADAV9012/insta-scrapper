import asyncio
import time
import json
import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from contextlib import asynccontextmanager
import io

# ✅ In-memory cache
CACHE = {}
CACHE_TTL = 240  # 4 minutes

# ✅ Async httpx client
async_client = httpx.AsyncClient(
    headers={
        "x-ig-app-id": "936619743392459",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/62.0.3202.94 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept": "*/*",
    },
    timeout=10.0,
)

# ✅ Background cache cleaner
async def cache_cleaner():
    while True:
        now = time.time()
        expired_keys = [k for k, v in CACHE.items() if v["expiry"] < now]
        for k in expired_keys:
            CACHE.pop(k, None)
        await asyncio.sleep(60)

# ✅ Lifespan event handler
@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(cache_cleaner())
    yield
    await async_client.aclose()

# ✅ Create app with lifespan
app = FastAPI(lifespan=lifespan)

# ✅ CORS config
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For development only
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)

# ================= API Logic =================
async def scrape_user(username: str):
    username = username.lower()
    
    cached = CACHE.get(username)
    if cached and cached["expiry"] > time.time():
        return cached["data"]

    url = f"https://i.instagram.com/api/v1/users/web_profile_info/?username={username}"

    try:
        result = await async_client.get(url)
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Network error: {str(e)}")

    if result.status_code == 404:
        raise HTTPException(status_code=404, detail="User not found on Instagram")
    elif result.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Instagram API returned {result.status_code}",
        )

    try:
        data = result.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Invalid JSON response from Instagram")

    user = data.get("data", {}).get("user")
    if not user:
        raise HTTPException(status_code=404, detail="User data not found in response")

    user_data = {
        "username": user.get("username"),
        # Backend proxy URL instead of direct Instagram URL
        "profile_pic": user.get("profile_pic_url_hd"),

        "followers": user.get("edge_followed_by", {}).get("count"),
        "following": user.get("edge_follow", {}).get("count"),
        "post_count": user.get("edge_owner_to_timeline_media", {}).get("count"),
        "bio": user.get("biography"),
    }

    CACHE[username] = {"data": user_data, "expiry": time.time() + CACHE_TTL}
    return user_data


@app.get("/scrape/{username}")
async def get_user(username: str):
    return await scrape_user(username)

# ================== Proxy Image Endpoint ==================
@app.get("/proxy-image/")
async def proxy_image(url: str = Query(..., description="Image URL to proxy")):
    """
    Fetch an image via backend to bypass CORS issues
    """
    try:
        resp = await async_client.get(url)
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail="Failed to fetch image")
        return StreamingResponse(io.BytesIO(resp.content), media_type="image/jpeg")
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Network error: {str(e)}")

# Health check endpoint
@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": time.time()}
