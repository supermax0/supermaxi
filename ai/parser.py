import re
from ai.learner import find_city_in_text, find_area_in_text, get_learned_cities

AR_NUMS = "٠١٢٣٤٥٦٧٨٩"
EN_NUMS = "0123456789"
TRANS = str.maketrans(AR_NUMS, EN_NUMS)

def normalize_numbers(text):
    return text.translate(TRANS)

def extract_phone(text):
    text = normalize_numbers(text)
    phones = re.findall(r"07\d{9}", text)
    return phones[0] if phones else None

def extract_name(text):
    for line in text.splitlines():
        l = line.strip()
        if len(l) >= 3 and not extract_phone(l):
            return l
    return None

def extract_address(text):
    keywords = ["شارع", "حي", "منطقة", "قرب", "محلة"]
    for line in text.splitlines():
        if any(k in line for k in keywords):
            return line.strip()
    return None

def extract_city(text):
    """
    استخراج المحافظة من النص باستخدام:
    1. البيانات المتعلمة (الأولوية)
    2. قائمة المحافظات الأساسية
    """
    # أولاً: البحث في البيانات المتعلمة
    learned_city = find_city_in_text(text)
    if learned_city:
        return learned_city
    
    # ثانياً: البحث في قائمة المحافظات الأساسية
    cities = [
        "بغداد", "البصرة", "الموصل", "أربيل", "السليمانية", 
        "كربلاء", "النجف", "بابل", "ديالى", "واسط",
        "ميسان", "ذي قار", "المثنى", "صلاح الدين", "دهوك",
        "كركوك", "الأنبار"
    ]
    
    # إضافة المحافظات المتعلمة للقائمة
    learned_cities = get_learned_cities()
    for city in learned_cities:
        if city not in cities:
            cities.append(city)
    
    text_normalized = text.replace(" ", "").replace("\n", "")
    
    # البحث عن المحافظات في النص
    for city in cities:
        if city in text or city in text_normalized:
            return city
    
    # إذا لم يتم العثور على محافظة محددة، افترض بغداد
    return "بغداد"

def extract_area(text):
    """
    استخراج المنطقة من النص باستخدام البيانات المتعلمة
    """
    # أولاً: البحث في البيانات المتعلمة
    learned_area = find_area_in_text(text)
    if learned_area:
        return learned_area
    
    # ثانياً: البحث باستخدام الكلمات المفتاحية
    area_keywords = ["حي", "منطقة", "محلة", "قرب", "شارع", "مجمع", "سوق", "دوار"]
    
    # البحث في كل سطر
    for line in text.splitlines():
        line_stripped = line.strip()
        if not line_stripped or len(line_stripped) < 3:
            continue
            
        # البحث عن الكلمات المفتاحية
        for keyword in area_keywords:
            if keyword in line_stripped:
                # أخذ الكلمات بعد الكلمة المفتاحية
                parts = line_stripped.split(keyword)
                if len(parts) > 1:
                    area = parts[1].strip()
                    # تنظيف المنطقة من علامات الترقيم والأرقام في البداية
                    area = re.sub(r'^[\d\s\-_.,:;]+', '', area).strip()
                    # أخذ أول 3-4 كلمات كحد أقصى
                    area_words = area.split()[:4]
                    area = ' '.join(area_words).strip()
                    if area and len(area) > 2:
                        return area
                # إذا لم نجد جزء بعد الكلمة المفتاحية، نأخذ السطر كاملاً
                if len(line_stripped) > 3:
                    return line_stripped
    
    # ثالثاً: البحث عن أي سطر يحتوي على كلمات عربية طويلة (قد تكون منطقة)
    for line in text.splitlines():
        line_stripped = line.strip()
        # إذا كان السطر يحتوي على كلمات عربية فقط (بدون أرقام في البداية)
        if line_stripped and len(line_stripped) >= 4:
            # التحقق من أن السطر يحتوي على أحرف عربية
            has_arabic = any('\u0600' <= char <= '\u06FF' for char in line_stripped)
            # التحقق من أن السطر لا يبدأ برقم هاتف
            is_not_phone = not re.match(r'^0?7\d{9}', line_stripped.replace(' ', ''))
            if has_arabic and is_not_phone:
                # تنظيف السطر
                cleaned = re.sub(r'^[\d\s\-_.,:;]+', '', line_stripped).strip()
                if cleaned and len(cleaned) >= 3:
                    return cleaned
    
    return None
