import asyncio
from datetime import datetime, timedelta

# In-memory rate limiting and queueing
user_download_timestamps = {}
MAX_CONCURRENT_DOWNLOADS = 2
SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
QUEUE_STATE_LOCK = asyncio.Lock()
waiting_users = 0

def get_rate_limit_retry_after_seconds(user_id: int) -> int:
    """Return how many seconds until the user can download again (0 if allowed)."""
    now = datetime.now()
    timestamps = user_download_timestamps.get(user_id, [])
    timestamps = [t for t in timestamps if now - t < timedelta(minutes=1)]
    user_download_timestamps[user_id] = timestamps

    if len(timestamps) < 5:
        return 0

    oldest = min(timestamps)
    retry_after = int((oldest + timedelta(minutes=1) - now).total_seconds())
    return max(1, retry_after)

def check_rate_limit(user_id: int) -> bool:
    """Check if the user has reached the 5 downloads / minute limit."""
    return get_rate_limit_retry_after_seconds(user_id) > 0

def record_download(user_id: int):
    """Record a download action to affect the rate limit."""
    if user_id not in user_download_timestamps:
        user_download_timestamps[user_id] = []
    user_download_timestamps[user_id].append(datetime.now())

async def acquire_lock(send_wait_message=None):
    """
    Acquire a download slot. 
    If the queue is full, calls send_wait_message(position) and then waits.
    """
    global waiting_users
    
    position = 0

    async with QUEUE_STATE_LOCK:
        if SEMAPHORE.locked():
            waiting_users += 1
            position = waiting_users

    if position:
        if send_wait_message:
            await send_wait_message(position)

        await SEMAPHORE.acquire()

        async with QUEUE_STATE_LOCK:
            waiting_users = max(0, waiting_users - 1)

        return position

    # We can instantly acquire.
    await SEMAPHORE.acquire()
    return 0

def release_lock():
    """Release a download slot."""
    SEMAPHORE.release()
