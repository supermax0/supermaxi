import cv2
import numpy as np
import pytesseract
from PIL import Image
import io
import re

# إعدادات محسنة لاستخراج النص العربي مع الأرقام الإنجليزية
# --oem 3: استخدام LSTM OCR Engine (الأفضل)
# --psm 6: افتراض كتلة نص واحدة موحدة
# -c tessedit_char_whitelist: تحديد الأحرف المسموحة (اختياري)
CUSTOM_CONFIG = r'-l ara+eng --oem 3 --psm 6 -c preserve_interword_spaces=1'

def preprocess_image(image_bytes):
    """
    معالجة الصورة وتحسينها لاستخراج أفضل للنص العربي
    """
    # قراءة الصورة
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    img = np.array(img)
    
    # تحويل RGB إلى BGR لـ OpenCV
    if len(img.shape) == 3:
        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    
    # تحويل إلى رمادي
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # تكبير الصورة إذا كانت صغيرة (يحسن دقة OCR)
    height, width = gray.shape
    if height < 300 or width < 300:
        scale = max(300 / height, 300 / width)
        new_width = int(width * scale)
        new_height = int(height * scale)
        gray = cv2.resize(gray, (new_width, new_height), interpolation=cv2.INTER_CUBIC)
    
    # تحسين التباين باستخدام CLAHE (مهم جداً للنص العربي)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    
    # إزالة الضوضاء باستخدام median filter (خفيف)
    gray = cv2.medianBlur(gray, 3)
    
    # تحسين الحواف باستخدام bilateral filter (يحافظ على الحواف)
    gray = cv2.bilateralFilter(gray, 9, 75, 75)
    
    # تحسين الحدة (مهم للنص العربي)
    gaussian = cv2.GaussianBlur(gray, (0, 0), 2.0)
    gray = cv2.addWeighted(gray, 1.5, gaussian, -0.5, 0)
    
    # تحويل إلى أبيض وأسود باستخدام adaptive threshold
    # هذه الطريقة تعمل بشكل أفضل للنص العربي
    thresh = cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, 11, 2
    )
    
    # تنظيف إضافي: إزالة الضوضاء الصغيرة
    kernel = np.ones((2, 2), np.uint8)
    thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
    
    return thresh

def normalize_text(text):
    """
    تطبيع النص: الحفاظ على النص العربي والأرقام الإنجليزية
    """
    if not text:
        return ""
    
    # تنظيف النص مع الحفاظ على جميع الأحرف العربية
    cleaned = []
    for char in text:
        # الحفاظ على جميع الأحرف العربية (Unicode ranges للعربية)
        # 0600-06FF: Basic Arabic
        # 0750-077F: Arabic Supplement
        # 08A0-08FF: Arabic Extended-A
        # FB50-FDFF: Arabic Presentation Forms-A
        # FE70-FEFF: Arabic Presentation Forms-B
        if ('\u0600' <= char <= '\u06FF' or 
            '\u0750' <= char <= '\u077F' or 
            '\u08A0' <= char <= '\u08FF' or 
            '\uFB50' <= char <= '\uFDFF' or 
            '\uFE70' <= char <= '\uFEFF'):
            cleaned.append(char)
        # الحفاظ على الأرقام الإنجليزية (0-9)
        elif char.isdigit():
            cleaned.append(char)
        # الحفاظ على الأحرف الإنجليزية (a-z, A-Z)
        elif char.isalpha() and ord(char) < 128:
            cleaned.append(char)
        # الحفاظ على المسافات وعلامات الترقيم الأساسية
        elif char in ' \n\t.,:;-()[]{}،؛؟':
            cleaned.append(char)
        # إزالة باقي الأحرف غير المرغوبة
    
    text = ''.join(cleaned)
    
    # إزالة المسافات المتعددة (لكن نحتفظ بمسافة واحدة)
    text = re.sub(r' +', ' ', text)
    
    # إزالة الأسطر الفارغة المتعددة
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    text = '\n'.join(lines)
    
    return text.strip()

def extract_text(image_bytes):
    """
    استخراج النص من الصورة مع معالجة محسنة
    يدعم النص العربي مع الأرقام الإنجليزية
    """
    results = []
    
    try:
        # قراءة الصورة الأصلية
        original_img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        original_array = np.array(original_img)
        
        # معالجة الصورة بطرق مختلفة
        processed_images = []
        
        # 1. الصورة الأصلية (RGB)
        processed_images.append(("original_rgb", original_array))
        
        # 2. الصورة المعالجة (من preprocess_image)
        try:
            processed = preprocess_image(image_bytes)
            processed_images.append(("processed", processed))
        except:
            pass
        
        # 3. معالجة بديلة: تحسين التباين فقط
        try:
            gray = cv2.cvtColor(original_array, cv2.COLOR_RGB2GRAY)
            clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
            enhanced = clahe.apply(gray)
            processed_images.append(("enhanced", enhanced))
        except:
            pass
        
        # 4. معالجة بديلة: Otsu threshold
        try:
            gray = cv2.cvtColor(original_array, cv2.COLOR_RGB2GRAY)
            _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            processed_images.append(("otsu", otsu))
        except:
            pass
        
        # 5. معالجة بديلة: Resize للصور الصغيرة
        try:
            gray = cv2.cvtColor(original_array, cv2.COLOR_RGB2GRAY)
            height, width = gray.shape
            if height < 300 or width < 300:
                scale = max(300 / height, 300 / width)
                new_width = int(width * scale)
                new_height = int(height * scale)
                resized = cv2.resize(gray, (new_width, new_height), interpolation=cv2.INTER_CUBIC)
                processed_images.append(("resized", resized))
        except:
            pass
        
        # إعدادات Tesseract محسنة للنص العربي
        configs = [
            # إعدادات محسنة للنص العربي
            r'-l ara+eng --oem 3 --psm 6',  # كتلة نص واحدة موحدة
            r'-l ara+eng --oem 3 --psm 11',  # نص واحد متعدد الأسطر
            r'-l ara+eng --oem 3 --psm 3',   # تلقائي كامل
            r'-l ara+eng --oem 3 --psm 4',   # عمود واحد من النص
            r'-l ara+eng --oem 3 --psm 13',  # نص خام (سطر واحد)
            # إعدادات مع تحسينات إضافية
            r'-l ara+eng --oem 3 --psm 6 -c tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF',
        ]
        
        # جرب كل صورة مع كل إعداد
        for img_name, img_data in processed_images:
            for config in configs:
                try:
                    # تحويل numpy array إلى PIL Image إذا لزم الأمر
                    if isinstance(img_data, np.ndarray):
                        if len(img_data.shape) == 2:  # Grayscale
                            pil_img = Image.fromarray(img_data)
                        else:  # RGB
                            pil_img = Image.fromarray(cv2.cvtColor(img_data, cv2.COLOR_BGR2RGB))
                    else:
                        pil_img = img_data
                    
                    text = pytesseract.image_to_string(pil_img, config=config)
                    if text and text.strip():
                        # حساب جودة النص (عدد الأحرف العربية)
                        arabic_chars = sum(1 for c in text if '\u0600' <= c <= '\u06FF')
                        results.append({
                            'text': text,
                            'arabic_count': arabic_chars,
                            'length': len(text.strip()),
                            'config': config,
                            'image': img_name
                        })
                except Exception as e:
                    continue
        
        # اختيار أفضل نتيجة (الأكثر أحرف عربية)
        if results:
            # ترتيب حسب عدد الأحرف العربية أولاً، ثم الطول
            results.sort(key=lambda x: (x['arabic_count'], x['length']), reverse=True)
            best_result = results[0]['text']
        else:
            # إذا لم نحصل على نتائج، جرب طريقة بسيطة
            try:
                gray = cv2.cvtColor(original_array, cv2.COLOR_RGB2GRAY)
                pil_img = Image.fromarray(gray)
                best_result = pytesseract.image_to_string(pil_img, config=r'-l ara+eng --oem 3 --psm 6')
            except:
                best_result = ""
        
        # تطبيع النص (الحفاظ على العربي والأرقام الإنجليزية)
        normalized_text = normalize_text(best_result)
        
        return normalized_text
        
    except Exception as e:
        # في حالة الخطأ، جرب معالجة أبسط
        try:
            img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            img_array = np.array(img)
            gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
            
            # تحسين بسيط
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            gray = clahe.apply(gray)
            
            pil_img = Image.fromarray(gray)
            text = pytesseract.image_to_string(pil_img, config=r'-l ara+eng --oem 3 --psm 6')
            return normalize_text(text)
        except Exception as e2:
            return ""
