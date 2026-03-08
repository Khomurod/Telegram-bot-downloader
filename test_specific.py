import asyncio
from services.ytdlp_service import extract_info

async def main():
    url = "https://youtu.be/z1DHw3djzY8?si=MFlqWZ0myeSyEaHx"
    print("Testing URL:", url)
    info = await extract_info(url)
    if info:
        print("Success:")
        print("Title:", info.get('title'))
        print("Duration:", info.get('duration'))
    else:
        print("Failed to extract info")

if __name__ == "__main__":
    asyncio.run(main())
