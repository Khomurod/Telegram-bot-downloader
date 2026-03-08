import asyncio
from services.ytdlp_service import download_media

async def main():
    url = "https://youtu.be/z1DHw3djzY8?si=MFlqWZ0myeSyEaHx"
    print("Testing download for URL:", url)
    result = await download_media(url, "1080p")
    print("Result:", result)

if __name__ == "__main__":
    asyncio.run(main())
