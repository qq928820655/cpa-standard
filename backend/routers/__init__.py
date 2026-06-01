"""
路由模块
"""
from .admin import router as admin_router
from .proxy import router as proxy_router
from .stats import router as stats_router
from .auth import router as auth_router
from .openai_plus import router as openai_plus_router

__all__ = ["admin_router", "proxy_router", "stats_router", "auth_router", "openai_plus_router"]
