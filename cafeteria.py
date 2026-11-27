"""Optimize three intact meals and compare budget tiers."""
import json

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp

from allergens import filter_meals
from config import SLOT_LABELS

MACROS = ("energy_kcal", "carb_g", "protein_g", "fat_g")
TARGETS = {
    "남성(19~29세)": (2600., 130., 65., 2600 * .15 / 9),
    "여성(19~29세)": (2000., 130., 55., 2000 * .15 / 9),
}
PROTEIN_MIN = {"남성(19~29세)": 50., "여성(19~29세)": 45.}
CARB_MIN = 100.
FAT_SHARE_MIN = .15
SODIUM_LIMIT = 2300.
WEIGHTS = np.array([1., 1., 2., 1.])
EPS = 1e-7
LEAN_LOSS_TOLERANCE = 0.005


def _solve(eligible, profile, *, value, low=None, high=None, cheapest=False,
           targets_override=None, weights=WEIGHTS, weighted_first=False,
           lean=False, protein_floor=None):
    count = len(eligible)
    intake = eligible[list(MACROS)].to_numpy(dtype=float).T
    priced = eligible.price_complete.eq(True) & eligible.base_cost_won.notna()
    cents = np.rint(eligible.base_cost_won.where(priced, 0).to_numpy(dtype=float) * 100)
    targets = np.array(TARGETS[profile] if targets_override is None else targets_override)
    rows, lows, highs = [], [], []

    def constrain(meal_terms, lower=-np.inf, upper=np.inf, shortages=None):
        rows.append(np.r_[meal_terms, np.zeros(5) if shortages is None else shortages])
        lows.append(lower)
        highs.append(upper)

    for slot in SLOT_LABELS:
        constrain(eligible.slot.eq(slot), 1, 1)
    constrain(eligible.sodium_mg, upper=SODIUM_LIMIT)
    constrain(intake[1], lower=CARB_MIN)
    constrain(intake[2], lower=max(PROTEIN_MIN[profile], protein_floor or 0))
    constrain(9 * intake[3] - FAT_SHARE_MIN * intake[0], lower=0)
    for index, values in enumerate(intake):
        constrain(values / targets[index], lower=1, shortages=np.eye(5)[index])
        constrain(np.zeros(count), upper=0, shortages=np.eye(5)[index] - np.eye(5)[4])
    if value:
        constrain(cents, -np.inf if low is None else low, high)

    cost = np.r_[cents, np.zeros(5)]
    loss = np.r_[np.zeros(count), weights / weights.sum(), 0.]
    integrality = np.r_[np.ones(count), np.zeros(5)]
    bounds = Bounds(np.zeros(count + 5), np.ones(count + 5))

    def optimize(objective):
        result = milp(objective, integrality=integrality, bounds=bounds,
                      constraints=LinearConstraint(np.vstack(rows), lows, highs),
                      options={"mip_rel_gap": 0., "time_limit": 30})
        if result.status == 2:
            return None
        if result.status != 0:
            raise RuntimeError(f"최적해를 확인하지 못했습니다. {result.message}")
        return result

    if cheapest:
        result = optimize(cost)
        if result is None:
            return None
        constrain(cents, upper=round(result.fun))

    worst_shortage = np.r_[np.zeros(count), 0., 0., 0., 0., 1.]
    criteria = [loss, worst_shortage] if weighted_first else [worst_shortage, loss]
    if lean:
        criteria.insert(1, np.r_[intake[3], np.zeros(5)])
    if value and not cheapest:
        criteria.append(cost)
    for objective in criteria:
        result = optimize(objective)
        if result is None:
            return None
        tolerance = LEAN_LOSS_TOLERANCE if lean and objective is loss else EPS
        constrain(objective[:count], upper=result.fun + tolerance, shortages=objective[count:])

    indexes = np.flatnonzero(result.x[:count] > .5)
    selected = eligible.iloc[indexes].copy()
    selected = selected.sort_values("slot", key=lambda series: series.map(dict(zip(SLOT_LABELS, range(3)))))
    totals = selected[list(MACROS) + ["sodium_mg"]].sum().to_dict()
    gaps = {key: max(0., target - totals[key]) for key, target in zip(MACROS, targets)}
    score = float(np.dot(weights, np.array(list(gaps.values())) / targets) / weights.sum())
    coverage = {key: totals[key] / target for key, target in zip(MACROS, targets)}
    return {
        "coverage": coverage, "balance": min(1., min(coverage.values())),
        "meals": selected, "totals": totals, "gaps": gaps, "score": score,
        "price_cents": int(cents[indexes].sum()) if priced.iloc[indexes].all() else None,
    }


def eligible_meals(meals, *, value, sources, excluded, allergies):
    eligible = meals[meals.nutrition_complete.eq(True)]
    if sources is not None:
        eligible = eligible[eligible.source.isin(sources)]
    if excluded:
        blocked = set(excluded)
        eligible = eligible[~eligible.menu_json.map(lambda raw: bool(blocked.intersection(json.loads(raw))))]
    eligible = filter_meals(eligible, allergies)
    if value:
        eligible = eligible[eligible.price_complete.eq(True) & eligible.base_cost_won.notna()]
    return eligible.drop_duplicates(["slot", "menu_json"])


def balanced_within_budget(meals, profile, budget, *, sources=None, excluded=(), allergies=()):
    """Maximize the lowest target coverage under the base budget."""
    eligible = eligible_meals(meals, value=True, sources=sources, excluded=excluded, allergies=allergies)
    if set(SLOT_LABELS) - set(eligible.slot):
        return None
    return _solve(eligible, profile, value=True, high=budget * 100)


def recommend(meals, profile, budget=15000, extra=0, *, value=False, sources=None, excluded=(), allergies=()):
    """Keep the base budget and offer separate 1,000-won improvement tiers."""
    if extra not in (0, 1000, 2000) or not isinstance(budget, int) or budget < 0:
        raise ValueError("예산은 0 이상의 정수, 초과 한도는 0·1,000·2,000원이어야 합니다.")
    eligible = eligible_meals(meals, value=value, sources=sources, excluded=excluded, allergies=allergies)
    if set(SLOT_LABELS) - set(eligible.slot):
        return None, []
    if not value:
        return _solve(eligible, profile, value=False), []

    ceiling = budget * 100
    base = _solve(eligible, profile, value=True, high=ceiling, cheapest=True)
    if not extra:
        return base, []
    if base is None:
        fallback = _solve(eligible, profile, value=True, low=ceiling + 1,
                          high=ceiling + extra * 100, cheapest=True)
        return None, [fallback] if fallback else []

    alternatives = []
    best = _solve(eligible, profile, value=True, high=ceiling)
    for end in range(1000, extra + 1, 1000):
        alternative = _solve(eligible, profile, value=True, low=ceiling + (end - 1000) * 100 + 1,
                             high=ceiling + end * 100)
        if alternative and (
            alternative["balance"] > best["balance"] + EPS
            or (abs(alternative["balance"] - best["balance"]) <= EPS
                and alternative["score"] < best["score"] - EPS)
        ):
            alternatives.append(alternative)
            best = alternative
    return base, alternatives



def plan_meals(meals, profile, budget, *, value=False, allergies=(), excluded=(),
               protein_target=None, protein_floor=None, lean=False,
               previous=None, replacing=None, extra=0):
    """Choose three original servings under the user's budget and preferences."""
    eligible = eligible_meals(meals, value=True, sources=None, excluded=excluded, allergies=allergies)
    if previous is not None and replacing is not None:
        for meal in previous["meals"].itertuples():
            matching = eligible.menu_json.eq(meal.menu_json)
            keep = ~matching if meal.slot == replacing else matching
            eligible = eligible[~eligible.slot.eq(meal.slot) | keep]
    if set(SLOT_LABELS) - set(eligible.slot):
        return None
    targets = list(TARGETS[profile])
    weights = WEIGHTS.copy()
    if protein_target is not None:
        targets[2] = protein_target
        weights[2] = 4.
    return _solve(
        eligible, profile, value=True, high=(budget + extra) * 100,
        low=budget * 100 + 1 if extra else None, cheapest=value or bool(extra),
        targets_override=targets, weights=weights, weighted_first=True,
        lean=lean, protein_floor=protein_floor,
    )
