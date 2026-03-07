import asyncio
from datetime import datetime, timedelta

# In-memory rate limiting and queueing
user_download_timestamps = {}
MAX_CONCURRENT_DOWNLOADS = 2
SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
waiting_users = 0

def check_rate_limit(user_id: int) -> bool:
    """Check if the user has reached the 5 downloads / minute limit."""
    now = datetime.now()
    if user_id not in user_download_timestamps:
        user_download_timestamps[user_id] = []
    
    # Prune timestamps older than 1 minute
    user_download_timestamps[user_id] = [
        t for t in user_download_timestamps[user_id] 
        if now - t < timedelta(minutes=1)
    ]
    
    if len(user_download_timestamps[user_id]) >= 5:
        return True
    return False

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
    
    # If semaphore is fully acquired (locked), we need to queue
    if SEMAPHORE.locked():
        waiting_users += 1
        position = waiting_users
        
        if send_wait_message:
            await send_wait_message(position)
            
        await SEMAPHORE.acquire()
        waiting_users -= 1
        return position
    else:
        # We can instantly acquire
        await SEMAPHORE.acquire()
        return 0

def release_lock():
    """Release a download slot."""
    SEMAPHORE.release()
