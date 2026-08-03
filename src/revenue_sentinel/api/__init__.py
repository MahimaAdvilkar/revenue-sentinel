"""Layer 7 -- thin FastAPI routers.

Transport concerns only: parse, authenticate, delegate, serialize (boundary R2).
Domain logic lives in services and is importable without an HTTP server.
"""
