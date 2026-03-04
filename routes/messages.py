from flask import Blueprint, render_template, request, jsonify, session, send_file, current_app
from extensions import db
from models.message import Message
from models.employee import Employee
from sqlalchemy import or_, and_, inspect, text
from datetime import datetime
import os
import uuid
from werkzeug.utils import secure_filename

messages_bp = Blueprint("messages", __name__, url_prefix="/messages")


def _ensure_messages_schema():
    """Lightweight migration: make sure `message.is_edited` exists."""
    try:
        inspector = inspect(db.engine)
        if "message" not in inspector.get_table_names():
            return

        columns = {col["name"] for col in inspector.get_columns("message")}
        if "is_edited" in columns:
            return

        db.session.execute(text("ALTER TABLE message ADD COLUMN is_edited BOOLEAN DEFAULT 0"))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        # Ignore race/duplicate column errors and keep requests alive.
        if "duplicate column" not in str(e).lower():
            print(f"[messages] schema ensure failed: {e}")


@messages_bp.before_request
def ensure_messages_schema():
    _ensure_messages_schema()

# =====================================================
# Messages Page
# =====================================================
@messages_bp.route("/")
def messages():
    if "user_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403
    
    current_user_id = session["user_id"]
    
    # جلب جميع الموظفين (للأدمن) أو الأدمن فقط (للكاشير)
    current_user = Employee.query.get(current_user_id)
    
    if not current_user:
        return jsonify({"error": "مستخدم غير موجود"}), 404
    
    # تحديد من يمكنك المراسلة معه
    if current_user.role == "admin":
        # الأدمن يمكنه المراسلة مع الجميع
        chat_users = Employee.query.filter(Employee.id != current_user_id).all()
    else:
        # الكاشير يمكنه المراسلة مع الأدمن فقط
        chat_users = Employee.query.filter_by(role="admin").all()
    
    return render_template(
        "messages.html",
        chat_users=[{"id": u.id, "name": u.name, "role": u.role} for u in chat_users],
        current_user_id=current_user_id,
        current_user_name=current_user.name
    )

# =====================================================
# Get Messages Between Two Users
# =====================================================
@messages_bp.route("/get/<int:other_user_id>")
def get_messages(other_user_id):
    if "user_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403
    
    current_user_id = session["user_id"]
    
    # جلب الرسائل بين المستخدمين
    messages = Message.query.filter(
        or_(
            and_(Message.sender_id == current_user_id, Message.receiver_id == other_user_id),
            and_(Message.sender_id == other_user_id, Message.receiver_id == current_user_id)
        )
    ).order_by(Message.created_at.asc()).all()
    
    # تحديث حالة الرسائل إلى "مقروءة"
    Message.query.filter(
        Message.sender_id == other_user_id,
        Message.receiver_id == current_user_id,
        Message.is_read == False
    ).update({"is_read": True})
    db.session.commit()
    
    return jsonify({
        "success": True,
        "messages": [msg.to_dict() for msg in messages]
    })

# =====================================================
# Send Message
# =====================================================
@messages_bp.route("/send", methods=["POST"])
def send_message():
    if "user_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403
    
    current_user_id = session["user_id"]
    
    try:
        # محاولة الحصول على البيانات من FormData أولاً، ثم JSON
        if request.content_type and 'multipart/form-data' in request.content_type:
            # FormData request
            receiver_id = request.form.get("receiver_id")
            content = request.form.get("content", "").strip()
        elif request.is_json:
            # JSON request
            data = request.get_json() or {}
            receiver_id = data.get("receiver_id")
            content = data.get("content", "").strip()
        else:
            # Try both
            receiver_id = request.form.get("receiver_id") or (request.get_json() or {}).get("receiver_id")
            content = request.form.get("content", "").strip() or (request.get_json() or {}).get("content", "").strip()
        
        if not receiver_id:
            return jsonify({"error": "المستقبل مطلوب"}), 400
        
        if not content and 'file' not in request.files:
            return jsonify({"error": "محتوى الرسالة أو ملف مطلوب"}), 400
        
        receiver = Employee.query.get(receiver_id)
        if not receiver:
            return jsonify({"error": "المستقبل غير موجود"}), 404
        
        # معالجة الملف المرفق
        file_type = None
        file_path = None
        file_name = None
        
        if 'file' in request.files:
            file = request.files['file']
            if file and file.filename:
                try:
                    # إنشاء مجلد التحميل
                    upload_folder = 'static/uploads/messages'
                    os.makedirs(upload_folder, exist_ok=True)
                    
                    # تحديد نوع الملف
                    filename = secure_filename(file.filename)
                    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
                    
                    if ext in ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp']:
                        file_type = 'image'
                    elif ext in ['mp4', 'webm', 'ogg', 'mov', 'avi', 'mkv']:
                        file_type = 'video'
                    elif ext in ['mp3', 'wav', 'ogg', 'm4a', 'aac', 'flac']:
                        file_type = 'audio'
                    else:
                        file_type = 'file'
                    
                    # إنشاء اسم فريد للملف
                    unique_filename = f"{uuid.uuid4()}.{ext}"
                    file_path_full = os.path.join(upload_folder, unique_filename)
                    file.save(file_path_full)
                    file_name = filename
                    
                    # حفظ المسار النسبي
                    file_path = f"/{upload_folder.replace(chr(92), '/')}/{unique_filename}"
                except Exception as e:
                    print(f"Error saving file: {e}")
                    return jsonify({"error": f"خطأ في رفع الملف: {str(e)}"}), 500
        
        # إنشاء الرسالة
        message = Message(
            sender_id=current_user_id,
            receiver_id=receiver_id,
            content=content or (f"📎 {file_name}" if file_name else ""),
            file_type=file_type,
            file_path=file_path,
            file_name=file_name
        )
        
        db.session.add(message)
        db.session.commit()
        
        return jsonify({
            "success": True,
            "message": message.to_dict()
        })
    except Exception as e:
        print(f"Error in send_message: {e}")
        return jsonify({"error": f"حدث خطأ: {str(e)}"}), 500

# =====================================================
# Get Unread Messages Count
# =====================================================
@messages_bp.route("/unread-count")
def unread_count():
    if "user_id" not in session:
        return jsonify({"unread_count": 0})
    
    current_user_id = session["user_id"]
    
    count = Message.query.filter(
        Message.receiver_id == current_user_id,
        Message.is_read == False
    ).count()
    
    return jsonify({"unread_count": count})

# =====================================================
# Get Last Messages with Each User
# =====================================================
@messages_bp.route("/delete/<int:message_id>", methods=["DELETE"])
def delete_message(message_id):
    if "user_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403
    
    current_user_id = session["user_id"]
    message = Message.query.get_or_404(message_id)
    
    # التحقق من أن المستخدم هو المرسل
    if message.sender_id != current_user_id:
        return jsonify({"error": "غير مصرح لك بحذف هذه الرسالة"}), 403
    
    
    db.session.delete(message)
    db.session.commit()
    
    return jsonify({"success": True, "message": "تم حذف الرسالة"})

@messages_bp.route("/edit/<int:message_id>", methods=["PUT"])
def edit_message(message_id):
    if "user_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403
    
    current_user_id = session["user_id"]
    message = Message.query.get_or_404(message_id)
    
    # التحقق من أن المستخدم هو المرسل
    if message.sender_id != current_user_id:
        return jsonify({"error": "غير مصرح لك بتعديل هذه الرسالة"}), 403
        
    data = request.get_json()
    new_content = data.get("content", "").strip()
    
    if not new_content:
        return jsonify({"error": "محتوى الرسالة مطلوب"}), 400
        
    message.content = new_content
    message.is_edited = True
    db.session.commit()
    
    return jsonify({
        "success": True, 
        "message": message.to_dict()
    })

@messages_bp.route("/clear/<int:other_user_id>", methods=["DELETE"])
def clear_chat(other_user_id):
    if "user_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403
    
    current_user_id = session["user_id"]
    
    # حذف جميع الرسائل بين المستخدمين
    Message.query.filter(
        or_(
            and_(Message.sender_id == current_user_id, Message.receiver_id == other_user_id),
            and_(Message.sender_id == other_user_id, Message.receiver_id == current_user_id)
        )
    ).delete()
    
    db.session.commit()
    
    return jsonify({"success": True, "message": "تم مسح المحادثة"})

@messages_bp.route("/conversations")
def get_conversations():
    if "user_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403
    
    current_user_id = session["user_id"]
    
    # جلب آخر رسالة مع كل مستخدم
    conversations = []
    
    # جلب جميع الرسائل المرسلة والمستلمة
    all_messages = Message.query.filter(
        or_(
            Message.sender_id == current_user_id,
            Message.receiver_id == current_user_id
        )
    ).order_by(Message.created_at.desc()).all()
    
    # تجميع المحادثات
    seen_users = set()
    for msg in all_messages:
        other_user_id = msg.receiver_id if msg.sender_id == current_user_id else msg.sender_id
        
        if other_user_id not in seen_users:
            seen_users.add(other_user_id)
            other_user = msg.receiver if msg.sender_id == current_user_id else msg.sender
            
            # حساب عدد الرسائل غير المقروءة
            unread_count = Message.query.filter(
                Message.sender_id == other_user_id,
                Message.receiver_id == current_user_id,
                Message.is_read == False
            ).count()
            
            user_role = ""
            if other_user:
                if hasattr(other_user, 'role'):
                    user_role = other_user.role
                elif hasattr(other_user, 'roles') and other_user.roles:
                    user_role = other_user.roles[0].name
                else:
                    user_role = "Admin"

            conversations.append({
                "user_id": other_user_id,
                "user_name": other_user.name if hasattr(other_user, 'name') else (other_user.username if hasattr(other_user, 'username') else ""),
                "user_role": user_role,
                "last_message": msg.content,
                "last_message_time": msg.created_at.strftime("%Y-%m-%d %H:%M:%S") if msg.created_at else "",
                "unread_count": unread_count
            })
    
    return jsonify({
        "success": True,
        "conversations": conversations
    })

# =====================================================
# Serve Uploaded Files
# =====================================================
@messages_bp.route("/file/<path:filename>")
def serve_file(filename):
    upload_folder = current_app.config.get('UPLOAD_FOLDER', 'static/uploads/messages')
    file_path = os.path.join(upload_folder, filename)
    
    if os.path.exists(file_path):
        return send_file(file_path)
    else:
        return jsonify({"error": "الملف غير موجود"}), 404

