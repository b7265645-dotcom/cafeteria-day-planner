"""Load separately verified GS25 package data for the cafeteria planner."""
from datetime import date

import numpy as np
import pandas as pd

from allergens import FIELDS
from config import ROOT

DEFAULT_PATH = ROOT / "data" / "gs25_products.csv"
PACKAGE_VALUES = ("package_g", "energy_kcal", "carb_g", "protein_g", "fat_g", "sodium_mg")
COLUMNS = (
    "product_id", "product_name", "barcode", *PACKAGE_VALUES, "nutrition_source", "nutrition_as_of",
    "price_won", "price_source", "store", "availability", "checked_on",
    "allergy_verified", "contains", "may_contain", "allergy_source",
)


def _date(value, field, required=False):
    if value or required:
        try:
            if date.fromisoformat(value).isoformat() != value:
                raise ValueError
        except ValueError as error:
            raise ValueError(f"{field}: YYYY-MM-DD 형식이 필요합니다.") from error


def _allergens(value):
    return frozenset(label.strip() for label in value.split("|") if label.strip())


def load_products(path=DEFAULT_PATH):
    """Read one package per row. Blank prices remain missing."""
    products = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    if missing := set(COLUMNS) - set(products):
        raise ValueError(f"GS25 필수 열 누락: {', '.join(sorted(missing))}")
    products = products.loc[:, list(COLUMNS)].apply(lambda column: column.str.strip())
    identity = ["product_id", "product_name", "nutrition_source"]
    if products[identity].eq("").any().any() or products.product_id.duplicated().any():
        raise ValueError("상품 ID·이름·영양 출처를 입력하고 ID는 고유하게 지정하세요.")
    for column in (*PACKAGE_VALUES, "price_won"):
        blank = products[column].eq("")
        values = pd.to_numeric(products[column], errors="coerce")
        valid = np.isfinite(values) & values.ge(0)
        if column == "price_won":
            valid = (valid & values.gt(0) & values.mod(1).eq(0)) | blank
        elif column == "package_g":
            valid &= values.gt(0)
        if not valid.all():
            errors = products.loc[~valid, "product_id"].tolist()
            raise ValueError(f"{column} 값 확인 필요: {', '.join(errors)}")
        products[column] = values
    for row in products.itertuples(index=False):
        _date(row.nutrition_as_of, "nutrition_as_of", required=True)
        _date(row.checked_on, "checked_on", required=row.availability == "판매확인")
        if row.availability not in {"미확인", "판매확인", "판매종료"}:
            raise ValueError(f"{row.product_id}: 판매 상태가 올바르지 않습니다.")
        if row.availability == "판매확인" and not row.store:
            raise ValueError(f"{row.product_id}: 판매를 확인한 점포를 입력하세요.")
        if pd.notna(row.price_won) and (not row.price_source or not row.checked_on):
            raise ValueError(f"{row.product_id}: 가격 출처와 확인일을 입력하세요.")
        if row.allergy_verified not in {"true", "false"}:
            raise ValueError(f"{row.product_id}: allergy_verified는 true 또는 false입니다.")
        if row.allergy_verified == "true" and not row.allergy_source:
            raise ValueError(f"{row.product_id}: 확인한 제품 표기 출처가 필요합니다.")
        if (_allergens(row.contains) | _allergens(row.may_contain)) - set(FIELDS):
            raise ValueError(f"{row.product_id}: 학식 DB와 같은 알레르기 항목 이름을 사용하세요.")
    return products


def eligible_products(products, *, store, budget_won, sodium_mg, allergies=()):
    """Screen packages by confirmed store, price, remaining sodium, and label data."""
    exclusions = set(allergies)
    if exclusions - set(FIELDS):
        raise ValueError("지원하는 알레르기 항목을 사용하세요.")
    candidates = products.loc[
        products.availability.eq("판매확인") & products.store.eq(store)
        & products.price_won.le(budget_won) & products.sodium_mg.le(sodium_mg)
    ]
    if exclusions:
        verified = candidates[candidates.allergy_verified.eq("true")]
        blocked = verified.contains.map(lambda raw: bool(exclusions & _allergens(raw)))
        blocked |= verified.may_contain.map(lambda raw: bool(exclusions & _allergens(raw)))
        return verified.loc[~blocked].copy()
    return candidates.copy()


if __name__ == "__main__":
    products = load_products()
    print(products[["product_name", "package_g", "energy_kcal", "price_won", "availability"]].to_string(index=False))
    print(f"영양 참조 {len(products)}개 / 판매 및 가격 확인 {(products.availability.eq('판매확인') & products.price_won.notna()).sum()}개")

