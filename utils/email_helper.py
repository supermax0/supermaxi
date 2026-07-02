import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import current_app


def _smtp_settings():
    """إعدادات SMTP من config أو من إعدادات السوبر أدمن."""
    server = current_app.config.get("MAIL_SERVER") or ""
    port = int(current_app.config.get("MAIL_PORT") or 465)
    user = current_app.config.get("MAIL_USERNAME") or ""
    password = current_app.config.get("MAIL_PASSWORD") or ""
    use_ssl = bool(current_app.config.get("MAIL_USE_SSL", True))
    use_tls = bool(current_app.config.get("MAIL_USE_TLS", False))
    sender = current_app.config.get("MAIL_DEFAULT_SENDER") or user

    if user and password:
        return {
            "server": server,
            "port": port,
            "user": user,
            "password": password,
            "use_ssl": use_ssl,
            "use_tls": use_tls,
            "sender": sender,
        }

    try:
        from flask import g
        from models.core.global_setting import GlobalSetting

        old_tenant = getattr(g, "tenant", None)
        g.tenant = None
        try:
            gs_user = (GlobalSetting.get_setting("SMTP_USER", "") or "").strip()
            gs_pass = (GlobalSetting.get_setting("SMTP_PASSWORD", "") or "").strip()
            if not gs_user or not gs_pass:
                return None
            gs_host = (GlobalSetting.get_setting("SMTP_HOST", "") or "").strip()
            gs_port = int(GlobalSetting.get_setting("SMTP_PORT", "587") or 587)
            gs_from = (GlobalSetting.get_setting("SMTP_FROM", "") or "").strip() or gs_user
            return {
                "server": gs_host or server or "smtp.hostinger.com",
                "port": gs_port,
                "user": gs_user,
                "password": gs_pass,
                "use_ssl": gs_port == 465,
                "use_tls": gs_port == 587,
                "sender": gs_from,
            }
        finally:
            g.tenant = old_tenant
    except Exception:
        return None


from typing import Optional


def send_email(*, to_email: str, subject: str, body: str, html_body: Optional[str] = None) -> bool:
    """إرسال بريد عام."""
    try:
        smtp = _smtp_settings()
        if not smtp:
            print("⚠️ Email configuration missing. Skipping email send.")
            return False

        msg = MIMEMultipart("alternative")
        msg["From"] = smtp["sender"]
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))
        if html_body:
            msg.attach(MIMEText(html_body, "html", "utf-8"))

        timeout = 15
        if smtp["use_ssl"]:
            server = smtplib.SMTP_SSL(smtp["server"], smtp["port"], timeout=timeout)
        else:
            server = smtplib.SMTP(smtp["server"], smtp["port"], timeout=timeout)
            if smtp["use_tls"]:
                server.starttls()

        server.login(smtp["user"], smtp["password"])
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"❌ Failed to send email: {e}")
        try:
            current_app.logger.exception("send_email failed")
        except Exception:
            pass
        return False


def _resolve_base_url() -> str:
    """عنوان المنصة العام (لروابط تسجيل الدخول في البريد)."""
    from flask import has_request_context, request

    base_cfg = (current_app.config.get("BASE_URL") or "").strip().rstrip("/")
    if has_request_context():
        try:
            proto = (request.headers.get("X-Forwarded-Proto") or request.scheme or "https").split(",")[0].strip()
            host = (
                request.headers.get("X-Forwarded-Host")
                or request.headers.get("Host")
                or (getattr(request, "host", None) or "")
            )
            host = (host or "").split(",")[0].strip()
            if host and not host.startswith(("127.", "localhost", "192.168.", "10.")):
                return f"{proto}://{host}".rstrip("/")
        except Exception:
            pass
    return base_cfg or "https://finora.company"


def build_tenant_login_url(slug: str) -> str:
    slug_clean = (slug or "").strip().lower()
    return f"{_resolve_base_url()}/login/{slug_clean}"


def send_welcome_account_email(
    *,
    to_email: str,
    contact_name: str,
    company_name: str,
    slug: str,
    username: str,
    password: str,
    plan_name: Optional[str] = None,
) -> bool:
    """إرسال بيانات الحساب الجديد للعميل بعد التسجيل."""
    app_name = current_app.config.get("APP_NAME", "Finora")
    login_url = build_tenant_login_url(slug)
    plan_line = f"\nالخطة: {plan_name}" if plan_name else ""

    subject = f"مرحباً بك في {app_name} — بيانات حسابك"
    body = f"""مرحباً {contact_name or ""},

تم إنشاء حساب شركتك بنجاح في {app_name}.

اسم الشركة: {company_name}
معرف الشركة: {slug}
اسم المستخدم: {username}
كلمة المرور: {password}{plan_line}

رابط تسجيل الدخول:
{login_url}

احتفظ بهذه البيانات في مكان آمن. ننصحك بتغيير كلمة المرور بعد أول دخول.

— فريق {app_name}
"""
    plan_html = f'<tr><td style="padding:8px 0;color:#667085">الخطة</td><td style="padding:8px 0;font-weight:600;color:#101828">{plan_name}</td></tr>' if plan_name else ""
    html = f"""
<div dir="rtl" style="font-family:Tajawal,Arial,sans-serif;max-width:520px;margin:0 auto;padding:24px">
  <h2 style="color:#2563EB;margin-bottom:8px">مرحباً بك في {app_name}</h2>
  <p style="color:#667085">مرحباً <strong>{contact_name or ""}</strong>، تم إنشاء حساب <strong>{company_name}</strong> بنجاح.</p>
  <table style="width:100%;border-collapse:collapse;margin:20px 0;background:#F9FAFB;border-radius:12px;padding:4px 16px">
    <tr><td style="padding:8px 0;color:#667085">معرف الشركة</td><td style="padding:8px 0;font-weight:700;color:#101828;direction:ltr;text-align:right">{slug}</td></tr>
    <tr><td style="padding:8px 0;color:#667085">اسم المستخدم</td><td style="padding:8px 0;font-weight:600;color:#101828;direction:ltr;text-align:right">{username}</td></tr>
    <tr><td style="padding:8px 0;color:#667085">كلمة المرور</td><td style="padding:8px 0;font-weight:600;color:#101828;direction:ltr;text-align:right">{password}</td></tr>
    {plan_html}
  </table>
  <p style="text-align:center;margin:24px 0">
    <a href="{login_url}" style="display:inline-block;background:#2563EB;color:#fff;text-decoration:none;padding:14px 28px;border-radius:10px;font-weight:700">تسجيل الدخول</a>
  </p>
  <p style="color:#667085;font-size:13px;word-break:break-all">أو افتح الرابط: <a href="{login_url}" style="color:#2563EB">{login_url}</a></p>
  <p style="color:#98A2B3;font-size:12px;margin-top:20px">احتفظ بهذه البيانات في مكان آمن وغيّر كلمة المرور بعد أول دخول.</p>
</div>
"""
    return send_email(to_email=to_email, subject=subject, body=body, html_body=html)


def send_signup_verification_email(to_email: str, code: str) -> bool:
    app_name = current_app.config.get("APP_NAME", "Finora")
    subject = f"رمز التحقق — {app_name}"
    body = f"""مرحباً،

رمز التحقق لتسجيل حسابك في {app_name}:

{code}

الرمز صالح لمدة 10 دقائق.
إذا لم تطلب التسجيل، تجاهل هذه الرسالة.

— فريق {app_name}
"""
    html = f"""
<div dir="rtl" style="font-family:Tajawal,Arial,sans-serif;max-width:480px;margin:0 auto;padding:24px">
  <h2 style="color:#2563EB;margin-bottom:8px">رمز التحقق</h2>
  <p style="color:#667085">استخدم الرمز التالي لإكمال تسجيل حسابك في {app_name}:</p>
  <div style="font-size:32px;font-weight:800;letter-spacing:8px;text-align:center;padding:20px;background:#EAF1FF;border-radius:12px;color:#101828;margin:20px 0">{code}</div>
  <p style="color:#667085;font-size:14px">صالح لمدة <strong>10 دقائق</strong>. لا تشارك هذا الرمز مع أحد.</p>
</div>
"""
    return send_email(to_email=to_email, subject=subject, body=body, html_body=html)


def send_contact_email(name, phone, message):
    """إرسال إشعار عند تعبئة نموذج التواصل."""
    to_email = current_app.config.get("CONTACT_EMAIL")
    if not to_email:
        return False

    subject = f"رسالة جديدة من: {name}"
    body = f"""لقد استلمت رسالة جديدة من نموذج التواصل في الموقع:

الاسم: {name}
رقم الهاتف: {phone}

الرسالة:
{message}

---
Finora Notification System
"""
    return send_email(to_email=to_email, subject=subject, body=body)
