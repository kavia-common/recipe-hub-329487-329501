from __future__ import annotations

import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.schemas import (
    AuthLoginRequest,
    AuthSignupRequest,
    AuthTokenResponse,
    ErrorResponse,
    FavoriteToggleResponse,
    MealPlanPublic,
    MealPlanUpsertRequest,
    RecipeCreateRequest,
    RecipeDetail,
    RecipeSummary,
    RecipeUpdateRequest,
    ShoppingListGenerateRequest,
    ShoppingListPublic,
    UserPublic,
)
from src.core.auth import (
    AuthenticatedUser,
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from src.core.flows import (
    ListRecipesRequest,
    get_or_create_shopping_list_flow,
    get_recipe_flow,
    list_recipes_flow,
    toggle_favorite_flow,
)
from src.db.models import MealPlan, Recipe, User
from src.db.session import get_db

logger = logging.getLogger("recipe_backend.api")

api_router = APIRouter()
ws_router = APIRouter()


class _WsHub:
    """In-memory WebSocket connection hub (single-process).

    Contract:
      - register/unregister websocket connections
      - broadcast event dict to all clients
    """

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.discard(ws)

    async def broadcast(self, event: dict) -> None:
        dead: list[WebSocket] = []
        for ws in list(self._connections):
            try:
                await ws.send_json(event)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


_WS_HUB = _WsHub()


@api_router.post(
    "/auth/signup",
    response_model=AuthTokenResponse,
    responses={400: {"model": ErrorResponse}},
    tags=["auth"],
    summary="Sign up",
    description="Create a new user account and return an access token.",
)
def signup(payload: AuthSignupRequest, db: Session = Depends(get_db)) -> AuthTokenResponse:
    existing = db.scalar(select(User).where(User.email == payload.email))
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        email=payload.email,
        display_name=payload.display_name,
        password_hash=hash_password(payload.password),
        is_admin=False,
    )
    db.add(user)
    db.flush()

    token = create_access_token(user.id)
    return AuthTokenResponse(access_token=token, user=UserPublic(
        id=user.id, email=user.email, display_name=user.display_name, is_admin=user.is_admin
    ))


@api_router.post(
    "/auth/login",
    response_model=AuthTokenResponse,
    responses={401: {"model": ErrorResponse}},
    tags=["auth"],
    summary="Login",
    description="Login with email/password and return an access token.",
)
def login(payload: AuthLoginRequest, db: Session = Depends(get_db)) -> AuthTokenResponse:
    user = db.scalar(select(User).where(User.email == payload.email))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token(user.id)
    return AuthTokenResponse(access_token=token, user=UserPublic(
        id=user.id, email=user.email, display_name=user.display_name, is_admin=user.is_admin
    ))


@api_router.get(
    "/me",
    response_model=UserPublic,
    tags=["auth"],
    summary="Current user",
    description="Return the current authenticated user.",
)
def me(user: AuthenticatedUser = Depends(get_current_user)) -> UserPublic:
    return user.to_public()


@api_router.get(
    "/recipes",
    response_model=list[RecipeSummary],
    tags=["recipes"],
    summary="List recipes",
    description="List recipes with search and filters.",
)
def list_recipes(
    q: str = "",
    cuisine: str = "",
    diet: str = "",
    max_time: int | None = None,
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> list[RecipeSummary]:
    items = list_recipes_flow(
        db,
        ListRecipesRequest(
            query=q,
            cuisine=cuisine,
            diet=diet,
            max_total_time_minutes=max_time,
            limit=min(max(limit, 1), 100),
            offset=max(offset, 0),
        ),
    )
    return [
        RecipeSummary(
            id=i.id,
            title=i.title,
            description=i.description,
            cuisine=i.cuisine,
            diet=i.diet,
            total_time_minutes=i.total_time_minutes,
            image_url=i.image_url,
            average_rating=i.average_rating,
            favorites_count=i.favorites_count,
        )
        for i in items
    ]


@api_router.post(
    "/recipes",
    response_model=RecipeDetail,
    tags=["recipes"],
    summary="Create recipe (demo admin-lite)",
    description="Create a recipe. For MVP/demo this endpoint is authenticated (any user).",
)
async def create_recipe(
    payload: RecipeCreateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RecipeDetail:
    recipe = Recipe(
        title=payload.title,
        description=payload.description,
        cuisine=payload.cuisine,
        diet=payload.diet,
        prep_time_minutes=payload.prep_time_minutes,
        cook_time_minutes=payload.cook_time_minutes,
        servings=payload.servings,
        ingredients=[i.model_dump() for i in payload.ingredients],
        steps=[s.model_dump() for s in payload.steps],
        image_url=payload.image_url,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(recipe)
    db.flush()

    await _WS_HUB.broadcast({"type": "recipe.created", "recipe_id": str(recipe.id)})

    return _recipe_to_detail(db, recipe)


@api_router.get(
    "/recipes/{recipe_id}",
    response_model=RecipeDetail,
    responses={404: {"model": ErrorResponse}},
    tags=["recipes"],
    summary="Get recipe detail",
    description="Fetch full recipe details including ingredients and steps.",
)
def get_recipe(recipe_id: uuid.UUID, db: Session = Depends(get_db)) -> RecipeDetail:
    try:
        recipe = get_recipe_flow(db, recipe_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Recipe not found") from None
    return _recipe_to_detail(db, recipe)


@api_router.patch(
    "/recipes/{recipe_id}",
    response_model=RecipeDetail,
    responses={404: {"model": ErrorResponse}},
    tags=["recipes"],
    summary="Update recipe",
    description="Update a recipe (authenticated).",
)
async def update_recipe(
    recipe_id: uuid.UUID,
    payload: RecipeUpdateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RecipeDetail:
    try:
        recipe = get_recipe_flow(db, recipe_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Recipe not found") from None

    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        if k in ("ingredients", "steps") and v is not None:
            setattr(recipe, k, [x.model_dump() for x in v])
        else:
            setattr(recipe, k, v)
    recipe.updated_at = datetime.utcnow()
    db.add(recipe)
    db.flush()

    await _WS_HUB.broadcast({"type": "recipe.updated", "recipe_id": str(recipe.id)})

    return _recipe_to_detail(db, recipe)


@api_router.post(
    "/recipes/{recipe_id}/favorite",
    response_model=FavoriteToggleResponse,
    tags=["favorites"],
    summary="Toggle favorite",
    description="Favorite/unfavorite a recipe for current user.",
)
async def toggle_favorite(
    recipe_id: uuid.UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FavoriteToggleResponse:
    is_favorite = toggle_favorite_flow(db, user.id, recipe_id)
    await _WS_HUB.broadcast(
        {"type": "favorite.toggled", "recipe_id": str(recipe_id), "user_id": str(user.id), "is_favorite": is_favorite}
    )
    return FavoriteToggleResponse(is_favorite=is_favorite)


@api_router.get(
    "/shopping-list",
    response_model=ShoppingListPublic,
    tags=["shopping-list"],
    summary="Get shopping list",
    description="Get current user's shopping list.",
)
def get_shopping_list(
    user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ShoppingListPublic:
    sl = get_or_create_shopping_list_flow(db, user.id)
    return ShoppingListPublic(items=sl.items or [])


@api_router.post(
    "/shopping-list/generate",
    response_model=ShoppingListPublic,
    tags=["shopping-list"],
    summary="Generate shopping list",
    description="Aggregate ingredients from multiple recipes into the user's shopping list.",
)
async def generate_shopping_list(
    payload: ShoppingListGenerateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ShoppingListPublic:
    sl = get_or_create_shopping_list_flow(db, user.id)

    # Simple aggregation: concatenate ingredients; a later iteration can normalize/merge.
    items: list[dict] = []
    for rid in payload.recipe_ids:
        recipe = db.scalar(select(Recipe).where(Recipe.id == rid))
        if recipe:
            for ing in (recipe.ingredients or []):
                items.append({**ing, "checked": False})

    sl.items = items
    sl.updated_at = datetime.utcnow()
    db.add(sl)
    db.flush()

    await _WS_HUB.broadcast({"type": "shopping_list.generated", "user_id": str(user.id), "count": len(items)})
    return ShoppingListPublic(items=sl.items or [])


@api_router.get(
    "/meal-plans",
    response_model=list[MealPlanPublic],
    tags=["meal-plans"],
    summary="List meal plans",
    description="List current user's meal plan entries.",
)
def list_meal_plans(
    user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[MealPlanPublic]:
    rows = db.scalars(select(MealPlan).where(MealPlan.user_id == user.id).order_by(MealPlan.plan_date.asc())).all()
    return [
        MealPlanPublic(
            id=r.id,
            user_id=r.user_id,
            plan_date=r.plan_date,
            meal=r.meal,
            recipe_id=r.recipe_id,
            note=r.note,
        )
        for r in rows
    ]


@api_router.post(
    "/meal-plans",
    response_model=MealPlanPublic,
    tags=["meal-plans"],
    summary="Upsert meal plan entry",
    description="Create or replace a meal plan entry for (date, meal).",
)
async def upsert_meal_plan(
    payload: MealPlanUpsertRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MealPlanPublic:
    existing = db.scalar(
        select(MealPlan).where(
            MealPlan.user_id == user.id,
            MealPlan.plan_date == payload.plan_date,
            MealPlan.meal == payload.meal,
        )
    )
    if existing:
        existing.recipe_id = payload.recipe_id
        existing.note = payload.note
        db.add(existing)
        db.flush()
        mp = existing
        event_type = "meal_plan.updated"
    else:
        mp = MealPlan(
            user_id=user.id,
            plan_date=payload.plan_date,
            meal=payload.meal,
            recipe_id=payload.recipe_id,
            note=payload.note,
        )
        db.add(mp)
        db.flush()
        event_type = "meal_plan.created"

    await _WS_HUB.broadcast(
        {"type": event_type, "user_id": str(user.id), "plan_date": str(mp.plan_date), "meal": mp.meal}
    )
    return MealPlanPublic(
        id=mp.id, user_id=mp.user_id, plan_date=mp.plan_date, meal=mp.meal, recipe_id=mp.recipe_id, note=mp.note
    )


@ws_router.websocket("/ws/updates")
async def websocket_updates(ws: WebSocket):
    """WebSocket endpoint for real-time updates.

    Clients receive JSON events like:
      - {"type":"recipe.created","recipe_id":"..."}
      - {"type":"favorite.toggled", ...}
    """
    await _WS_HUB.connect(ws)
    try:
        while True:
            # Keep connection alive; we ignore incoming messages in this MVP.
            await ws.receive_text()
    except WebSocketDisconnect:
        _WS_HUB.disconnect(ws)
    except Exception:
        _WS_HUB.disconnect(ws)


def _recipe_to_detail(db: Session, recipe: Recipe) -> RecipeDetail:
    total_time = int(recipe.prep_time_minutes + recipe.cook_time_minutes)
    return RecipeDetail(
        id=recipe.id,
        title=recipe.title,
        description=recipe.description,
        cuisine=recipe.cuisine,
        diet=recipe.diet,
        total_time_minutes=total_time,
        image_url=recipe.image_url,
        average_rating=0.0,
        favorites_count=0,
        prep_time_minutes=recipe.prep_time_minutes,
        cook_time_minutes=recipe.cook_time_minutes,
        servings=recipe.servings,
        ingredients=recipe.ingredients or [],
        steps=recipe.steps or [],
        created_at=recipe.created_at,
    )
