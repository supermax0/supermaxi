تعليمات عامة للسلوك (System / Assistant behavior)

اعمل كمهندس برمجيات وخبير بنية نظم (Software Architect) + مهندس DevOps + مهندس أمن + مصمم واجهات UI/UX.

كن دقيقاً ومباشراً: أعطِ مخططاً هندسياً، مخططات قواعد بيانات، جميع الملفات البرمجية الأساسية (frontend, backend, infra), سكربتات التشغيل، وملفات التهيئة (Docker, docker-compose, Kubernetes manifests, GitHub Actions).

اجعل المخرجات قابلة للنسخ واللصق مباشرة — كل كود داخل blocks للـ Markdown. لا تسأل أسئلة توضيحية. إذا احتجت افتراضات معقولة فاذكرها صراحة ثم تابع.

اعالج الأخطاء، حالات الحافة، وإدارة الأحجام والمزامنة (idempotency). أدرج اختبارات وحدات (unit tests) ومجموعة اختبارات تكاملية (integration tests) أساسية.

التزم بممارسات الأمن: لا تسجل مفاتيح API، استخدم متغيرات بيئية، تحقق من صلاحية المدخلات، ضع حدود سرعة rate limits، واذكر سياسات تسليم البيانات والنسخ الاحتياطي.

قسّم النتائج إلى ملفات/مجلدات واضحة ومسمّاة، وقدم أمر واحد لبناء المشروع محليًا وأمر لنشره على VPS أو باستخدام Docker Compose / Kubernetes.

هدف النظام المطلوب

بناء منصة AI Automation + Workflow Builder (مصغرة n8n) مع تكامل OpenAI Chat (Agents) ووكلاء (Agents) جاهزين لردود Telegram, Messenger, Facebook Comments, WhatsApp، مع:

محرر سير عمل بصري (React + ReactFlow).

محرك تنفيذ Workflows (Backend: Node.js أو Python — اختر Node.js لأنك طلبت Node بالذات).

وحدات (Nodes) قابلة للسحب (Triggers, AI Agent, Condition, SQL Save, Reply).

تخزين SQL للعلاقات (customers, orders, products، إلخ) + Vector DB (Qdrant) للمعرفة/الكتالوج.

إمكانية رفع كتالوج منتجات (CSV/Excel/JSON) وتحويله إلى embeddings + استعلام عبر RAG.

مولّد Workflows تلقائي من نص المستخدم (AI Builder) — "write a prompt and the system builds workflow and wires nodes".

واجهة إعدادات للتوصيل بمفاتيح OpenAI و Telegram و Facebook و WhatsApp.

آلية حفظ الحالة (state) لكل محادثة وجلسة agent.

سجلّ (logs) وتنبيهات (alerts) وواجهة Orders/Customers.

مخرجات متوقعة من الـ AI (Deliverables)

اطلب من النموذج أن يولد كل ما يلي بالترتيب وبصيغة قابلة للنسخ:

ملف README.md يشرح المشروع وطرق التشغيل والنشر.

هيكل المشروع (tree) مفصل.

ملفات الشيفرة:

frontend: React + ReactFlow + صفحات: Canvas, Orders, Customers, Knowledge, AI Builder (chat).

backend: Node.js (Express/ Fastify) أو NestJS + خدمات: workflow-engine, integrations (telegram, fb, whatsapp), ai-agent (OpenAI wrapper), db-service.

سكربتات ingestion للكتالوج (CSV/Excel -> SQL + embeddings).

scripts: migrations, seeders.

ملفات infra:

Dockerfile لكل خدمة، وdocker-compose.yml.

(اختياري) k8s/ manifests (Deployment, Service, Ingress, Secrets).

GitHub Actions CI pipeline (build, test, image push).

ملفات config/ENV المثال .env.example.

اختبارات أساسية (jest/mocha للـ Node، وReact Testing Library للـ front).

وثيقة API (OpenAPI / Swagger) مختصرة لنقاط النهاية الحرجة (webhooks, workflows, orders).

ملف PROMPTS/AGENT_TEMPLATES: كل القوالب البرمجية للـ prompts التي سيستخدمها الـ AI Agent (extractor, routing, confirmation, fallback).

مثال Workflow JSON جاهز يمكن استيراده إلى الـ Canvas (Telegram sales flow).

دليل نشر خطوة بخطوة (local dev، production عبر Docker Compose وKubernetes).

فرضيات معقولة (إن لم تُعطَ تفاصيل)

استخدام Node.js 18+ وTypeScript في backend.

قاعدة بيانات PostgreSQL.

Vector DB: Qdrant (أو بديل Chroma/Qdrant).

OpenAI API متاح عبر مفتاح في متغير بيئي OPENAI_API_KEY.

سير عمل الرسائل عبر webhooks (Telegram Bot API webhook). للـ WhatsApp/Facebook يستخدم Facebook Graph API/WhatsApp Cloud API.

التخزين الثابت للملفات (catalogs) عبر uploads/ محلي أو S3.

تعليمات دقيقة لكيفية تصميم الـ AI Agent (البُنى والبرومبت)

ضع أقساماً منفصلة لكل دور للـ AI داخل النظام، مع قالب برومبت لكل وظيفة:

1) Router Agent (يقرّر أي Agent يعالج الرسالة)

قالب برومبت (Router):

You are Router Agent. Input: {message_text, metadata:{channel, user_id, last_messages, user_profile}}.
Tasks:
1) Classify intent: [order, question, support, complaint, unknown]
2) If order -> route to Sales Agent. If question about product details -> route to Knowledge Agent. If complaint -> Support Agent.
3) Extract confidence 0-1.
Output JSON:
{ "intent":"order", "route":"sales_agent", "confidence":0.95, "reason":"contains keywords ..."}
Constraints: only output valid JSON.
2) Extractor Agent (يستخرج الحقول)

قالب برومبت (Extractor):

You are Extractor. Input message and context. Extract: name, phone, address, product_name, quantity, preferred_time, any payment preference.
Rules:
- Normalize phone to +country format if possible.
- If field missing, output null but suggest follow-up question.
Output JSON with fields and follow_up_questions array if needed.
3) Knowledge + RAG Agent (للأسئلة عن المنتجات)

قالب برومبت (RAG answer):

Use retrieval results (top K passages) + the user message.
Follow this structure:
- If retrieval confident -> produce short answer + one-sentence summary of source (source id).
- If ambiguous -> ask clarifying Q.
- If user asks price/stock -> query products table (provide DB snippet).
Output: {answer_text, source:[...], actions:[{type:"query_db", sql:"..."}] }
4) Sales Agent (إدارة الحوار لجمع بيانات الطلب)

قالب برومبت (Sales flow):

Goal: convert to order. Use extraction, confirm required fields [name, phone, address, product, quantity]. 
If missing fields, ask one question at a time. After collecting, confirm full order summary and ask to confirm (yes/no).
On confirmation -> return action: { type: "create_order", payload: {...} }
Tone: concise, local language Arabic (MSA/iraqi dialect optional).
5) Fallback & Safety
If message appears to contain PII beyond needed or harmful content -> refuse and log.
Implement rate-limiting and anti-spam heuristics: >X messages/min => require captcha/manual review.
قالب الـ Workflow JSON (مثال قابل للاستيراد)

اطلب من الـ AI أن يولّد مثالًا جاهزًا:

{
  "id":"flow_telegram_sales_v1",
  "nodes":[
    {"id":"n1","type":"telegram_trigger","config":{"bot_token_env":"TELEGRAM_BOT_TOKEN"}},
    {"id":"n2","type":"router_agent","config":{}},
    {"id":"n3","type":"ai_extractor","config":{}},
    {"id":"n4","type":"condition","config":{"expr":"intent == 'order'"}},
    {"id":"n5","type":"collect_fields","config":{"fields":["name","phone","address","product","quantity"]}},
    {"id":"n6","type":"sql_save_order","config":{"table":"orders"}},
    {"id":"n7","type":"telegram_reply","config":{"template":"order_confirm"}}
  ],
  "connections":[
    {"from":"n1","to":"n2"},
    {"from":"n2","to":"n3"},
    {"from":"n3","to":"n4"},
    {"from":"n4","on":"true","to":"n5"},
    {"from":"n5","to":"n6"},
    {"from":"n6","to":"n7"}
  ]
}
مخطط قاعدة البيانات الأساسية (SQL schema)

اطلب توليد SQL migration لـ PostgreSQL:

-- customers
CREATE TABLE customers (
  id SERIAL PRIMARY KEY,
  name TEXT,
  phone TEXT UNIQUE,
  address TEXT,
  created_at TIMESTAMP DEFAULT now()
);

-- products
CREATE TABLE products (
  id SERIAL PRIMARY KEY,
  sku TEXT UNIQUE,
  name TEXT,
  description TEXT,
  price NUMERIC,
  stock INTEGER DEFAULT 0,
  created_at TIMESTAMP DEFAULT now()
);

-- orders
CREATE TABLE orders (
  id SERIAL PRIMARY KEY,
  customer_id INTEGER REFERENCES customers(id),
  product_id INTEGER REFERENCES products(id),
  quantity INTEGER,
  total_price NUMERIC,
  status TEXT,
  channel TEXT,
  created_at TIMESTAMP DEFAULT now()
);

-- conversation_state
CREATE TABLE conversation_state (
  id SERIAL PRIMARY KEY,
  channel TEXT,
  user_id TEXT,
  state JSONB,
  updated_at TIMESTAMP DEFAULT now()
);
تكامل OpenAI (كيفية استدعاءه بشكل آمن)

استخدم مكتبة OpenAI الرسمية (nodejs).

استخدم نموذج الـ chat completions مع RAG pattern:

استخرج embeddings للنص (البحث) عبر openai.embeddings.create.

استخدم Qdrant للبحث أعلى تشابه.

بني prompt مدمج: system prompt ثابت + retrieved contexts + user message.

قيِّم الطول وتقطيع contexts لتجنب تجاوز التوكن.

نموذج طلب للـ API (pseudo-code):

const embedding = await openai.embeddings.create({ model: "text-embedding-3-small", input: query });
const results = await qdrant.search(embedding);
const systemPrompt = "..."; // use templates above
const chat = await openai.chat.completions.create({
  model: "gpt-5-mini", 
  messages: [
    { role: "system", content: systemPrompt },
    { role: "user", content: buildUserWithContexts(results, userMessage) }
  ],
  max_tokens: 800
});
أمان وخصوصية وممارسات إنتاجية

ENV: OPENAI_API_KEY, TELEGRAM_BOT_TOKEN, DATABASE_URL, QDRANT_URL, QDRANT_API_KEY في .env.

Rate limiting على webhooks (per user & per IP).

Input validation: sanitize all incoming text before storing.

PII handling: وضع سياسة تخزين مشددة، وميزة حذف بيانات (GDPR-like).

Logging: سجلّ الأحداث المهمة مع مستوى تحسس (do not log raw messages with PII).

Backups: daily DB dump + snapshot Qdrant.

CI/CD وDeployment مختصر

GitHub Actions: build, test, build Docker images, push to registry.

Docker Compose (local + prod) مع Postgres + Qdrant + backend + frontend.

For scale: Kubernetes manifests + HPA, use a managed DB and Qdrant cloud or self-hosted with persistence.

اختبارات ومقاييس جودة

Unit tests: business logic parsers, extractor tests (few-shot examples), db service.

Integration tests: simulate Telegram webhook -> run workflow -> check DB insert.

E2E: Playwright for frontend (drag & drop node, import JSON, save flow).

متطلبات الواجهة Visual Builder (React + ReactFlow)

Canvas with node palette, draggable nodes.

Node configuration panel (on select).

Save/Load flows (JSON endpoint).

Import sample flow button (use the provided Telegram flow).

Live test panel (simulate a message to test flow).

قالب README.md مختصر (اطلب من النموذج توليده)

وصف المشروع، متطلبات، خطوات التشغيل محليًا (ENV, docker-compose up), أمثلة curl للويبهوك، وكيفية استيراد الـ flow.

أمر تنفيذي واحد للتشغيل المحلي (مثال)
# بعد استنساخ الريبو
cp .env.example .env
# ضع المفاتيح
docker-compose up --build
# http://localhost:3000 -> frontend
# http://localhost:4000 -> backend
نقاط إضافية قوية لطلبها من الـ AI أثناء التنفيذ

أدرج explainability لأسباب كل رد (لماذا تم توجيه العميل).

احتفظ بسجل للتصحيحات اليدوية (human overrides) لتدريب لاحق.

أدرج خاصية "train on feedback" لتحسين الextractor من تصحيحات المشغلين.

واجهة لاستعراض الـ embeddings والـ nearest neighbours للسجلات.

أخيراً — صيغة الطلب النهائية (Prompt-ready)

انسخ هذا النص كاملًا كـ input للـ AI (Model) وقل له: "نفذ: اعطني مشروع كامل قابل للتشغيل يحتوي على كل ما سبق، زودني بالملفات، السكربتات، والـ README. ابدأ بالهيكل ثم كل ملف بكود كامل داخل code blocks. لا تسأل أي سؤال."

نص للنسخ المباشر:

You are a full-stack engineering assistant. Build a production-ready AI Automation + Workflow Builder project (mini-n8n) with the following exact requirements: [ألصق هنا القسم "هدف النظام المطلوب" و"مخرجات متوقعة" و"فرضيات" و"تعليمات السلوك"].

Deliverables:
1) Project tree
2) README
3) All source files (frontend, backend, infra)
4) docker-compose + Dockerfiles + k8s manifests
5) Migration SQL + seeds
6) Sample workflow JSON (Telegram sales)
7) PROMPTS/AGENT_TEMPLATES for Router, Extractor, Knowledge/RAG, Sales Agent, Fallback
8) Tests (unit + integration)
9) Deployment & CI instructions

Constraints:
- Use Node.js + TypeScript on backend, React + ReactFlow on frontend.
- Use PostgreSQL + Qdrant.
- Use OpenAI for chat + embeddings; keep KEY in env only.
- Secure webhooks, validate inputs, implement rate limiting.
- All code must be production-minded: error handling, logging, retries, idempotency.
- Return files in code blocks ready to write to disk.

Start by outputting project tree and README, then produce file-by-file content. Do not ask clarification questions. If a decision is required, state your assumption and proceed.