from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.db.models import Favorite, Recipe, ShoppingList

logger = logging.getLogger("recipe_backend.flows")


@dataclass(frozen=True)
class ListRecipesRequest:
    query: str = ""
    cuisine: str = ""
    diet: str = ""
    max_total_time_minutes: Optional[int] = None
    limit: int = 20
    offset: int = 0


@dataclass(frozen=True)
class ListRecipesItem:
    id: uuid.UUID
    title: str
    description: str
    cuisine: str
    diet: str
    total_time_minutes: int
    image_url: str
    average_rating: float
    favorites_count: int


# PUBLIC_INTERFACE
def list_recipes_flow(db: Session, req: ListRecipesRequest) -> list[ListRecipesItem]:
    """List recipes with basic filters and computed aggregates.

    Contract:
      Inputs: validated ListRecipesRequest
      Outputs: list of ListRecipesItem
      Errors: bubbles SQLAlchemy errors; caller maps to HTTP errors
      Side effects: none
    """
    logger.info(
        "list_recipes_flow.start query=%s cuisine=%s diet=%s limit=%s offset=%s",
        req.query,
        req.cuisine,
        req.diet,
        req.limit,
        req.offset,
    )

    # Subqueries for favorites and rating averages
    fav_counts = (
        select(Favorite.recipe_id, func.count(Favorite.id).label("fav_count"))
        .group_by(Favorite.recipe_id)
        .subquery()
    )

    # ratings table not in use in minimal UI; average kept 0 for now in query to keep stable schema
    q = select(
        Recipe,
        func.coalesce(fav_counts.c.fav_count, 0).label("favorites_count"),
    ).outerjoin(fav_counts, fav_counts.c.recipe_id == Recipe.id)

    if req.query:
        like = f"%{req.query.lower()}%"
        q = q.where(func.lower(Recipe.title).like(like))
    if req.cuisine:
        q = q.where(Recipe.cuisine == req.cuisine)
    if req.diet:
        q = q.where(Recipe.diet == req.diet)
    if req.max_total_time_minutes is not None:
        q = q.where((Recipe.prep_time_minutes + Recipe.cook_time_minutes) <= req.max_total_time_minutes)

    q = q.order_by(Recipe.created_at.desc()).limit(req.limit).offset(req.offset)

    rows = db.execute(q).all()
    items: list[ListRecipesItem] = []
    for recipe, favorites_count in rows:
        total_time = int(recipe.prep_time_minutes + recipe.cook_time_minutes)
        items.append(
            ListRecipesItem(
                id=recipe.id,
                title=recipe.title,
                description=recipe.description,
                cuisine=recipe.cuisine,
                diet=recipe.diet,
                total_time_minutes=total_time,
                image_url=recipe.image_url,
                average_rating=0.0,
                favorites_count=int(favorites_count),
            )
        )

    logger.info("list_recipes_flow.success count=%s", len(items))
    return items


# PUBLIC_INTERFACE
def get_recipe_flow(db: Session, recipe_id: uuid.UUID) -> Recipe:
    """Fetch a recipe by id or raise KeyError."""
    logger.info("get_recipe_flow.start recipe_id=%s", recipe_id)
    recipe = db.scalar(select(Recipe).where(Recipe.id == recipe_id))
    if not recipe:
        logger.info("get_recipe_flow.not_found recipe_id=%s", recipe_id)
        raise KeyError("Recipe not found")
    logger.info("get_recipe_flow.success recipe_id=%s", recipe_id)
    return recipe


# PUBLIC_INTERFACE
def toggle_favorite_flow(db: Session, user_id: uuid.UUID, recipe_id: uuid.UUID) -> bool:
    """Toggle favorite for a recipe.

    Returns:
      bool: True if favorited after operation, False otherwise.
    """
    logger.info("toggle_favorite_flow.start user_id=%s recipe_id=%s", user_id, recipe_id)
    existing = db.scalar(select(Favorite).where(Favorite.user_id == user_id, Favorite.recipe_id == recipe_id))
    if existing:
        db.delete(existing)
        db.flush()
        logger.info("toggle_favorite_flow.success is_favorite=false")
        return False

    db.add(Favorite(user_id=user_id, recipe_id=recipe_id))
    db.flush()
    logger.info("toggle_favorite_flow.success is_favorite=true")
    return True


# PUBLIC_INTERFACE
def get_or_create_shopping_list_flow(db: Session, user_id: uuid.UUID) -> ShoppingList:
    """Get or create a user's shopping list row."""
    sl = db.scalar(select(ShoppingList).where(ShoppingList.user_id == user_id))
    if sl:
        return sl
    sl = ShoppingList(user_id=user_id, items=[])
    db.add(sl)
    db.flush()
    return sl
