import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routers import api_router, ws_router
from src.core.config import get_settings

logging.basicConfig(level=logging.INFO)

openapi_tags = [
    {"name": "auth", "description": "Signup/login and current user."},
    {"name": "recipes", "description": "Browse, search, view, create, and edit recipes."},
    {"name": "favorites", "description": "Favorite recipes."},
    {"name": "shopping-list", "description": "Generate and manage shopping lists."},
    {"name": "meal-plans", "description": "Meal planning calendar entries."},
    {"name": "realtime", "description": "WebSocket endpoints for real-time updates."},
]

app = FastAPI(
    title="Recipe Hub API",
    description=(
        "Backend API for Recipe Hub (recipes, favorites, shopping lists, meal planning).\n\n"
        "WebSocket usage:\n"
        "- Connect to `/ws/updates` to receive JSON events for created/updated recipes and other updates."
    ),
    version="0.2.0",
    openapi_tags=openapi_tags,
)

settings = get_settings()

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")
app.include_router(ws_router, tags=["realtime"])


@app.get("/", tags=["health"], summary="Health check")
def health_check():
    """Health check endpoint.

    Returns:
        dict: { "message": "Healthy" }
    """
    return {"message": "Healthy"}


@app.get("/docs/websocket", tags=["realtime"], summary="WebSocket usage help")
def websocket_help():
    """WebSocket usage instructions for clients."""
    return {
        "endpoint": "/ws/updates",
        "example": "const ws = new WebSocket('wss://<host>/ws/updates'); ws.onmessage = (e) => console.log(e.data);",
        "events": ["recipe.created", "recipe.updated", "favorite.toggled", "shopping_list.generated", "meal_plan.created", "meal_plan.updated"],
    }
