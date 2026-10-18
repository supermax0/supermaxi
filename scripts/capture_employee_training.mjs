/** Capture the actual desk templates at phone size, with synthetic fixture data.
 * Start tests/support/employee_training_preview.py first. No production server is used.
 * Rerun when the desk layout changes to refresh screenshots and target coordinates.
 */
import { chromium } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = fileURLToPath(new URL("../", import.meta.url));
const output = path.join(root, "static/employee_desk/training");
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true, channel: "chrome" });
const page = await browser.newPage({ viewport: { width: 390, height: 760 }, deviceScaleFactor: 1, locale: "ar" });
const lessons = { login: [], messages: [], reply: [], booking: [] };
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
// Keep the capture entirely local, including fonts and notification services.
await page.route(/https?:\/\/(?!127\.0\.0\.1:5099)/, (route) => route.abort());
async function take(module, image, selector, title, description, task, hint) {
  const node = page.locator(selector).first();
  await node.waitFor({ state: "visible" });
  await page.addStyleTag({ content: "*, *::before, *::after { animation: none !important; transition: none !important; }" });
  await node.scrollIntoViewIfNeeded();
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  const box = await node.boundingBox();
  if (!box || box.x < -1 || box.y < -1 || box.x + box.width > 391 || box.y + box.height > 761) throw new Error(`Target outside phone: ${selector} ${JSON.stringify(box)}`);
  await page.screenshot({ path: path.join(output, image), animations: "disabled" });
  const pct = (value, size) => Math.round(value / size * 10000) / 100;
  lessons[module].push({ image, title, description, task, hint,
    target: { x: pct(box.x, 390), y: pct(box.y, 760), width: pct(box.width, 390), height: pct(box.height, 760) } });
}
try {
  await page.goto("http://127.0.0.1:5099/employee-desk/login");
  await take("login", "login-company.png", '[name="tenant_slug"]', "ابدأ بمعرّف الشركة", "افتح رابط مكتب الموظف اللي يوصلك من الإدارة. معرّف الشركة يحدد النظام اللي راح تدخل عليه؛ إذا الرابط خاص بالشركة، يطلع معبّأ تلقائياً.", "اضغط على حقل معرّف الشركة بالصورة.", "أول حقل داخل بطاقة الدخول، تحت عنوان «معرّف الشركة». لا تغيّر المعرّف إذا الإدارة محددته.");
  await take("login", "login-username.png", '[name="username"]', "اكتب اسم المستخدم الخاص بيك", "استخدم الاسم اللي أعطتك إياه الإدارة. كل موظف عنده حسابه حتى تنربط المحادثات والحجوزات بالشخص الصحيح.", "حدد مكان كتابة اسم المستخدم.", "الحقل الثاني، بين معرّف الشركة وكلمة المرور.");
  await take("login", "login-password.png", '[name="password"]', "كلمة المرور تبقى إلك", "اكتب كلمة مرورك بالحقل المخصص. لا تشاركها ويّا أحد، وإذا ناسيها ارجع للإدارة.", "حدد حقل كلمة المرور.", "الحقل الثالث يخفي الحروف اللي تكتبها.");
  await take("login", "login-submit.png", '#ed-login button', "سجّل دخولك", "بعد ما تراجع الشركة واسمك وكلمة مرورك، اضغط تسجيل الدخول. إذا يطلع خطأ، اقرأه وراجع البيانات أو الصلاحية ويّا الإدارة.", "اضغط زر تسجيل الدخول بالصورة.", "الزر العنّابي العريض أسفل حقول الدخول.");
  await page.goto("http://127.0.0.1:5099/employee-desk");
  await page.locator("#ed-inbox .ed-thread").waitFor({ state: "attached" });
  await take("messages", "messages-tab.png", '.ed-tabs [data-pane="ed-pane-inbox"]', "روح لقائمة الرسائل", "من الشريط السفلي تكدر تتنقل بين الرئيسية والرسائل والطلبات والزبائن والحساب. شارة الرسائل تنبهك للمحادثات اللي تنتظر رد.", "اضغط تبويب الرسائل بأسفل الهاتف.", "أيقونة المحادثة، ثاني تبويب من جهة اليمين.");
  await page.locator('.ed-tabs [data-pane="ed-pane-inbox"]').click();
  await take("messages", "messages-thread.png", '#ed-inbox .ed-thread', "افتح محادثة الزبون", "القائمة تعرض الاسم وآخر رسالة وحالة المحادثة. اقرأ المعاينة، وانتبه للمحادثات المتأخرة أو اللي بانتظار الرد.", "اضغط محادثة زبون التدريب.", "بطاقة المحادثة تحت البحث والفلاتر.");
  await page.locator("#ed-inbox .ed-thread").click();
  await page.locator(".ed-bubble-txt").waitFor();
  await page.locator("#ed-chat-input").blur();
  await take("reply", "reply-input.png", '#ed-chat-input', "اقرأ، وبعدها اكتب ردك", "راجع اسم الزبون ورسائله قبل الرد. جاوب على سؤاله بمعلومة من الكتالوج، واسأل عن التفاصيل اللي تحتاجها حتى تكمل.", "حدد مكان كتابة الرد.", "حقل «اكتب ردك…» أسفل المحادثة.");
  await page.locator("#ed-chat-input").fill("أهلاً وسهلاً، خل أتأكدلك من سعر المنتج ومواصفاته من الكتالوج.");
  await page.locator("#ed-chat-input").blur();
  await take("reply", "reply-send.png", '#ed-chat-send', "راجع الرد، واضغط إرسال", "اقرأ نصك مرة ثانية: المنتج المقصود صحيح؟ السعر مؤكد؟ ماكو وعد غير متأكد منه؟ بعدها اضغط سهم الإرسال، وانتظر نتيجة النظام.", "اضغط سهم الإرسال بالصورة.", "الزر العنّابي اللي يحمل سهم، داخل شريط كتابة الرد.");
  await take("reply", "reply-quick.png", '#ed-quick-open', "انتبه للردود السريعة", "زر البرق يفتح الردود الجاهزة. مهم تعرف أن الضغط على الرد بالقائمة يرسله مباشرة؛ تأكد من ملاءمته للزبون قبل الضغط عليه.", "حدد زر الردود السريعة.", "أيقونة البرق على طرف شريط الرد.");
  await take("booking", "booking-open.png", '#ed-book-from-chat', "ابدأ الحجز من المحادثة", "بعد ما يوافق الزبون وتوضح التفاصيل، اضغط حجز من داخل المحادثة حتى تكمل تسجيل الطلب.", "اضغط زر حجز أعلى المحادثة.", "زر «حجز» يم اسم الزبون وزر التحويل.");
  await page.locator("#ed-book-from-chat").click();
  await take("booking", "booking-customer.png", '#ed-cust-q', "دور على الزبون أولاً", "ابحث بالاسم أو رقم الهاتف حتى تتجنب تسجيل نفس الزبون مرتين. إذا موجود اختَره من النتائج، وإذا جديد استخدم «زبون جديد».", "حدد حقل البحث عن الزبون.", "الحقل المكتوب بيه «الاسم أو رقم الهاتف» ضمن نافذة الحجز.");
  await take("booking", "booking-new.png", '#ed-cust-new-toggle', "إذا الزبون جديد، سجّل بياناته", "تأكد من الاسم ورقم الهاتف والمحافظة والعنوان وأقرب نقطة دالة. لا تستخدم معلومات ناقصة أو معلومات زبون ثاني.", "اضغط زر زبون جديد بالصورة.", "الزر الصغير بجانب حقل البحث عن الزبون.");
  await page.locator("#ed-cust-new-toggle").click();
  await take("booking", "booking-fields.png", '#ed-nc-phone', "راجع الهاتف والعنوان", "نموذج الزبون الجديد بيه الاسم والهاتف والمحافظة والعنوان. اكتب البيانات مثل ما أكدها الزبون، وبعد المراجعة اضغط حفظ الزبون.", "حدد مكان كتابة رقم الهاتف.", "حقل رقم الهاتف داخل نموذج «زبون جديد»؛ بعده المحافظة والعنوان.");
  await page.locator("#ed-nc-name").fill("زبون التدريب");
  await page.locator("#ed-nc-phone").fill("07700000000");
  await page.locator("#ed-nc-address").fill("عنوان تدريبي — قرب نقطة دالة");
  await page.locator("#ed-nc-save").click();
  await page.locator("#ed-cust-picked").waitFor();
  await page.locator("#ed-toast").waitFor({ state: "hidden" });
  await take("booking", "booking-product.png", '#ed-prod-q', "ابحث عن المنتج المطلوب", "اكتب جزء من اسم المنتج أو رمزه. راجع اسم المنتج وسعره، واضغط النتيجة الصحيحة لإضافتها للسلة.", "حدد حقل البحث عن المنتج.", "الحقل المكتوب بيه «ابحث عن منتج…» بعد بطاقة الزبون المختار.");
  await page.locator("#ed-prod-q").fill("منتج");
  await page.locator("#ed-prod-results [data-product]").waitFor();
  await take("booking", "booking-select.png", '#ed-prod-results [data-product]', "أضف المنتج من النتائج", "هنا يطلع اسم المنتج والسعر المسجل. اختَر النتيجة الصحيحة؛ تكرار الضغط على نفس المنتج يزيد الكمية، فراجع السلة.", "اضغط نتيجة المنتج التدريبي.", "صف المنتج أسفل حقل البحث، والسعر ظاهر بجانبه. هذا السعر مثال توضيحي بالصورة.");
  await page.locator("#ed-prod-results [data-product]").click();
  await page.locator(".ed-line-color").selectOption("أسود");
  await take("booking", "booking-cart.png", '#ed-cart .ed-line', "راجع السلة واللون والكمية", "تأكد من المنتج، الكمية، واللون المطلوب إذا موجود. راجع المجموع، وسجّل أي ملاحظة واضحة بعد تأكيدها ويّا الزبون.", "حدد سطر المنتج داخل السلة.", "داخل السلة تشوف اسم المنتج واختيار اللون وأزرار زيادة ونقصان الكمية.");
  await take("booking", "booking-confirm.png", '#ed-confirm', "ثبّت الحجز بعد المراجعة", "تأكد من موافقة الزبون وصحة بياناته والمنتج والسعر النهائي، وبعدها اضغط «احجز الطلب» مرة وحدة. انتظر رسالة نجاح النظام؛ إذا صار خطأ راجع النتيجة قبل إعادة المحاولة.", "اضغط مكان تأكيد الحجز بالصورة.", "الزر العنّابي بأسفل نافذة الحجز، يم مجموع الطلب. هنا مجرد صورة تدريبية.");
  if (errors.length) throw new Error(errors.join("\n"));
  await writeFile(path.join(output, "lessons.json"), JSON.stringify(lessons, null, 2) + "\n", "utf8");
  console.log(`Captured ${Object.values(lessons).flat().length} screenshots from actual templates; all targets inside viewport.`);
} finally { await browser.close(); }
