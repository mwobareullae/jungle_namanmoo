from pathlib import Path

from app.models.data_contract import (
    ConcernEffect,
    DataCatalog,
    Ingredient,
    IngredientEvidence,
    Product,
    ProductIngredient,
    ProductPrice,
    SearchDocument,
)
from app.services.data_loader import load_data_catalog


class DataRepository:
    def __init__(self, catalog: DataCatalog) -> None:
        self._catalog = catalog
        self._products_by_id = {product.product_id: product for product in catalog.products}
        self._ingredients_by_id = {
            ingredient.ingredient_id: ingredient for ingredient in catalog.ingredients
        }

    def list_products(self) -> list[Product]:
        return list(self._catalog.products)

    def get_product(self, product_id: str) -> Product | None:
        return self._products_by_id.get(product_id)

    def get_product_prices(self, product_id: str) -> list[ProductPrice]:
        return [price for price in self._catalog.product_prices if price.product_id == product_id]

    def get_product_ingredients(self, product_id: str) -> list[ProductIngredient]:
        ingredients = [
            ingredient
            for ingredient in self._catalog.product_ingredients
            if ingredient.product_id == product_id
        ]
        return sorted(ingredients, key=lambda ingredient: ingredient.display_order)

    def get_ingredient(self, ingredient_id: str) -> Ingredient | None:
        return self._ingredients_by_id.get(ingredient_id)

    def get_effects_for_concern(self, tag_id: str) -> list[ConcernEffect]:
        return [effect for effect in self._catalog.concern_effects if effect.tag_id == tag_id]

    def get_evidence_for_ingredient(self, ingredient_id: str) -> list[IngredientEvidence]:
        return [
            evidence
            for evidence in self._catalog.ingredient_evidence
            if evidence.ingredient_id == ingredient_id
        ]

    def list_search_documents(self) -> list[SearchDocument]:
        return list(self._catalog.search_documents)


def load_repository(data_dir: str | Path) -> DataRepository:
    return DataRepository(load_data_catalog(data_dir))
