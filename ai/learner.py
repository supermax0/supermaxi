import json
from pathlib import Path
import re

DATA_FILE = Path("ai/learned.json")
CITIES_FILE = Path("ai/learned_cities.json")
AREAS_FILE = Path("ai/learned_areas.json")

def load_json_file(file_path, default=None):
    """تحميل ملف JSON أو إنشاء واحد جديد"""
    if default is None:
        default = {}
    if file_path.exists():
        try:
            content = file_path.read_text(encoding="utf-8")
            if not content.strip():
                return default
            return json.loads(content)
        except Exception:
            return default
    return default

def save_json_file(file_path, data):
    """حفظ بيانات في ملف JSON"""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

def learn(raw_text, corrected_text):
    """تعلم من النص الخام والنص المصحح"""
    data = load_json_file(DATA_FILE, default=[])
    if not isinstance(data, list):
        data = []

    data.append({
        "raw": raw_text,
        "corrected": corrected_text
    })

    save_json_file(DATA_FILE, data)

def _ensure_cities_dict(obj):
    """تحويل أي صيغة قديمة (list) إلى dict حديث."""
    if isinstance(obj, dict):
        return obj
    if isinstance(obj, list):
        converted = {}
        for entry in obj:
            if isinstance(entry, dict):
                city = entry.get("city") or entry.get("name")
                patterns = entry.get("raw_patterns") or entry.get("patterns") or []
                count = entry.get("count", 0)
                if city:
                    converted[city] = {
                        "patterns": patterns if isinstance(patterns, list) else [],
                        "variations": [],
                        "count": count,
                        "last_learned": None
                    }
        return converted
    # غير متوقع
    return {}

def _ensure_areas_dict(obj):
    """تحويل أي صيغة قديمة (list) إلى dict حديث."""
    if isinstance(obj, dict):
        return obj
    if isinstance(obj, list):
        converted = {}
        for entry in obj:
            if isinstance(entry, dict):
                area = entry.get("area") or entry.get("name")
                patterns = entry.get("raw_patterns") or entry.get("patterns") or []
                count = entry.get("count", 0)
                if area:
                    converted[area] = {
                        "patterns": patterns if isinstance(patterns, list) else [],
                        "variations": [],
                        "count": count,
                        "last_learned": None
                    }
        return converted
    return {}

def learn_city(raw_text, city_name):
    """تعلم محافظة جديدة من النص الخام"""
    if not city_name or city_name.strip() == "":
        return
    
    city_name = city_name.strip()
    cities_data = _ensure_cities_dict(load_json_file(CITIES_FILE, default={}))
    
    # البحث عن المحافظة في النص الخام
    raw_normalized = raw_text.replace(" ", "").replace("\n", "").lower()
    raw_with_spaces = raw_text.lower()
    
    # حفظ المحافظة مع أنماط مختلفة من النص
    if city_name not in cities_data:
        cities_data[city_name] = {
            "patterns": [],
            "variations": [],  # أشكال مختلفة للمحافظة
            "count": 0,
            "last_learned": None
        }
    
    # إضافة النص الخام كأنماط للتعلم (بدون مسافات)
    if raw_normalized and raw_normalized not in cities_data[city_name]["patterns"]:
        cities_data[city_name]["patterns"].append(raw_normalized)
    
    # إضافة النص مع المسافات
    if raw_with_spaces and raw_with_spaces not in cities_data[city_name]["patterns"]:
        cities_data[city_name]["patterns"].append(raw_with_spaces)
    
    # إضافة أجزاء من النص التي تحتوي على المحافظة
    if city_name in raw_text:
        # استخراج جزء النص حول المحافظة
        city_index = raw_text.lower().find(city_name.lower())
        if city_index != -1:
            start = max(0, city_index - 10)
            end = min(len(raw_text), city_index + len(city_name) + 10)
            context = raw_text[start:end].lower()
            if context not in cities_data[city_name]["patterns"]:
                cities_data[city_name]["patterns"].append(context)
    
    cities_data[city_name]["count"] += 1
    from datetime import datetime
    cities_data[city_name]["last_learned"] = datetime.now().isoformat()
    
    save_json_file(CITIES_FILE, cities_data)

def learn_area(raw_text, area_name):
    """تعلم منطقة جديدة من النص الخام"""
    if not area_name or area_name.strip() == "":
        return
    
    area_name = area_name.strip()
    areas_data = _ensure_areas_dict(load_json_file(AREAS_FILE, default={}))
    
    # البحث عن المنطقة في النص الخام
    raw_normalized = raw_text.replace(" ", "").replace("\n", "").lower()
    raw_with_spaces = raw_text.lower()
    
    # حفظ المنطقة مع أنماط مختلفة من النص
    if area_name not in areas_data:
        areas_data[area_name] = {
            "patterns": [],
            "variations": [],  # أشكال مختلفة للمنطقة
            "count": 0,
            "last_learned": None
        }
    
    # إضافة النص الخام كأنماط للتعلم (بدون مسافات)
    if raw_normalized and raw_normalized not in areas_data[area_name]["patterns"]:
        areas_data[area_name]["patterns"].append(raw_normalized)
    
    # إضافة النص مع المسافات
    if raw_with_spaces and raw_with_spaces not in areas_data[area_name]["patterns"]:
        areas_data[area_name]["patterns"].append(raw_with_spaces)
    
    # إضافة أجزاء من النص التي تحتوي على المنطقة
    if area_name in raw_text:
        # استخراج جزء النص حول المنطقة
        area_index = raw_text.lower().find(area_name.lower())
        if area_index != -1:
            start = max(0, area_index - 15)
            end = min(len(raw_text), area_index + len(area_name) + 15)
            context = raw_text[start:end].lower()
            if context not in areas_data[area_name]["patterns"]:
                areas_data[area_name]["patterns"].append(context)
    
    areas_data[area_name]["count"] += 1
    from datetime import datetime
    areas_data[area_name]["last_learned"] = datetime.now().isoformat()
    
    save_json_file(AREAS_FILE, areas_data)

def get_learned_cities():
    """الحصول على قائمة المحافظات المتعلمة"""
    cities_data = _ensure_cities_dict(load_json_file(CITIES_FILE, default={}))
    return list(cities_data.keys())

def get_learned_areas():
    """الحصول على قائمة المناطق المتعلمة"""
    areas_data = _ensure_areas_dict(load_json_file(AREAS_FILE, default={}))
    return list(areas_data.keys())

def find_city_in_text(text, learned_cities=None):
    """البحث عن محافظة في النص باستخدام البيانات المتعلمة"""
    if learned_cities is None:
        learned_cities = get_learned_cities()
    
    cities_data = _ensure_cities_dict(load_json_file(CITIES_FILE, default={}))
    text_normalized = text.replace(" ", "").replace("\n", "").lower()
    text_with_spaces = text.lower()
    
    # ترتيب المحافظات حسب عدد مرات التعلم (الأكثر تعلمًا أولاً)
    sorted_cities = sorted(
        cities_data.items(),
        key=lambda x: x[1].get("count", 0),
        reverse=True
    )
    
    # البحث في المحافظات المتعلمة
    for city, data in sorted_cities:
        city_lower = city.lower()
        
        # 1. البحث المباشر في النص
        if city_lower in text_normalized or city_lower in text_with_spaces or city in text:
            return city
        
        # 2. البحث في الأنماط المتعلمة
        patterns = data.get("patterns", [])
        for pattern in patterns:
            if pattern and len(pattern) > 3:
                # البحث في النص بدون مسافات
                if pattern in text_normalized:
                    return city
                # البحث في النص مع المسافات
                if pattern in text_with_spaces:
                    return city
                # البحث الجزئي (60% من النمط)
                if len(pattern) > 5:
                    min_match = max(3, int(len(pattern) * 0.6))
                    for i in range(len(text_normalized) - min_match + 1):
                        substring = text_normalized[i:i+min_match]
                        if substring in pattern or pattern in substring:
                            return city
    
    return None

def find_area_in_text(text, learned_areas=None):
    """البحث عن منطقة في النص باستخدام البيانات المتعلمة"""
    if learned_areas is None:
        learned_areas = get_learned_areas()
    
    areas_data = _ensure_areas_dict(load_json_file(AREAS_FILE, default={}))
    text_normalized = text.replace(" ", "").replace("\n", "").lower()
    text_with_spaces = text.lower()
    
    # ترتيب المناطق حسب عدد مرات التعلم (الأكثر تعلمًا أولاً)
    sorted_areas = sorted(
        areas_data.items(),
        key=lambda x: x[1].get("count", 0),
        reverse=True
    )
    
    # البحث في المناطق المتعلمة
    for area, data in sorted_areas:
        area_lower = area.lower()
        
        # 1. البحث المباشر في النص
        if area_lower in text_normalized or area_lower in text_with_spaces or area in text:
            return area
        
        # 2. البحث في الأنماط المتعلمة
        patterns = data.get("patterns", [])
        for pattern in patterns:
            if pattern and len(pattern) > 3:
                # البحث في النص بدون مسافات
                if pattern in text_normalized:
                    return area
                # البحث في النص مع المسافات
                if pattern in text_with_spaces:
                    return area
                # البحث الجزئي (60% من النمط)
                if len(pattern) > 5:
                    min_match = max(3, int(len(pattern) * 0.6))
                    for i in range(len(text_normalized) - min_match + 1):
                        substring = text_normalized[i:i+min_match]
                        if substring in pattern or pattern in substring:
                            return area
    
    return None
