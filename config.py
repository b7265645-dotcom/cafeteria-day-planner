"""성인 참고 목표와 연구 설정. 진단·처방이 아닌 후보 비교용."""
from pathlib import Path
ROOT = Path(__file__).resolve().parent
NUTRIENT_COLUMNS = {
    "energy_kcal": "Energy", "protein_g": "Protein", "carb_g": "Carbohydrate",
    "fiber_g": "Total Dietary", "calcium_mg": "Calcium", "vitamin_c_mg": "Vitamin C",
    "fat_g": "Fat", "sodium_mg": "Sodium",
}
LABELS = {
    "energy_kcal": "열량(kcal)", "protein_g": "단백질(g)", "carb_g": "탄수화물(g)",
    "fiber_g": "식이섬유(g)", "calcium_mg": "칼슘(mg)", "vitamin_c_mg": "비타민 C(mg)",
    "fat_g": "지방(g)", "sodium_mg": "나트륨(mg)",
}
# 공개 2025 KDRI 요약표에 표기된 19~29세 값.
# 에너지=필요추정량, 식이섬유=충분섭취량, 나머지=권장섭취량.
# 권장섭취량을 개인에게 반드시 필요한 절대 최소량으로 해석하지 않는다.
TARGETS = {
    "남성(19~29세)": {
        "energy_kcal": 2600., "protein_g": 65., "carb_g": 130.,
        "fiber_g": 25., "calcium_mg": 800., "vitamin_c_mg": 100.,
    },
    "여성(19~29세)": {
        "energy_kcal": 1900., "protein_g": 55., "carb_g": 130.,
        "fiber_g": 20., "calcium_mg": 650., "vitamin_c_mg": 100.,
    },
}
TARGET_TYPES = {
    "energy_kcal": "필요추정량", "protein_g": "권장섭취량", "carb_g": "권장섭취량",
    "fiber_g": "충분섭취량", "calcium_mg": "권장섭취량", "vitamin_c_mg": "권장섭취량",
}
TARGET_SOURCE = "https://www.kns.or.kr/data/FileRoom/2025123102020340340.pdf"
OPERATING_COST = 3900.  # 사용자가 제공한 수원대 사례를 재사용. 표준 대학 원가 아님.
DELIVERY_COST = 0.     # 별도 배송비 미반영. 실제 물류비가 0이라는 의미 아님.
SLOT_SLICES = {"breakfast": slice(0, 3), "lunch": slice(3, 8), "dinner": slice(8, 13)}
SLOT_LABELS = {"breakfast": "아침", "lunch": "점심", "dinner": "저녁"}
SOURCE_FILES = ("new_before_change.csv", "new_after_change.csv")
EPS = 1e-9
