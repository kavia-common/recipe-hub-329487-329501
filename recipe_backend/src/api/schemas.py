from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class UserPublic(BaseModel):
    id: uuid.UUID = Field(..., description="User id (UUID)")
    email: str = Field(..., description="User email")
    display_name: str = Field(..., description="Display name")
    is_admin: bool = Field(..., description="Whether user has admin privileges")


class AuthSignupRequest(BaseModel):
    email: str = Field(..., description="Email address")
    password: str = Field(..., min_length=6, description="Password (min 6 chars)")
    display_name: str = Field("", description="Display name")


class AuthLoginRequest(BaseModel):
    email: str = Field(..., description="Email address")
    password: str = Field(..., description="Password")


class AuthTokenResponse(BaseModel):
    access_token: str = Field(..., description="Bearer token")
    token_type: str = Field("bearer", description="Token type")
    user: UserPublic = Field(..., description="Authenticated user")


class Ingredient(BaseModel):
    name: str = Field(..., description="Ingredient name")
    quantity: str = Field("", description="Quantity value (free-form)")
    unit: str = Field("", description="Unit (free-form)")


class Step(BaseModel):
    step: int = Field(..., ge=1, description="Step number (1-indexed)")
    text: str = Field(..., description="Instruction text")


class RecipeBase(BaseModel):
    title: str = Field(..., description="Recipe title")
    description: str = Field("", description="Short description")
    cuisine: str = Field("", description="Cuisine, e.g. Italian")
    diet: str = Field("", description="Diet label, e.g. Vegan")
    prep_time_minutes: int = Field(0, ge=0, description="Prep time in minutes")
    cook_time_minutes: int = Field(0, ge=0, description="Cook time in minutes")
    servings: int = Field(1, ge=1, description="Servings count")
    ingredients: list[Ingredient] = Field(default_factory=list, description="Ingredient list")
    steps: list[Step] = Field(default_factory=list, description="Step-by-step instructions")
    image_url: str = Field("", description="Recipe image URL")


class RecipeCreateRequest(RecipeBase):
    pass


class RecipeUpdateRequest(BaseModel):
    title: Optional[str] = Field(None, description="Recipe title")
    description: Optional[str] = Field(None, description="Short description")
    cuisine: Optional[str] = Field(None, description="Cuisine")
    diet: Optional[str] = Field(None, description="Diet")
    prep_time_minutes: Optional[int] = Field(None, ge=0, description="Prep time in minutes")
    cook_time_minutes: Optional[int] = Field(None, ge=0, description="Cook time in minutes")
    servings: Optional[int] = Field(None, ge=1, description="Servings count")
    ingredients: Optional[list[Ingredient]] = Field(None, description="Ingredient list")
    steps: Optional[list[Step]] = Field(None, description="Steps list")
    image_url: Optional[str] = Field(None, description="Recipe image URL")


class RecipeSummary(BaseModel):
    id: uuid.UUID = Field(..., description="Recipe id")
    title: str = Field(..., description="Recipe title")
    description: str = Field("", description="Short description")
    cuisine: str = Field("", description="Cuisine")
    diet: str = Field("", description="Diet")
    total_time_minutes: int = Field(..., description="Prep + cook time")
    image_url: str = Field("", description="Recipe image URL")
    average_rating: float = Field(0, description="Average rating 0-5")
    favorites_count: int = Field(0, description="Number of favorites")


class RecipeDetail(RecipeSummary):
    prep_time_minutes: int = Field(0, description="Prep time")
    cook_time_minutes: int = Field(0, description="Cook time")
    servings: int = Field(1, description="Servings")
    ingredients: list[Ingredient] = Field(default_factory=list, description="Ingredients")
    steps: list[Step] = Field(default_factory=list, description="Steps")
    created_at: datetime = Field(..., description="Creation time")


class FavoriteToggleResponse(BaseModel):
    is_favorite: bool = Field(..., description="Whether recipe is now favorited")


class CommentCreateRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000, description="Comment content")


class CommentPublic(BaseModel):
    id: uuid.UUID = Field(..., description="Comment id")
    user_id: uuid.UUID = Field(..., description="User id")
    recipe_id: uuid.UUID = Field(..., description="Recipe id")
    content: str = Field(..., description="Comment content")
    created_at: datetime = Field(..., description="Creation time")


class RatingUpsertRequest(BaseModel):
    value: int = Field(..., ge=1, le=5, description="Rating value 1-5")


class ShoppingListPublic(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list, description="Shopping list items")


class ShoppingListGenerateRequest(BaseModel):
    recipe_ids: list[uuid.UUID] = Field(..., description="Recipes to aggregate into a shopping list")


class MealPlanUpsertRequest(BaseModel):
    plan_date: date = Field(..., description="Date for the meal plan entry")
    meal: str = Field("dinner", description="Meal slot: breakfast/lunch/dinner/snack")
    recipe_id: Optional[uuid.UUID] = Field(None, description="Recipe id, optional")
    note: str = Field("", description="Optional note")


class MealPlanPublic(BaseModel):
    id: uuid.UUID = Field(..., description="Meal plan id")
    user_id: uuid.UUID = Field(..., description="User id")
    plan_date: date = Field(..., description="Date")
    meal: str = Field(..., description="Meal slot")
    recipe_id: Optional[uuid.UUID] = Field(None, description="Recipe id")
    note: str = Field("", description="Note")


class ErrorResponse(BaseModel):
    detail: str = Field(..., description="Error message")
