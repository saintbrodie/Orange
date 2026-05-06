import httpx
import asyncio
from typing import Optional, List, Dict

from app.core.config import get_comfy_servers

# Global tracker for active requests sent by this Orange instance
# This prevents race conditions when multiple requests arrive simultaneously
active_requests: Dict[str, int] = {}

async def get_backend_queue_size(url: str) -> float:
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            res = await client.get(f"{url}/queue")
            if res.status_code == 200:
                data = res.json()
                pending = data.get("queue_pending", [])
                running = data.get("queue_running", [])
                return float(len(pending) + len(running))
    except Exception:
        pass
    return float('inf')

async def get_best_backend(exclude_urls: List[str] = None) -> Optional[str]:
    servers = get_comfy_servers()
    if exclude_urls:
        servers = [s for s in servers if s.get("url") not in exclude_urls]
        
    if not servers:
        return None
        
    # Query all queue sizes concurrently
    tasks = [get_backend_queue_size(s.get("url")) for s in servers]
    queue_sizes = await asyncio.gather(*tasks)
    
    best_server = None
    min_score = float('inf')
    
    for i, s in enumerate(servers):
        url = s.get("url")
        q_size = queue_sizes[i]
        if q_size == float('inf'):
            continue
            
        # Add in-flight requests that Orange has sent but haven't been confirmed in the backend queue yet
        in_flight = active_requests.get(url, 0)
        effective_q_size = q_size + in_flight
        
        priority = int(s.get("priority", 1))
        # Priority-based score: Effective queue size is primary, priority breaks ties.
        score = (effective_q_size * 1000) + priority
        
        if score < min_score:
            min_score = score
            best_server = url
            
    if not best_server:
        # Fallback
        return servers[0].get("url")
        
    return best_server

def increment_active(url: str):
    active_requests[url] = active_requests.get(url, 0) + 1

def decrement_active(url: str):
    if url in active_requests:
        active_requests[url] = max(0, active_requests[url] - 1)
