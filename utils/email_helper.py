import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

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


def _email_notifications_enabled() -> bool:
    try:
        from flask import g
        from models.core.global_setting import GlobalSetting

        old_tenant = getattr(g, "tenant", None)
        g.tenant = None
        try:
            return GlobalSetting.get_setting("NOTIFY_EMAIL_ENABLED", "0") == "1"
        finally:
            g.tenant = old_tenant
    except Exception:
        return True


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


def build_unsubscribe_url(token: str) -> str:
    token_clean = (token or "").strip()
    return f"{_resolve_base_url()}/unsubscribe/{token_clean}"


def _app_name() -> str:
    return current_app.config.get("APP_NAME", "Finora")


def _email_shell(*, title: str, body_html: str, footer_html: Optional[str] = None) -> str:
    app_name = _app_name()
    footer = footer_html or (
        f'<p style="color:#98A2B3;font-size:12px;margin:0;text-align:center">'
        f"© {app_name} — جميع الحقوق محفوظة</p>"
    )
    return f"""
<div dir="rtl" style="background:#F0F4FF;padding:32px 16px;font-family:Tajawal,Cairo,Arial,sans-serif">
  <div style="max-width:560px;margin:0 auto;background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 8px 32px rgba(16,24,40,.08)">
    <div style="background:linear-gradient(135deg,#2563EB 0%,#1D4ED8 100%);padding:28px 32px;text-align:center">
      <div style="font-size:28px;font-weight:900;color:#fff;letter-spacing:-.5px">{app_name}</div>
      <div style="color:rgba(255,255,255,.85);font-size:14px;margin-top:6px">{title}</div>
    </div>
    <div style="padding:32px">
      {body_html}
    </div>
    <div style="background:#F9FAFB;padding:20px 32px;border-top:1px solid #EAECF0">
      {footer}
    </div>
  </div>
</div>
"""


def send_welcome_account_email(
    *,
    to_email: str,
    contact_name: str,
    company_name: str,
    slug: str,
    username: str,
    password: str,
    plan_name: Optional[str] = None,
    unsubscribe_url: Optional[str] = None,
) -> bool:
    """إرسال بيانات الحساب الجديد للعميل بعد التسجيل."""
    app_name = _app_name()
    login_url = build_tenant_login_url(slug)
    plan_line = f"\nالخطة: {plan_name}" if plan_name else ""
    unsub_line = f"\n\nلإلغاء النشرة الأسبوعية: {unsubscribe_url}" if unsubscribe_url else ""

    subject = f"مرحباً بك في {app_name} — بيانات حسابك"
    body = f"""أهلاً {contact_name or ""}،

نحن سعداء بانضمامك إلى {app_name}! تم إنشاء حساب شركتك بنجاح.

اسم الشركة: {company_name}
معرف الشركة: {slug}
اسم المستخدم: {username}
كلمة المرور: {password}{plan_line}

رابط تسجيل الدخول:
{login_url}

احتفظ بهذه البيانات في مكان آمن. ننصحك بتغيير كلمة المرور بعد أول دخول.{unsub_line}

— فريق {app_name}
"""
    plan_row = (
        f'<tr><td style="padding:10px 0;color:#667085;border-bottom:1px solid #F2F4F7">الخطة</td>'
        f'<td style="padding:10px 0;font-weight:600;color:#101828;border-bottom:1px solid #F2F4F7;text-align:left;direction:ltr">{plan_name}</td></tr>'
        if plan_name
        else ""
    )
    body_html = f"""
<p style="color:#344054;font-size:16px;line-height:1.7;margin:0 0 20px">
  أهلاً <strong style="color:#101828">{contact_name or ""}</strong>،<br>
  نحن سعداء بانضمامك إلى <strong>{app_name}</strong>! تم إنشاء حساب <strong>{company_name}</strong> بنجاح.
</p>
<table style="width:100%;border-collapse:collapse;margin:0 0 24px;background:#F9FAFB;border-radius:12px;border:1px solid #EAECF0">
  <tr><td style="padding:10px 16px;color:#667085;border-bottom:1px solid #F2F4F7">معرف الشركة</td>
      <td style="padding:10px 16px;font-weight:700;color:#2563EB;border-bottom:1px solid #F2F4F7;text-align:left;direction:ltr">{slug}</td></tr>
  <tr><td style="padding:10px 16px;color:#667085;border-bottom:1px solid #F2F4F7">اسم المستخدم</td>
      <td style="padding:10px 16px;font-weight:600;color:#101828;border-bottom:1px solid #F2F4F7;text-align:left;direction:ltr">{username}</td></tr>
  <tr><td style="padding:10px 16px;color:#667085;border-bottom:1px solid #F2F4F7">كلمة المرور</td>
      <td style="padding:10px 16px;font-weight:600;color:#101828;border-bottom:1px solid #F2F4F7;text-align:left;direction:ltr">{password}</td></tr>
  {plan_row}
</table>
<p style="text-align:center;margin:0 0 16px">
  <a href="{login_url}" style="display:inline-block;background:#2563EB;color:#fff;text-decoration:none;padding:14px 36px;border-radius:10px;font-weight:700;font-size:15px">ابدأ الآن — تسجيل الدخول</a>
</p>
<p style="color:#667085;font-size:13px;text-align:center;word-break:break-all;margin:0">
  أو افتح: <a href="{login_url}" style="color:#2563EB">{login_url}</a>
</p>
<p style="color:#98A2B3;font-size:12px;margin:20px 0 0;text-align:center">احتفظ بهذه البيانات في مكان آمن وغيّر كلمة المرور بعد أول دخول.</p>
"""
    footer = f'<p style="color:#98A2B3;font-size:12px;margin:0;text-align:center">© {app_name}</p>'
    if unsubscribe_url:
        footer = (
            f'<p style="color:#98A2B3;font-size:12px;margin:0 0 8px;text-align:center">'
            f'<a href="{unsubscribe_url}" style="color:#667085">إلغاء الاشتراك في النشرة الأسبوعية</a></p>' + footer
        )
    html = _email_shell(title="مرحباً بك!", body_html=body_html, footer_html=footer)
    return send_email(to_email=to_email, subject=subject, body=body, html_body=html)


def send_signup_verification_email(to_email: str, code: str) -> bool:
    app_name = _app_name()
    subject = f"رمز التحقق — {app_name}"
    body = f"""مرحباً،

رمز التحقق لتسجيل حسابك في {app_name}:

{code}

الرمز صالح لمدة 10 دقائق.
إذا لم تطلب التسجيل، تجاهل هذه الرسالة.

— فريق {app_name}
"""
    body_html = f"""
<p style="color:#344054;font-size:15px;margin:0 0 16px">استخدم الرمز التالي لإكمال تسجيل حسابك في <strong>{app_name}</strong>:</p>
<div style="font-size:36px;font-weight:900;letter-spacing:10px;text-align:center;padding:24px;background:#EAF1FF;border-radius:12px;color:#1D4ED8;margin:0 0 16px;border:2px dashed #93C5FD">{code}</div>
<p style="color:#667085;font-size:14px;margin:0;text-align:center">صالح لمدة <strong>10 دقائق</strong>. لا تشارك هذا الرمز مع أحد.</p>
"""
    html = _email_shell(title="رمز التحقق", body_html=body_html)
    return send_email(to_email=to_email, subject=subject, body=body, html_body=html)


def send_announcement_email(
    *,
    to_email: str,
    contact_name: str,
    subject: str,
    body_html: str,
    body_plain: str,
    unsubscribe_url: Optional[str] = None,
) -> bool:
    """إرسال إعلان/نشرة تسويقية."""
    if not _email_notifications_enabled():
        return False

    app_name = _app_name()
    greeting = f"مرحباً {contact_name or ''},\n\n" if contact_name else ""
    unsub_plain = f"\n\nلإلغاء الاشتراك: {unsubscribe_url}" if unsubscribe_url else ""
    body = f"{greeting}{body_plain}{unsub_plain}\n\n— فريق {app_name}"

    greeting_html = (
        f'<p style="color:#344054;font-size:15px;margin:0 0 20px">مرحباً <strong>{contact_name}</strong>،</p>'
        if contact_name
        else ""
    )
    content_html = f"""
{greeting_html}
<div style="color:#344054;font-size:15px;line-height:1.8">{body_html}</div>
"""
    footer = f'<p style="color:#98A2B3;font-size:12px;margin:0;text-align:center">© {app_name}</p>'
    if unsubscribe_url:
        footer = (
            f'<p style="color:#98A2B3;font-size:12px;margin:0 0 8px;text-align:center">'
            f'<a href="{unsubscribe_url}" style="color:#667085">إلغاء الاشتراك في النشرة</a></p>' + footer
        )
    html = _email_shell(title=subject, body_html=content_html, footer_html=footer)
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
