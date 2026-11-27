"""Chat interface for recommendations from intact cafeteria meals."""
import json

import pandas as pd
import streamlit as st

from allergens import FIELDS
from cafeteria import TARGETS, plan_meals
from config import LABELS, ROOT, SLOT_LABELS
from conversation import interpret
from gs25 import DEFAULT_PATH, load_products
from snacks import recommend_snack

st.set_page_config(page_title="하루 식단 에이전트", page_icon="🍚")
st.title("하루 식단 에이전트")


def data_path(path):
    if path.is_file():
        return path
    return ROOT / path.name


@st.cache_data
def load_inputs(meals_path, products_path, meals_version, products_version):
    meals = pd.read_csv(meals_path, low_memory=False)
    names = {item for raw in meals.menu_json.unique() for item in json.loads(raw)}
    return meals, load_products(products_path), names


meals_path = data_path(ROOT / "data/meals.csv.gz")
products_path = data_path(DEFAULT_PATH)
meals, products, names = load_inputs(
    meals_path, products_path, meals_path.stat().st_mtime_ns, products_path.stat().st_mtime_ns
)
with st.sidebar:
    st.radio("추천 기준", ["영양 우선", "가성비 우선"], key="mode")
    st.multiselect("피해야 할 알레르기", FIELDS, key="allergies")
    if st.session_state.allergies:
        st.caption("알레르기 필터는 원본 표기에 근거해요. 실제 섭취 전 포장과 배식 안내를 확인해 주세요.")
    with st.expander("영양 참고 기준"):
        st.selectbox("19~29세 기준", list(TARGETS), key="profile")
    if st.button("새 대화"):
        st.session_state.dialog = {}
        st.session_state.messages = []
        st.session_state.pop("plan", None)
        st.session_state.pop("snack", None)
        st.session_state.pop("context", None)
        st.rerun()


def amount(cents):
    won = ((cents + 500) // 1000) * 10
    return f"{won:,}원"


def snack_sentence(plan, snack):
    item = snack["item"]
    timing = "끼니 사이에"
    if plan["gaps"]["energy_kcal"] > 0 and item.energy_kcal > 0:
        lightest = min(plan["meals"].itertuples(), key=lambda row: row.energy_kcal)
        timing = f"{SLOT_LABELS[lightest.slot]} 후"
    return f"{timing} 출출하면 GS25에서 **{item.product_name}**을 간식으로 먹는 걸 추천할게."


def menu_reply(plan, snack, mode, budget, *, alternative=False, protein_target=None):
    meal_price = plan["price_cents"]
    if alternative:
        over = meal_price - budget * 100
        displayed_over = "10원 미만" if over < 500 else amount(over)
        opening = f"예산을 **{displayed_over}** 더 쓸 수 있다면 이렇게 먹는 걸 추천해."
    elif mode == "가성비 우선":
        opening = "예산 안에서 비용을 아끼려면 오늘은 이렇게 먹는 걸 추천해."
    else:
        opening = "오늘은 예산 안에서 영양 목표에 가까운 이 조합을 추천해."

    menu = [f"**{SLOT_LABELS[row.slot]}**은 {row.menu_text}" for row in plan["meals"].itertuples()]
    lines = [opening, *menu]
    price_line = f"세 끼 추정원가는 약 **{amount(meal_price)}**이야."
    if snack:
        item = snack["item"]
        snack_price = int(item.price_won) * 100
        price_line += (
            f" 간식은 참고가 약 **{amount(snack_price)}**이고, "
            f"간식까지 합치면 약 **{amount(meal_price + snack_price)}**이야."
        )
    lines.append(price_line)
    if protein_target:
        lines.append(
            f"단백질 목표 **{protein_target:g}g**에 세 끼로 **{plan['totals']['protein_g']:.1f}g**을 채워."
        )
    if snack:
        lines.append(snack_sentence(plan, snack))
    return "\n\n".join(lines)


def explain(plan, snack, context):
    if plan is None:
        return "하루 식단을 먼저 추천받으면 선택 이유와 영양 합계를 확인할 수 있어."
    mode, _, _, lean = context
    method = "입력 예산과 영양 하한을 만족한 세 끼 중 추정원가가 가장 낮은 조합이야." if mode == "가성비 우선" else "입력 예산 안에서 영양소별 부족률을 비교했어. 단백질 부족에 더 큰 가중치를 적용했어."
    if lean:
        method += " 영양 점수 차이가 0.5%p 이내인 후보 중 지방이 적은 식단을 골랐어."
    rows = ["마지막으로 추천한 식단의 계산 결과야.", "", method, ""]
    if snack:
        rows += [f"간식을 더하면 가중 충족률이 {100 * snack['improvement']:.1f}%p 올라가.", ""]
    for key, value in plan["totals"].items():
        coverage = plan["coverage"][key] if key in plan["coverage"] else None
        suffix = f" · 목표의 {coverage:.1%}" if coverage is not None else " · 모델 상한 2,300mg"
        if snack and key in snack["coverage"]:
            suffix += f" → 간식 포함 {snack['coverage'][key]:.1%}"
        elif snack and key == "sodium_mg":
            suffix += f" → 간식 포함 {snack['totals'][key]:,.0f}mg"
        rows.append(f"- {LABELS[key]} {value:,.1f}{suffix}")
    return "\n".join(rows)


def submit():
    message = st.session_state.request
    if not message:
        return
    st.session_state.messages.append(("user", message))
    try:
        reply = respond(message)
    except (ValueError, RuntimeError) as error:
        reply = str(error)
    st.session_state.messages.append(("assistant", reply))


def respond(message):
    state = st.session_state
    settings = state.dialog
    updates, kind, replacing = interpret(message, names, awaiting_budget="budget" not in settings)
    if kind == "reason":
        return explain(state.get("plan"), state.get("snack"), state.get("context"))
    settings.update({key: value for key, value in updates.items() if key not in {"mode", "allergies", "excluded"}})
    if "mode" in updates:
        state.mode = updates["mode"]
    if "allergies" in updates:
        state.allergies = list(dict.fromkeys([*state.allergies, *updates["allergies"]]))
    if "excluded" in updates:
        settings["excluded"] = list(dict.fromkeys([*settings.get("excluded", ()), *updates["excluded"]]))
    budget = settings.get("budget")
    protein_target = settings.get("protein_target")
    if settings.get("muscle"):
        protein_target = TARGETS[state.profile][2] + 15
    if kind == "conditions":
        lines = [f"추천 기준 **{state.mode}**", f"예산 **{budget:,}원**" if budget is not None else "예산을 아직 정하지 않았어."]
        if protein_target:
            lines.append(f"단백질 목표 **{protein_target:g}g**")
        if state.allergies or settings.get("excluded"):
            lines.append("제외 항목 " + ", ".join([*state.allergies, *settings.get("excluded", ())]))
        if settings.get("lean"):
            lines.append("가중 부족률 차이가 0.5%p 이내인 후보 중 지방이 적은 쪽을 우선해.")
        return " · ".join(lines)
    if budget is None:
        return "하루 식비 예산을 어느 정도로 잡을까?"
    previous = state.get("plan")
    if replacing and previous is None:
        return "먼저 하루 식단을 추천받으면 원하는 끼니만 바꿀 수 있어."
    lean = settings.get("lean", False)
    options = dict(value=state.mode == "가성비 우선", allergies=state.allergies,
                   excluded=settings.get("excluded", ()), protein_target=protein_target,
                   protein_floor=settings.get("protein_floor"), lean=lean,
                   previous=previous, replacing=replacing)
    if kind == "alternatives":
        alt = plan_meals(meals, state.profile, budget, **options, extra=2000)
        return menu_reply(alt, None, state.mode, budget, alternative=True) if alt else "예산을 최대 2,000원 올린 범위에서도 조건을 만족하는 조합이 없어."
    plan = plan_meals(meals, state.profile, budget, **options)
    if plan is None:
        alt = plan_meals(meals, state.profile, budget, **options, extra=2000)
        if alt is not None:
            return "현재 예산에는 조건을 만족하는 조합이 없어. 아래 대안을 보고 예산을 올리고 싶으면 새 금액을 알려줘.\n\n" + menu_reply(alt, None, state.mode, budget, alternative=True)
        return "현재 조건을 만족하는 조합을 찾지 못했어. 예산이나 단백질 목표를 바꿔서 다시 계산할 수 있어."
    snack = recommend_snack(products, plan, budget, state.profile, allergies=state.allergies,
                            lean=lean, protein_target=protein_target)
    state.plan = plan
    state.snack = snack
    state.context = (state.mode, budget, protein_target, lean)
    return menu_reply(plan, snack, state.mode, budget, protein_target=protein_target)


if "dialog" not in st.session_state:
    st.session_state.dialog = {}
    st.session_state.messages = []

with st.chat_message("assistant"):
    st.markdown("오늘 식단을 같이 골라 볼까? **‘오늘 식단 짜줘’**라고 시작해 봐.")
for role, message in st.session_state.messages:
    with st.chat_message(role):
        st.markdown(message)
st.chat_input("식단이나 원하는 조건을 말해 줘", key="request", on_submit=submit)
