"""Rank one packaged GS25 snack against the selected three meals."""
import numpy as np

from cafeteria import MACROS, SODIUM_LIMIT, TARGETS, WEIGHTS, EPS

SNACK_PRICE_LIMIT = 2999


def recommend_snack(products, plan, budget, profile, *, allergies=(),
                    lean=False, protein_target=None):
    if plan is None or plan["price_cents"] is None:
        return None

    from gs25 import _allergens

    exclusions = set(allergies)
    remaining = budget * 100 - plan["price_cents"]
    targets = np.array(TARGETS[profile])
    weights = WEIGHTS.copy()
    if protein_target is not None:
        targets[2] = protein_target
        weights[2] = 4.
    before = np.array([plan["totals"][key] for key in MACROS])
    best = None
    best_rank = None
    price_cap = min(SNACK_PRICE_LIMIT, remaining // 100)
    candidates = products[products.price_won.le(price_cap) & ~products.availability.eq("판매종료")]
    for item in candidates.itertuples(index=False):
        if exclusions and (
            item.allergy_verified != "true"
            or exclusions & (_allergens(item.contains) | _allergens(item.may_contain))
        ):
            continue
        sodium = plan["totals"]["sodium_mg"] + item.sodium_mg
        if sodium > SODIUM_LIMIT:
            continue
        after = before + np.array([getattr(item, key) for key in MACROS])
        improvement = float(np.average(
            np.minimum(after / targets, 1) - np.minimum(before / targets, 1), weights=weights
        ))
        if improvement <= EPS:
            continue
        rank = (-round(improvement, 10), -float(np.min(after / targets).clip(max=1)),
                item.fat_g if lean else 0, item.price_won, item.product_id)
        if best_rank is None or rank < best_rank:
            best_rank = rank
            best = {
                "item": item, "improvement": improvement,
                "totals": dict(zip(MACROS, after), sodium_mg=sodium),
                "coverage": dict(zip(MACROS, after / targets)),
            }
    return best
