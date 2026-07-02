from datetime import datetime
import json

from flask import g

from extensions import db
from models.core.landing_content import (
    LandingCTA,
    LandingFAQ,
    LandingFeature,
    LandingMedia,
    LandingModule,
    LandingPageSettings,
    LandingPricingPlan,
    LandingSEO,
    LandingSection,
    LandingTestimonial,
)


SCOPED_MODELS = [
    LandingPageSettings,
    LandingSection,
    LandingFeature,
    LandingModule,
    LandingPricingPlan,
    LandingFAQ,
    LandingTestimonial,
    LandingCTA,
    LandingSEO,
]


def _as_json(value):
    return json.dumps(value or {}, ensure_ascii=False)


def _as_json_list(value):
    return json.dumps(value or [], ensure_ascii=False)


def _core_guard():
    old_tenant = getattr(g, "tenant", None)
    g.tenant = None
    return old_tenant


def _restore_tenant(old_tenant):
    g.tenant = old_tenant


def _copy_public_columns(src, dest):
    skip = {"id", "scope", "created_at", "updated_at", "published_at", "published_by", "last_edited_by"}
    for column in src.__table__.columns:
        if column.name in skip:
            continue
        setattr(dest, column.name, getattr(src, column.name))


def _seed_scope(scope):
    settings = LandingPageSettings(
        scope=scope,
        site_name="Finora Cloud",
        page_title="Finora Cloud — نظام إدارة ومحاسبة ذكي",
        page_subtitle="منصة SaaS تجمع الطلبات والمخزون والحسابات والتسويات في مكان واحد.",
        logo_url="/static/IMG_0200.png",
        favicon_url="/static/IMG_0200.png",
        primary_color="#2563eb",
        secondary_color="#0f766e",
        accent_color="#7c3aed",
        background_color="#f7f9fc",
        text_color="#101828",
        whatsapp_number="+9647700000000",
        contact_email="hello@finora.cloud",
        login_url="/login",
        trial_url="/signup?plan=free&billing=monthly",
        demo_booking_url="#contact",
        is_active=True,
    )
    db.session.add(settings)

    sections = [
        ("hero", "hero", "فينورا — نظام إدارة ومحاسبة ذكي لشركتك", "مصمم للشركات والمتاجر العراقية", "تابع المبيعات، الطلبات، المخزون، شركات التوصيل، المصاريف، الأرباح، والتسويات من مكان واحد، مع مساعد ذكي يساعدك تكتشف الأخطاء قبل ما تتحول إلى خسائر.", {"stats": [{"value": "+1,200", "label": "طلب يومياً"}, {"value": "12+", "label": "ميزة تشغيلية"}, {"value": "99.9%", "label": "وقت تشغيل"}, {"value": "4", "label": "خطط مرنة"}]}, "/static/image.png", "", "جرّب مجاناً", "/signup?plan=free&billing=monthly", "احجز عرض مباشر", "#contact", 10),
        ("pain_points", "pain_points", "الفوضى الصغيرة تتحول إلى خسارة كبيرة", "مشاكل يومية يعرفها كل صاحب متجر", "طلبات غير محسوبة، تسويات توصيل معقدة، مخزون غير مضبوط، أرباح غير واضحة، ومصاريف لا تظهر في التقرير الصحيح.", {"items": ["طلبات غير محسوبة", "تسويات توصيل معقدة", "مخزون غير مضبوط", "أرباح غير واضحة", "مصاريف غير مرتبطة", "موظفون بلا متابعة دقيقة"]}, "", "", "", "", "", "", 20),
        ("solution", "solution", "فينورا يجمع عملياتك في لوحة واحدة", "من الطلب إلى الربح الحقيقي", "فينورا يحوّل شغل شركتك اليومي إلى أرقام واضحة، قرارات أسرع، وتقارير تفهم منها الربح الحقيقي.", {}, "", "", "شاهد طريقة العمل", "#workflow", "", "", 30),
        ("workflow", "workflow", "طريقة العمل", "طلب → تجهيز → شحن → تسليم → تسوية → ربح صافي", "كل خطوة مرتبطة بالأرقام التي تحتاجها لاتخاذ قرار أسرع.", {"steps": ["طلب", "تجهيز", "شحن", "تسليم", "تسوية", "ربح صافي"]}, "", "", "", "", "", "", 40),
        ("features", "features", "كل ما تحتاجه لإدارة شركتك", "مميزات تشغيلية ومحاسبية في نظام واحد", "من أول طلب حتى آخر تقرير مالي، Finora يغطي كل خطوة.", {}, "", "", "", "", "", "", 50),
        ("modules", "modules", "موديلات النظام", "نوافذ واضحة لكل فريق", "اعرض ما يهم كل قسم داخل شركتك بدون تشتيت.", {}, "", "", "", "", "", "", 60),
        ("ai_assistant", "ai_assistant", "LEON AI — مساعدك الذكي داخل فينورا", "يراجع الأرقام وينبهك قبل الخسارة", "LEON يكتشف الأخطاء، يحلل التسويات، ينبهك للطلبات المتأخرة، ويجاوبك على أسئلة الربح والمخزون والتحصيل.", {"messages": ["عندك 3 طلبات تم تسليمها ولم تدخل بالتسوية.", "المصاريف زادت 18% مقارنة بالأسبوع السابق.", "هذا المنتج مبيعاته عالية والمخزون قرب يخلص.", "كشف شركة التوصيل يحتوي فرق 25,000 دينار."]}, "", "", "", "", "", "", 70),
        ("demo_video", "demo_video", "شاهد فينورا خلال دقيقتين", "فيديو تعريفي سريع", "افتح الفيديو داخل نافذة خفيفة بدون تحميل إجباري.", {}, "", "", "شاهد الفيديو", "", "", "", 80),
        ("pricing", "pricing", "خطط واضحة بلا مفاجآت", "اختر الخطة التي تناسب حجم عملك", "يمكن تعديل الخطط والأسعار والعملة من لوحة التحكم.", {}, "", "", "", "", "", "", 90),
        ("testimonials", "testimonials", "آراء العملاء", "ثقة أصحاب المتاجر والشركات", "يمكن إخفاء هذا القسم إذا لم تضف آراء بعد.", {}, "", "", "", "", "", "", 100),
        ("faq", "faq", "أسئلة شائعة", "إجابات واضحة قبل الاشتراك", "", {}, "", "", "", "", "", "", 110),
        ("final_cta", "final_cta", "ابدأ بتنظيم شركتك اليوم", "جرّب فينورا مجاناً أو احجز عرض مباشر", "شوف كيف يسيطر النظام على عملياتك اليومية من الطلب إلى الربح الصافي.", {}, "", "", "جرّب مجاناً", "/signup?plan=free&billing=monthly", "تواصل واتساب", "https://wa.me/9647700000000", 120),
        ("footer", "footer", "Finora Cloud", "منصة إدارة ومحاسبة ذكية", "نظام SaaS للشركات والمتاجر وشركات التوصيل.", {"links": [{"label": "الخصوصية", "url": "/privacy"}, {"label": "الشروط", "url": "/terms"}], "social": []}, "", "", "", "", "", "", 130),
    ]
    for row in sections:
        db.session.add(
            LandingSection(
                scope=scope,
                section_key=row[0],
                section_type=row[1],
                title=row[2],
                subtitle=row[3],
                description=row[4],
                content_json=_as_json(row[5]),
                image_url=row[6],
                video_url=row[7],
                button_primary_text=row[8],
                button_primary_url=row[9],
                button_secondary_text=row[10],
                button_secondary_url=row[11],
                sort_order=row[12],
                is_visible=True,
            )
        )

    features = [
        ("POS سريع", "واجهة كاشير خفيفة وبحث فوري وإنشاء طلبات في ثوان.", "fa-solid fa-cash-register"),
        ("إدارة الطلبات", "تتبع كامل من الإنشاء حتى التوصيل والتسوية.", "fa-solid fa-boxes-stacked"),
        ("إدارة المخزون", "حركة مخزون وكلفة وتنبيهات نقص المنتجات.", "fa-solid fa-warehouse"),
        ("إدارة العملاء", "سجل طلبات وذمم وملاحظات لكل عميل.", "fa-solid fa-users"),
        ("الموردون والمشتريات", "فواتير شراء ومديونيات وسجل دفعات واضح.", "fa-solid fa-handshake"),
        ("تسويات شركات التوصيل", "مطابقة كشوفات التوصيل مع الطلبات والفروقات.", "fa-solid fa-truck"),
        ("تقارير الأرباح", "إيرادات ومصاريف وربح صافي وقيمة مخزون.", "fa-solid fa-chart-line"),
        ("صلاحيات الموظفين", "أدوار وصلاحيات دقيقة حسب مسؤولية كل موظف.", "fa-solid fa-user-shield"),
        ("LEON AI", "مساعد ذكي يراجع الأرقام وينبهك للأخطاء.", "fa-solid fa-brain"),
    ]
    for idx, (title, desc, icon) in enumerate(features, start=1):
        db.session.add(LandingFeature(scope=scope, title=title, description=desc, icon=icon, feature_key=f"feature_{idx}", sort_order=idx * 10, is_visible=True))

    modules = [
        ("POS", "بيع سريع ونقطة كاشير", "fa-solid fa-cash-register"),
        ("Orders", "إدارة الطلبات والحالات", "fa-solid fa-list-check"),
        ("Inventory", "مخزون وحركات وتكاليف", "fa-solid fa-box-open"),
        ("Customers", "عملاء وذمم وسجل تعامل", "fa-solid fa-address-book"),
        ("Suppliers", "موردون ومشتريات ودفعات", "fa-solid fa-truck-ramp-box"),
        ("Accounting", "حسابات ومصاريف وربح صافي", "fa-solid fa-calculator"),
        ("Courier Settlement", "تسويات شركات التوصيل", "fa-solid fa-route"),
        ("Reports", "تقارير ذكية للإدارة", "fa-solid fa-chart-pie"),
        ("Employees", "موظفون وأدوار وصلاحيات", "fa-solid fa-users-gear"),
        ("LEON AI", "مساعد تحليل وتنبيه", "fa-solid fa-brain"),
    ]
    for idx, (name, desc, icon) in enumerate(modules, start=1):
        db.session.add(LandingModule(scope=scope, name=name, short_description=desc, long_description=desc, icon=icon, sort_order=idx * 10, is_visible=True))

    plans = [
        ("Starter", "starter", 20, "$", "شهري", "مناسب للمتاجر الصغيرة.", ["أساسيات فينورا", "POS وطلبات ومخزون", "بدون LEON كامل"], "", False),
        ("Business", "business", 49, "$", "شهري", "مناسب للشركات النامية.", ["كل مميزات فينورا", "تقارير وتسويات", "LEON بنصف الإمكانيات"], "الأكثر شيوعاً", True),
        ("Pro AI", "pro-ai", 99, "$", "شهري", "للشركات التي تريد ذكاء وتحليل كامل.", ["Finora كامل", "LEON كامل", "تحليل وتسويات وتنبيهات ذكية"], "ذكاء كامل", False),
    ]
    for idx, (name, slug, price, currency, period, desc, feats, badge, popular) in enumerate(plans, start=1):
        db.session.add(LandingPricingPlan(scope=scope, name=name, slug=slug, price=price, currency=currency, billing_period=period, description=desc, features_json=_as_json_list(feats), cta_text="ابدأ الآن", cta_url=f"/signup?plan={slug}", badge_text=badge, is_popular=popular, is_visible=True, sort_order=idx * 10))

    faqs = [
        ("هل فينورا يدعم شركات التوصيل؟", "نعم، يدعم ربط الطلبات بشركات التوصيل وتحليل كشوف التسوية والفروقات."),
        ("هل أستطيع استخدامه من الهاتف؟", "نعم، الصفحة والنظام متجاوبان ويعملان على الهاتف والتابلت والديسكتوب."),
        ("هل يحسب الربح الصافي؟", "نعم، يعتمد على المبيعات والمرتجعات والمصاريف وكلفة المخزون والتسويات."),
        ("هل يدعم أكثر من موظف؟", "نعم، مع صلاحيات وأدوار لكل موظف حسب مسؤولياته."),
        ("هل توجد تجربة مجانية؟", "نعم، يمكن تفعيل تجربة مجانية من زر التجربة أو عبر التواصل."),
        ("هل البيانات آمنة؟", "بيانات كل شركة معزولة عن الأخرى مع حماية على مستوى الجلسات والصلاحيات."),
    ]
    for idx, (q, a) in enumerate(faqs, start=1):
        db.session.add(LandingFAQ(scope=scope, question=q, answer=a, category="عام", sort_order=idx * 10, is_visible=True))

    testimonials = [
        ("أحمد كريم", "مدير متجر إلكتروني", "متجر عراقي", "فينورا خلّى الربح الحقيقي واضح بعد ما كان مشتت بين الطلبات والتوصيل.", 5),
        ("سارة علي", "محاسبة", "شركة توزيع", "أكثر شيء فرق معنا هو التسويات وتقارير المصاريف اليومية.", 5),
    ]
    for idx, (name, title, company, quote, rating) in enumerate(testimonials, start=1):
        db.session.add(LandingTestimonial(scope=scope, customer_name=name, customer_title=title, company_name=company, quote=quote, rating=rating, sort_order=idx * 10, is_visible=True))

    ctas = [
        ("جرّب مجاناً", "/signup?plan=free&billing=monthly", "trial", "hero", 10),
        ("احجز عرض مباشر", "#contact", "demo", "hero", 20),
        ("تواصل واتساب", "https://wa.me/9647700000000", "whatsapp", "final_cta", 10),
        ("تسجيل الدخول", "/login", "login", "header", 10),
    ]
    for label, url, cta_type, placement, order in ctas:
        db.session.add(LandingCTA(scope=scope, label=label, url=url, cta_type=cta_type, placement_key=placement, sort_order=order, is_visible=True))

    db.session.add(
        LandingSEO(
            scope=scope,
            meta_title="Finora Cloud — نظام إدارة ومحاسبة ذكي للشركات والمتاجر",
            meta_description="منصة SaaS عراقية لإدارة الطلبات والمخزون والحسابات وشركات التوصيل والتسويات مع مساعد LEON الذكي.",
            meta_keywords="Finora, محاسبة, إدارة متجر, SaaS, POS, مخزون, شركات التوصيل",
            og_title="Finora Cloud",
            og_description="كل عمليات شركتك من الطلب إلى التسوية والربح الحقيقي في مكان واحد.",
            og_image_url="/static/image.png",
            twitter_title="Finora Cloud",
            twitter_description="نظام إدارة ومحاسبة ذكي للشركات والمتاجر.",
            twitter_image_url="/static/image.png",
            canonical_url="",
            robots="index,follow",
            schema_json=_as_json({"@context": "https://schema.org", "@type": "SoftwareApplication", "name": "Finora Cloud", "applicationCategory": "BusinessApplication"}),
        )
    )


def ensure_landing_seed():
    old_tenant = _core_guard()
    try:
        LandingPageSettings.__table__.create(bind=db.engine, checkfirst=True)
        LandingSection.__table__.create(bind=db.engine, checkfirst=True)
        LandingMedia.__table__.create(bind=db.engine, checkfirst=True)
        LandingFeature.__table__.create(bind=db.engine, checkfirst=True)
        LandingModule.__table__.create(bind=db.engine, checkfirst=True)
        LandingPricingPlan.__table__.create(bind=db.engine, checkfirst=True)
        LandingFAQ.__table__.create(bind=db.engine, checkfirst=True)
        LandingTestimonial.__table__.create(bind=db.engine, checkfirst=True)
        LandingCTA.__table__.create(bind=db.engine, checkfirst=True)
        LandingSEO.__table__.create(bind=db.engine, checkfirst=True)
        if LandingPageSettings.query.filter_by(scope="draft").first():
            return False
        _seed_scope("draft")
        _seed_scope("published")
        now = datetime.utcnow()
        for model in SCOPED_MODELS:
            for row in model.query.filter_by(scope="published").all():
                row.published_at = now
        db.session.commit()
        return True
    except Exception:
        db.session.rollback()
        raise
    finally:
        _restore_tenant(old_tenant)


def get_landing_payload(scope="published", include_hidden=False):
    ensure_landing_seed()
    old_tenant = _core_guard()
    try:
        settings = LandingPageSettings.query.filter_by(scope=scope).first() or LandingPageSettings.query.filter_by(scope="published").first()
        seo = LandingSEO.query.filter_by(scope=scope).first() or LandingSEO.query.filter_by(scope="published").first()

        def visible(query):
            return query if include_hidden else query.filter_by(is_visible=True)

        sections = visible(LandingSection.query.filter_by(scope=scope)).order_by(LandingSection.sort_order.asc(), LandingSection.id.asc()).all()
        features = visible(LandingFeature.query.filter_by(scope=scope)).order_by(LandingFeature.sort_order.asc(), LandingFeature.id.asc()).all()
        modules = visible(LandingModule.query.filter_by(scope=scope)).order_by(LandingModule.sort_order.asc(), LandingModule.id.asc()).all()
        pricing = visible(LandingPricingPlan.query.filter_by(scope=scope)).order_by(LandingPricingPlan.sort_order.asc(), LandingPricingPlan.id.asc()).all()
        faqs = visible(LandingFAQ.query.filter_by(scope=scope)).order_by(LandingFAQ.sort_order.asc(), LandingFAQ.id.asc()).all()
        testimonials = visible(LandingTestimonial.query.filter_by(scope=scope)).order_by(LandingTestimonial.sort_order.asc(), LandingTestimonial.id.asc()).all()
        ctas = visible(LandingCTA.query.filter_by(scope=scope)).order_by(LandingCTA.sort_order.asc(), LandingCTA.id.asc()).all()
        media = LandingMedia.query.filter_by(is_active=True).order_by(LandingMedia.id.desc()).all()
        section_map = {s.section_key: s.to_dict() for s in sections}
        return {
            "settings": settings.to_dict() if settings else {},
            "seo": seo.to_dict() if seo else {},
            "sections": [s.to_dict() for s in sections],
            "section_map": section_map,
            "features": [x.to_dict() for x in features],
            "modules": [x.to_dict() for x in modules],
            "pricing": [x.to_dict() for x in pricing],
            "faqs": [x.to_dict() for x in faqs],
            "testimonials": [x.to_dict() for x in testimonials],
            "ctas": [x.to_dict() for x in ctas],
            "media": [x.to_dict() for x in media],
            "scope": scope,
        }
    finally:
        _restore_tenant(old_tenant)


def publish_landing(superadmin_id=None):
    ensure_landing_seed()
    old_tenant = _core_guard()
    try:
        for model in SCOPED_MODELS:
            model.query.filter_by(scope="published").delete()
            for draft in model.query.filter_by(scope="draft").all():
                clone = model(scope="published")
                _copy_public_columns(draft, clone)
                clone.published_at = datetime.utcnow()
                clone.published_by = superadmin_id
                clone.last_edited_by = getattr(draft, "last_edited_by", None)
                db.session.add(clone)
        db.session.commit()
        return get_landing_payload("published")
    except Exception:
        db.session.rollback()
        raise
    finally:
        _restore_tenant(old_tenant)
