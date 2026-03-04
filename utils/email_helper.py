import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import current_app

def send_contact_email(name, phone, message):
    """
    Sends an email notification when someone fills out the contact form.
    """
    try:
        smtp_server = current_app.config.get("MAIL_SERVER")
        smtp_port = current_app.config.get("MAIL_PORT")
        smtp_user = current_app.config.get("MAIL_USERNAME")
        smtp_pass = current_app.config.get("MAIL_PASSWORD")
        to_email = current_app.config.get("CONTACT_EMAIL")

        if not all([smtp_user, smtp_pass]):
            print("⚠️ Email configuration missing. Skipping email send.")
            return False

        # Create message
        msg = MIMEMultipart()
        msg['From'] = smtp_user
        msg['To'] = to_email
        msg['Subject'] = f"رسالة جديدة من: {name}"

        body = f"""
        لقد استلمت رسالة جديدة من نموذج التواصل في الموقع:
        
        الاسم: {name}
        رقم الهاتف: {phone}
        
        الرسالة:
        {message}
        
        ---
        Finora Notification System
        """
        
        msg.attach(MIMEText(body, 'plain', 'utf-8'))

        # Send email
        timeout = 15  # seconds
        if current_app.config.get("MAIL_USE_SSL"):
            server = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=timeout)
        else:
            server = smtplib.SMTP(smtp_server, smtp_port, timeout=timeout)
            if current_app.config.get("MAIL_USE_TLS"):
                server.starttls()
        
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)
        server.quit()
        
        print(f"✅ Email sent successfully to {to_email}")
        return True
    except Exception as e:
        print(f"❌ Failed to send email: {str(e)}")
        return False
