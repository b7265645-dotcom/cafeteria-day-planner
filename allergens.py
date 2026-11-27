"""Menu-level dataset labels for cafeteria research recommendations."""
import json

FIELDS = (
    "밀", "쌀", "메밀", "감자", "대두", "땅콩", "들깨", "참깨", "씨앗",
    "돼지", "오리", "닭", "기타가금류", "소", "난류", "우유", "붉은살생선", "흰살생선",
    "장어", "멸치", "게", "새우", "가재", "조개,꼬막", "굴", "홍합,담치", "오징어", "문어",
    "낙지", "고둥", "소라", "전복", "오이", "마늘", "샐러리", "당근", "브로콜리",
    "양파", "겨자", "후추", "토마토", "체리", "자두", "키위", "바나나", "사과", "배",
    "코코넛", "복숭아", "메론", "수박", "시트러스", "망고", "아황산류", "견과류", "땅콩+견과류",
)
RECORD_COLUMNS = ("allergens_present", "allergens_unknown")


def menu_labels(nutrition):
    labels = {}
    for menu, values in zip(nutrition.index, nutrition.reindex(columns=FIELDS).itertuples(index=False, name=None)):
        present = {name for name, value in zip(FIELDS, values) if str(value) in {"1", "1.0"}}
        unknown = {name for name, value in zip(FIELDS, values) if str(value) not in {"0", "0.0", "1", "1.0"}}
        if present.intersection({"땅콩", "견과류"}):
            present.add("땅콩+견과류")
        if "땅콩+견과류" in present and not present.intersection({"땅콩", "견과류"}):
            unknown.update(("땅콩", "견과류"))
        labels[menu] = present, unknown
    return labels


def meal_labels(menus, labels):
    present, unknown = set(), set()
    for menu in menus:
        if menu == "empty":
            continue
        menu_present, menu_unknown = labels.get(menu, ((), FIELDS))
        present.update(menu_present)
        unknown.update(menu_unknown)
    return {
        "allergens_present": json.dumps(sorted(present), ensure_ascii=False),
        "allergens_unknown": json.dumps(sorted(unknown), ensure_ascii=False),
    }


def filter_meals(meals, exclusions):
    blocked = set(exclusions)
    if blocked - set(FIELDS):
        raise ValueError("원본 DB에서 지원하는 알레르기 항목을 선택하세요.")
    if not blocked:
        return meals
    if not set(RECORD_COLUMNS).issubset(meals.columns):
        raise ValueError("알레르기 표기 열이 없습니다. python prepare.py를 실행하세요.")

    def eligible(values):
        try:
            records = [json.loads(value) for value in values]
        except (TypeError, ValueError):
            return False
        return all(
            isinstance(record, list) and all(item in FIELDS for item in record)
            and not blocked.intersection(record)
            for record in records
        )

    keep = [eligible(values) for values in meals[list(RECORD_COLUMNS)].itertuples(index=False, name=None)]
    return meals.loc[keep]
