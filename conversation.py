"""Interpret supported Korean requests without an external service."""
import re
from decimal import Decimal

from allergens import FIELDS
from config import LABELS, SLOT_LABELS

AMOUNT = r"(?P<amount>\d[\d,]*(?:\.\d+)?)\s*(?P<unit>만원|만|천원|천|원)?"
BUDGET = re.compile(rf"(?:예산(?:을|은)?\s*)?{AMOUNT}\s*(?:으로|으로만|로|까지|이하|정도로)?(?:\s*(?:바꿔(?:줘)?|설정해(?:줘)?|추천해(?:줘)?))?")
LIMITS = {"0": 0, "1000": 1000, "2000": 2000}
ALIASES = {"달걀": "난류", "계란": "난류", "우유": "우유"}
EXCLUDE = re.compile(r"(?P<items>.+?)\s*(?:은|는|을|를)?\s*(?:빼고(?:\s*추천해(?:줘)?)?|빼\s*줘|제외해(?:줘)?|제외)")
MODE = {"영양 우선": "영양 우선", "가성비 우선": "가성비 우선", "최저가": "가성비 우선"}


def parse_message(message, names):
    """Return atomic widget changes and the requested kind of reply."""
    query = message.strip().rstrip(".!?")
    if query in {"왜?", "왜", "왜 이 식단이야", "추천 이유", "왜 이 식단을 추천했어", "추천 이유 알려줘"}:
        return {}, "reason"
    if query in {"예산 얼마였지", "내 예산 얼마야", "현재 조건", "설정 알려줘"}:
        return {}, "conditions"
    if query in {"초과 대안 보여줘", "다른 대안 보여줘", "대안 보여줘", "대안"}:
        return {}, "alternatives"
    if query in {"추천", "추천해줘", "추천해 줘", "식단 추천해줘", "오늘 식단 추천해줘"}:
        return {}, "plan"

    updates = {}
    for part in re.split(r"\s*(?:[;\n]|(?<!\d),(?!\d))\s*", query):
        part = part.strip()
        if not part:
            continue
        if part in {"초과 대안 끄기", "초과 없이", "예산 초과 없이"}:
            updates["extra"] = 0
            continue
        limit = re.fullmatch(r"(?:예산\s*)?초과(?:\s*한도)?\s*(1,?000|2,?000|0)\s*원(?:까지)?", part)
        if limit:
            updates["extra"] = LIMITS[limit[1].replace(",", "")]
            continue
        mode = re.fullmatch(r"(영양 우선|가성비 우선|최저가)(?:으로|로)?(?:\s*추천해(?:줘)?)?", part)
        if mode:
            updates["mode"] = MODE[mode[1]]
            continue
        budget = BUDGET.fullmatch(part)
        if budget:
            unit = budget["unit"]
            if unit is None and not part.startswith("예산"):
                raise ValueError("금액의 용도를 알려줘. 예를 들어 ‘예산 16,000원’이라고 입력해 줘.")
            amount = Decimal(budget["amount"].replace(",", "")) * {"만원": 10000, "만": 10000, "천원": 1000, "천": 1000}.get(unit, 1)
            if amount != amount.to_integral_value() or not 0 <= amount <= 1_000_000:
                raise ValueError("예산을 0원부터 100만원 사이의 정수 금액으로 알려줘.")
            updates["budget"] = int(amount)
            continue
        exclusion = EXCLUDE.fullmatch(part)
        if exclusion:
            items = re.split(r"\s*(?:이랑|하고|랑|과\s+|와\s+|및\s+)\s*", exclusion["items"])
            for item in items:
                item = re.sub(r"\s*알레르기$", "", item.strip()).strip()
                canonical = ALIASES.get(item, item)
                if canonical in FIELDS:
                    updates.setdefault("allergies", []).append(canonical)
                elif item in names:
                    updates.setdefault("excluded", []).append(item)
                else:
                    raise ValueError(f"‘{item}’의 제외 항목을 확인하지 못했어. 사이드바의 알레르기 항목이나 정확한 메뉴 이름을 써 줘.")
            continue
        raise ValueError("이 문장의 조건을 모두 해석하지 못했어. ‘가성비 우선, 예산 15,000원, 우유랑 난류 빼줘’처럼 조건을 쉼표로 나눠 줘.")
    if not updates:
        raise ValueError("추천 조건이나 궁금한 점을 하나 알려줘.")
    if "budget" in updates or "extra" in updates:
        updates.setdefault("mode", "가성비 우선")
    return updates, "plan"


def answer(kind, result, alternatives, *, mode, budget, extra, allergies, excluded):
    if kind == "conditions":
        filters = ", ".join([*allergies, *excluded]) or "없음"
        return f"현재 기준은 **{mode}**, 예산은 **{budget:,}원**, 초과 한도는 **{extra:,}원**이야. 제외 항목은 {filters}야."
    if kind == "alternatives":
        if mode != "가성비 우선":
            return "예산 초과 대안은 가성비 우선에서 비교해. ‘가성비 우선’이라고 입력해 줘."
        if not alternatives:
            return f"현재 조건의 초과 한도 {extra:,}원에서 표시할 대안이 없어."
        return "\n".join(
            f"- {index}. {item['price_cents'] / 100:,.2f}원 · "
            f"기본 예산 대비 {item['price_cents'] / 100 - budget:,.2f}원 초과 · 최저 충족률 {item['balance']:.1%}"
            for index, item in enumerate(alternatives, 1)
        )
    if result is None:
        if alternatives:
            price = alternatives[0]["price_cents"] / 100
            return f"기본 예산 안에 조건을 만족하는 조합이 없어. 초과 범위의 최저가 대안은 **{price:,.2f}원**이야. 아래 표에서 확인할 수 있어."
        return "현재 조건을 만족하는 조합을 찾지 못했어. 예산이나 제외 조건을 다시 알려주면 재계산할게."

    limiting = min(result["coverage"], key=result["coverage"].get)
    coverage = f"최저 목표 충족률은 **{result['balance']:.1%}**"
    coverage += f"이고, 가장 부족한 항목은 {LABELS[limiting]}이야." if result["balance"] < 1 else "로 네 항목 목표를 모두 충족해."
    if kind == "reason":
        method = "입력 예산 안에서 영양 항목의 최저 충족률을 최대화했어." if mode == "가성비 우선" else "네 영양 항목의 목표 충족률 중 가장 낮은 값을 최대화했어."
        return method + " " + coverage
    menu = "\n".join(f"- **{SLOT_LABELS[row.slot]}** {row.menu_text}" for row in result["meals"].itertuples())
    price = result["price_cents"]
    cost = f"하루 추정원가는 **{price / 100:,.2f}원**이야." if price is not None else "일부 단가가 빠져 하루 추정원가는 계산하지 못했어."
    return f"**{mode} 추천**\n\n{menu}\n\n{coverage} {cost}"


# Conversational entry point for the Streamlit chat.
DAY_MONEY = re.compile(r"(?P<amount>\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(?P<unit>만\s*원|천\s*원|만|천|원)(?![가-힣]?(?:g|그램))")
PROTEIN_GOAL = re.compile(r"(?:단백질\s*(?:은|을)?\s*(?:하루\s*)?)?(\d+(?:\.\d+)?)\s*(?:g\b|그램)\s*(이상|최소)?", re.I)
MEAL_CHANGE = re.compile(r"(아침|점심|저녁)(?:만|을|은)?\s*(?:다른|바꿔|변경|다시)")
BUDGET_RANGE = re.compile(r"\d[\d,.]*\s*(?:만|천)?\s*(?:원)?\s*(?:~|～|에서|부터|–|－|-)\s*\d")
SLOT_KEYS = {label: slot for slot, label in SLOT_LABELS.items()}


def interpret(query, names, *, awaiting_budget=False):
    query = re.sub(r"\s+", " ", query.strip().rstrip(".!?"))
    if query in {"현재 조건", "설정 알려줘", "예산 얼마였지", "내 예산 얼마야"}:
        return {}, "conditions", None
    if re.search(r"추천\s*이유|왜.*(?:추천|식단)|^왜$|영양\s*(?:상세|정보|성분)|충족률", query):
        return {}, "reason", None
    if re.search(r"초과\s*(?:대안|안)|다른\s*대안", query) and not DAY_MONEY.search(query):
        return {}, "alternatives", None
    if BUDGET_RANGE.search(query):
        raise ValueError("하루 예산으로 적용할 최대 금액을 하나 알려줘. ‘2만 원까지’처럼 말해 줘.")

    updates = {}
    money = list(DAY_MONEY.finditer(query))
    if len(money) > 1:
        raise ValueError("하루 예산으로 적용할 금액을 하나 알려줘.")
    if money:
        amount, unit = money[0].group("amount", "unit")
        multiplier = {"만원": 10000, "만": 10000, "천원": 1000, "천": 1000, "원": 1}
        amount = Decimal(amount.replace(",", "")) * multiplier[unit.replace(" ", "")]
    else:
        raw = re.fullmatch(r"(?:예산(?:은|을)?\s*)?(\d[\d,]*)", query)
        amount = Decimal(raw[1].replace(",", "")) if raw and (awaiting_budget or "예산" in query) else None
    if amount is not None:
        if amount != amount.to_integral_value() or not 0 <= amount <= 1_000_000:
            raise ValueError("하루 예산을 0원부터 100만 원 사이의 정수로 알려줘.")
        updates["budget"] = int(amount)
    if re.search(r"가성비|최저가", query):
        updates["mode"] = "가성비 우선"
    elif re.search(r"영양\s*우선", query):
        updates["mode"] = "영양 우선"

    protein = PROTEIN_GOAL.search(query) if "단백질" in query else None
    if protein:
        target = float(protein[1])
        if not 0 < target <= 500:
            raise ValueError("단백질 목표를 0g 초과, 500g 이하로 알려줘.")
        updates.update(protein_target=target, muscle=False,
                       protein_floor=target if protein[2] or "최소" in query else None)
    elif re.search(r"근력|근육|벌크업|고단백|단백질.*(?:많|높|늘)", query):
        updates.update(muscle=True, protein_target=None, protein_floor=None)
    if re.search(r"근력|근육|저지방|지방.*(?:적|낮|줄)", query):
        updates["lean"] = True
    if re.search(r"기본\s*영양|영양\s*선호\s*초기화", query):
        updates.update(muscle=False, protein_target=None, protein_floor=None, lean=False)
    replacement = MEAL_CHANGE.search(query)

    if re.search(r"빼\s*줘|빼고|제외", query):
        exclusion_clauses = [part.strip() for part in re.split(r"(?<!\d),(?!\d)|[;]", query)
                             if re.search(r"빼\s*줘|빼고|제외", part)]
        for clause in exclusion_clauses:
            try:
                changes, _ = parse_message(clause, names)
            except ValueError:
                raise ValueError("제외할 항목을 확인할 수 있게 ‘우유랑 난류 빼줘’처럼 따로 말해 줘.") from None
            for key in ("allergies", "excluded"):
                if key in changes:
                    updates.setdefault(key, []).extend(changes[key])

    elif "알레르기" in query:
        labels = [label for label in (*FIELDS, *ALIASES) if label in query]
        if not labels or re.search(r"없[어는]|아니|괜찮|취소|해제", query):
            raise ValueError("피해야 할 알레르기는 사이드바에서 직접 선택하거나 해제해 줘.")
        updates["allergies"] = list(dict.fromkeys(ALIASES.get(label, label) for label in labels))

    if not updates and not replacement and not re.search(r"식단|추천|메뉴|짤|짜\s*줘|보완|간식", query):
        raise ValueError("오늘 식단, 하루 예산, 또는 원하는 영양 조건을 알려줘.")
    return updates, "plan", SLOT_KEYS[replacement[1]] if replacement else None
