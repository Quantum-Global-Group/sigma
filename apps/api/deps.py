"""
Common FastAPI dependency re-exports so routers can import from a single place.
"""

from cache.redis import get_redis as get_redis
from db.connection import get_db as get_db
