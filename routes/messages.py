from flask import Blueprint, render_template, request, jsonify, session, send_file, current_app
from extensions import db
from models.message import Message
from models.employee import Employee
from models.channel import ChannelMessage, ChannelRead
from models.call import CallSession, CallSignal
from sqlalchemy import or_, and_, inspect, text
from datetime import datetime
import os
import json
import uuid
from werkzeug.utils import secure_filename

messages_bp = Blueprint("messages", __name__, url_prefix="/messages")


ALLOWED_IMAGE_EXT = {"jpg", "jpeg", "png", "gif", "webp", "bmp"}
ALLOWED_VIDEO_EXT = {"mp4", "webm", "ogg", "mov", "avi", "mkv"}
ALLOWED_AUDIO_EXT = {"mp3", "wav", "ogg", "m4a", "aac", "flac"}


def _save_uploaded_file(file):
    """يحفظ ملفاً مرفقاً ويعيد (file_type, file_path, file_name)."""
    upload_folder = "static/uploads/messages"
    os.makedirs(upload_folder, exist_ok=True)

    filename = secure_filename(file.filename)
    ext = filename.rsplit(".", 1)[1].lower() if "." in filename else ""

    if ext in ALLOWED_IMAGE_EXT:
        file_type = "image"
    elif ext in ALLOWED_VIDEO_EXT:
        file_type = "video"
    elif ext in ALLOWED_AUDIO_EXT:
        file_type = "audio"
    else:
        file_type = "file"

    unique_filename = f"{uuid.uuid4()}.{ext}" if ext else f"{uuid.uuid4()}"
    file_path_full = os.path.join(upload_folder, unique_filename)
    file.save(file_path_full)

    file_path = f"/{upload_folder.replace(chr(92), '/')}/{unique_filename}"
    return file_type, file_path, filename


def _is_admin(user):
    return bool(user and getattr(user, "role", None) == "admin")


def _ensure_messages_schema():
    """Lightweight migration: make sure `message.is_edited` / `reply_to_id` exist."""
    try:
        inspector = inspect(db.engine)
        if "message" not in inspector.get_table_names():
            return

        columns = {col["name"] for col in inspector.get_columns("message")}
        if "is_edited" not in columns:
            db.session.execute(text("ALTER TABLE message ADD COLUMN is_edited BOOLEAN DEFAULT 0"))
            db.session.commit()
        if "reply_to_id" not in columns:
            db.session.execute(text("ALTER TABLE message ADD COLUMN reply_to_id INTEGER"))
            db.session.commit()
    except Exception as e:
        db.session.rollback()
        # Ignore race/duplicate column errors and keep requests alive.
        if "duplicate column" not in str(e).lower():
            print(f"[messages] schema ensure failed: {e}")


def _ensure_channel_schema():
    """Create channel tables + employee.last_active for existing tenant DBs."""
    try:
        inspector = inspect(db.engine)
        tables = set(inspector.get_table_names())

        # إنشاء جداول القناة إن لم توجد
        to_create = [t for t in (ChannelMessage.__table__, ChannelRead.__table__)
                     if t.name not in tables]
        if to_create:
            db.Model.metadata.create_all(bind=db.engine, tables=to_create)

        # عمود آخر ظهور على جدول الموظف
        if "employee" in tables:
            emp_cols = {col["name"] for col in inspector.get_columns("employee")}
            if "last_active" not in emp_cols:
                db.session.execute(text("ALTER TABLE employee ADD COLUMN last_active DATETIME"))
                db.session.commit()
    except Exception as e:
        db.session.rollback()
        if "duplicate column" not in str(e).lower() and "already exists" not in str(e).lower():
            print(f"[messages] channel schema ensure failed: {e}")


def _ensure_call_schema():
    """Create call tables for existing tenant DBs (idempotent)."""
    try:
        inspector = inspect(db.engine)
        tables = set(inspector.get_table_names())
        to_create = [t for t in (CallSession.__table__, CallSignal.__table__)
                     if t.name not in tables]
        if to_create:
            db.Model.metadata.create_all(bind=db.engine, tables=to_create)
    except Exception as e:
        db.session.rollback()
        if "already exists" not in str(e).lower():
            print(f"[messages] call schema ensure failed: {e}")


@messages_bp.before_request
def ensure_messages_schema():
    _ensure_messages_schema()
    _ensure_channel_schema()
    _ensure_call_schema()

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
        current_user_name=current_user.name,
        is_admin=(current_user.role == "admin")
    )

# =====================================================
# Get Messages Between Two Users
# =====================================================
@messages_bp.route("/get/<int:other_user_id>")
def get_messages(other_user_id):
    if "user_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403
    
    current_user_id = session["user_id"]

    # استطلاع تزايدي: جلب ما بعد after_id فقط عند توفره
    after_id = request.args.get("after_id", type=int)

    query = Message.query.filter(
        or_(
            and_(Message.sender_id == current_user_id, Message.receiver_id == other_user_id),
            and_(Message.sender_id == other_user_id, Message.receiver_id == current_user_id)
        )
    )
    if after_id:
        query = query.filter(Message.id > after_id)

    messages = query.order_by(Message.created_at.asc()).all()

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
        reply_to_id = None
        if request.content_type and 'multipart/form-data' in request.content_type:
            # FormData request
            receiver_id = request.form.get("receiver_id")
            content = request.form.get("content", "").strip()
            reply_to_id = request.form.get("reply_to_id")
        elif request.is_json:
            # JSON request
            data = request.get_json() or {}
            receiver_id = data.get("receiver_id")
            content = data.get("content", "").strip()
            reply_to_id = data.get("reply_to_id")
        else:
            # Try both
            receiver_id = request.form.get("receiver_id") or (request.get_json() or {}).get("receiver_id")
            content = request.form.get("content", "").strip() or (request.get_json() or {}).get("content", "").strip()
            reply_to_id = request.form.get("reply_to_id")

        try:
            reply_to_id = int(reply_to_id) if reply_to_id else None
        except (TypeError, ValueError):
            reply_to_id = None
        
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
            file_name=file_name,
            reply_to_id=reply_to_id
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
    
    private_count = Message.query.filter(
        Message.receiver_id == current_user_id,
        Message.is_read == False
    ).count()

    channel_count = _channel_unread_count(current_user_id)

    return jsonify({
        "unread_count": private_count + channel_count,
        "private_count": private_count,
        "channel_count": channel_count
    })


def _channel_unread_count(user_id):
    """عدد رسائل القناة التي لم يقرأها المستخدم (باستثناء رسائله)."""
    try:
        read_ids = db.session.query(ChannelRead.channel_message_id).filter(
            ChannelRead.user_id == user_id
        ).subquery()
        return ChannelMessage.query.filter(
            ChannelMessage.sender_id != user_id,
            ~ChannelMessage.id.in_(db.session.query(read_ids.c.channel_message_id))
        ).count()
    except Exception:
        return 0

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


# =====================================================
# Channel (قناة الإعلانات - بث من الأدمن للجميع)
# =====================================================
@messages_bp.route("/channel")
def get_channel():
    if "user_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403

    current_user_id = session["user_id"]
    current_user = Employee.query.get(current_user_id)
    if not current_user:
        return jsonify({"error": "مستخدم غير موجود"}), 404

    after_id = request.args.get("after_id", type=int)

    query = ChannelMessage.query
    if after_id:
        query = query.filter(ChannelMessage.id > after_id)
    messages = query.order_by(ChannelMessage.created_at.asc()).all()

    # تعليم كل رسائل القناة كمقروءة للمستخدم الحالي
    _mark_channel_read(current_user_id)

    return jsonify({
        "success": True,
        "is_admin": _is_admin(current_user),
        "messages": [msg.to_dict() for msg in messages]
    })


def _mark_channel_read(user_id):
    """يُدرج سجلات ChannelRead للرسائل غير المقروءة لهذا المستخدم."""
    try:
        read_ids = {
            r.channel_message_id
            for r in ChannelRead.query.filter(ChannelRead.user_id == user_id).all()
        }
        query = ChannelMessage.query
        if read_ids:
            query = query.filter(~ChannelMessage.id.in_(read_ids))
        unread = query.all()

        for msg in unread:
            db.session.add(ChannelRead(channel_message_id=msg.id, user_id=user_id))
        if unread:
            db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[channel] mark read failed: {e}")


@messages_bp.route("/channel/send", methods=["POST"])
def send_channel_message():
    if "user_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403

    current_user_id = session["user_id"]
    current_user = Employee.query.get(current_user_id)
    if not _is_admin(current_user):
        return jsonify({"error": "الإرسال في القناة متاح للأدمن فقط"}), 403

    try:
        if request.content_type and 'multipart/form-data' in request.content_type:
            content = request.form.get("content", "").strip()
        elif request.is_json:
            content = (request.get_json() or {}).get("content", "").strip()
        else:
            content = request.form.get("content", "").strip()

        file_type = file_path = file_name = None
        if 'file' in request.files:
            file = request.files['file']
            if file and file.filename:
                try:
                    file_type, file_path, file_name = _save_uploaded_file(file)
                except Exception as e:
                    return jsonify({"error": f"خطأ في رفع الملف: {str(e)}"}), 500

        if not content and not file_name:
            return jsonify({"error": "محتوى الرسالة أو ملف مطلوب"}), 400

        message = ChannelMessage(
            sender_id=current_user_id,
            content=content or (f"📎 {file_name}" if file_name else ""),
            file_type=file_type,
            file_path=file_path,
            file_name=file_name
        )
        db.session.add(message)
        db.session.commit()

        # المرسل قرأ رسالته تلقائياً
        db.session.add(ChannelRead(channel_message_id=message.id, user_id=current_user_id))
        db.session.commit()

        return jsonify({"success": True, "message": message.to_dict()})
    except Exception as e:
        db.session.rollback()
        print(f"Error in send_channel_message: {e}")
        return jsonify({"error": f"حدث خطأ: {str(e)}"}), 500


@messages_bp.route("/channel/edit/<int:message_id>", methods=["PUT"])
def edit_channel_message(message_id):
    if "user_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403

    current_user = Employee.query.get(session["user_id"])
    if not _is_admin(current_user):
        return jsonify({"error": "التعديل متاح للأدمن فقط"}), 403

    message = ChannelMessage.query.get_or_404(message_id)
    data = request.get_json() or {}
    new_content = data.get("content", "").strip()
    if not new_content:
        return jsonify({"error": "محتوى الرسالة مطلوب"}), 400

    message.content = new_content
    message.is_edited = True
    db.session.commit()
    return jsonify({"success": True, "message": message.to_dict()})


@messages_bp.route("/channel/delete/<int:message_id>", methods=["DELETE"])
def delete_channel_message(message_id):
    if "user_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403

    current_user = Employee.query.get(session["user_id"])
    if not _is_admin(current_user):
        return jsonify({"error": "الحذف متاح للأدمن فقط"}), 403

    message = ChannelMessage.query.get_or_404(message_id)
    db.session.delete(message)
    db.session.commit()
    return jsonify({"success": True, "message": "تم حذف الرسالة"})


@messages_bp.route("/channel/unread-count")
def channel_unread_count():
    if "user_id" not in session:
        return jsonify({"unread_count": 0})
    return jsonify({"unread_count": _channel_unread_count(session["user_id"])})


# =====================================================
# Presence / Heartbeat / Typing (حالة الاتصال والكتابة)
# =====================================================

# مخزن ذاكرة بسيط لمؤشر الكتابة: {receiver_id: {sender_id: timestamp}}
_typing_state = {}


@messages_bp.route("/heartbeat", methods=["POST"])
def heartbeat():
    if "user_id" not in session:
        return jsonify({"success": False}), 403
    try:
        user = Employee.query.get(session["user_id"])
        if user:
            user.last_active = datetime.utcnow()
            db.session.commit()
    except Exception:
        db.session.rollback()
    return jsonify({"success": True})


@messages_bp.route("/presence/<int:other_user_id>")
def presence(other_user_id):
    if "user_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403

    other = Employee.query.get(other_user_id)
    if not other:
        return jsonify({"online": False, "last_seen": None})

    online = False
    last_seen = None
    if other.last_active:
        delta = (datetime.utcnow() - other.last_active).total_seconds()
        online = delta < 45  # نشِط خلال 45 ثانية = متصل
        last_seen = other.last_active.strftime("%Y-%m-%d %H:%M:%S")

    # هل الطرف الآخر يكتب لي؟
    typing = False
    try:
        me = session["user_id"]
        senders = _typing_state.get(me, {})
        ts = senders.get(other_user_id)
        if ts and (datetime.utcnow() - ts).total_seconds() < 6:
            typing = True
    except Exception:
        typing = False

    return jsonify({"online": online, "last_seen": last_seen, "typing": typing})


@messages_bp.route("/typing", methods=["POST"])
def typing():
    if "user_id" not in session:
        return jsonify({"success": False}), 403
    data = request.get_json(silent=True) or request.form
    receiver_id = data.get("receiver_id")
    try:
        receiver_id = int(receiver_id)
    except (TypeError, ValueError):
        return jsonify({"success": False}), 400

    _typing_state.setdefault(receiver_id, {})[session["user_id"]] = datetime.utcnow()
    return jsonify({"success": True})


# =====================================================
# Voice / Video Calls (WebRTC signaling عبر HTTP polling)
# =====================================================

def build_ice_servers():
    """يبني قائمة iceServers من الإعدادات (STUN دائماً + TURN إن توفّر)."""
    ice_servers = []
    stun = (current_app.config.get("STUN_URLS") or "").strip()
    if stun:
        urls = [u.strip() for u in stun.split(",") if u.strip()]
        if urls:
            ice_servers.append({"urls": urls})

    turn = (current_app.config.get("TURN_URLS") or "").strip()
    if turn:
        urls = [u.strip() for u in turn.split(",") if u.strip()]
        if urls:
            entry = {"urls": urls}
            user = (current_app.config.get("TURN_USERNAME") or "").strip()
            cred = (current_app.config.get("TURN_CREDENTIAL") or "").strip()
            if user:
                entry["username"] = user
            if cred:
                entry["credential"] = cred
            ice_servers.append(entry)

    if not ice_servers:
        ice_servers.append({"urls": ["stun:stun.l.google.com:19302"]})
    return ice_servers


def _can_message(caller, callee):
    """نفس منطق DM: الأدمن يراسل الجميع، والكاشير يراسل الأدمن فقط."""
    if not caller or not callee:
        return False
    if caller.role == "admin":
        return True
    return callee.role == "admin"


@messages_bp.route("/call/ice")
def call_ice():
    if "user_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403
    return jsonify({"ice_servers": build_ice_servers()})


@messages_bp.route("/call/start", methods=["POST"])
def call_start():
    if "user_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403

    current_user_id = session["user_id"]
    caller = Employee.query.get(current_user_id)
    data = request.get_json(silent=True) or {}

    try:
        callee_id = int(data.get("callee_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "المستقبل مطلوب"}), 400

    call_type = data.get("call_type", "audio")
    if call_type not in ("audio", "video"):
        call_type = "audio"

    sdp = data.get("sdp")
    if not sdp:
        return jsonify({"error": "عرض الاتصال (offer) مطلوب"}), 400

    callee = Employee.query.get(callee_id)
    if not callee:
        return jsonify({"error": "المستقبل غير موجود"}), 404
    if callee_id == current_user_id:
        return jsonify({"error": "لا يمكن الاتصال بنفسك"}), 400
    if not _can_message(caller, callee):
        return jsonify({"error": "غير مصرح بالاتصال بهذا المستخدم"}), 403

    # إنهاء أي مكالمات سابقة عالقة للمتصل
    CallSession.query.filter(
        CallSession.caller_id == current_user_id,
        CallSession.status == "ringing"
    ).update({"status": "canceled", "ended_at": datetime.utcnow()})

    call = CallSession(
        caller_id=current_user_id,
        callee_id=callee_id,
        call_type=call_type,
        status="ringing"
    )
    db.session.add(call)
    db.session.commit()

    db.session.add(CallSignal(
        call_id=call.id,
        sender_id=current_user_id,
        kind="offer",
        payload=json.dumps(sdp)
    ))
    db.session.commit()

    return jsonify({
        "success": True,
        "call_id": call.id,
        "call": call.to_dict(current_user_id),
        "ice_servers": build_ice_servers()
    })


@messages_bp.route("/call/incoming")
def call_incoming():
    if "user_id" not in session:
        return jsonify({"incoming": False})

    current_user_id = session["user_id"]
    call = CallSession.query.filter(
        CallSession.callee_id == current_user_id,
        CallSession.status == "ringing"
    ).order_by(CallSession.created_at.desc()).first()

    if not call:
        return jsonify({"incoming": False})

    # تجاهل المكالمات القديمة جداً (>60ث) واعتبارها فائتة
    if call.created_at and (datetime.utcnow() - call.created_at).total_seconds() > 60:
        call.status = "missed"
        call.ended_at = datetime.utcnow()
        db.session.commit()
        return jsonify({"incoming": False})

    return jsonify({"incoming": True, "call": call.to_dict(current_user_id)})


@messages_bp.route("/call/<int:call_id>/offer")
def call_offer(call_id):
    if "user_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403

    current_user_id = session["user_id"]
    call = CallSession.query.get_or_404(call_id)
    if current_user_id not in (call.caller_id, call.callee_id):
        return jsonify({"error": "غير مصرح"}), 403

    offer = CallSignal.query.filter_by(call_id=call_id, kind="offer").first()
    return jsonify({
        "success": True,
        "call": call.to_dict(current_user_id),
        "offer": json.loads(offer.payload) if offer and offer.payload else None
    })


@messages_bp.route("/call/<int:call_id>/answer", methods=["POST"])
def call_answer(call_id):
    if "user_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403

    current_user_id = session["user_id"]
    call = CallSession.query.get_or_404(call_id)
    if call.callee_id != current_user_id:
        return jsonify({"error": "غير مصرح"}), 403

    data = request.get_json(silent=True) or {}
    sdp = data.get("sdp")
    if not sdp:
        return jsonify({"error": "رد الاتصال (answer) مطلوب"}), 400

    call.status = "accepted"
    call.answered_at = datetime.utcnow()
    db.session.add(CallSignal(
        call_id=call.id,
        sender_id=current_user_id,
        kind="answer",
        payload=json.dumps(sdp)
    ))
    db.session.commit()
    return jsonify({"success": True})


@messages_bp.route("/call/<int:call_id>/reject", methods=["POST"])
def call_reject(call_id):
    if "user_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403

    current_user_id = session["user_id"]
    call = CallSession.query.get_or_404(call_id)
    if current_user_id not in (call.caller_id, call.callee_id):
        return jsonify({"error": "غير مصرح"}), 403

    if call.status == "ringing":
        call.status = "rejected"
        call.ended_at = datetime.utcnow()
        db.session.add(CallSignal(call_id=call.id, sender_id=current_user_id, kind="bye", payload=None))
        db.session.commit()
    return jsonify({"success": True})


@messages_bp.route("/call/<int:call_id>/end", methods=["POST"])
def call_end(call_id):
    if "user_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403

    current_user_id = session["user_id"]
    call = CallSession.query.get_or_404(call_id)
    if current_user_id not in (call.caller_id, call.callee_id):
        return jsonify({"error": "غير مصرح"}), 403

    if call.status not in ("ended", "rejected", "missed", "canceled"):
        call.status = "ended"
        call.ended_at = datetime.utcnow()
    db.session.add(CallSignal(call_id=call.id, sender_id=current_user_id, kind="bye", payload=None))
    db.session.commit()
    return jsonify({"success": True})


@messages_bp.route("/call/<int:call_id>/state")
def call_state(call_id):
    if "user_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403

    current_user_id = session["user_id"]
    call = CallSession.query.get_or_404(call_id)
    if current_user_id not in (call.caller_id, call.callee_id):
        return jsonify({"error": "غير مصرح"}), 403

    return jsonify({"success": True, "call": call.to_dict(current_user_id)})


@messages_bp.route("/call/<int:call_id>/signal", methods=["POST"])
def call_signal(call_id):
    if "user_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403

    current_user_id = session["user_id"]
    call = CallSession.query.get_or_404(call_id)
    if current_user_id not in (call.caller_id, call.callee_id):
        return jsonify({"error": "غير مصرح"}), 403

    data = request.get_json(silent=True) or {}
    kind = data.get("kind")
    if kind not in ("ice", "offer", "answer", "bye"):
        return jsonify({"error": "نوع إشارة غير صالح"}), 400

    payload = data.get("payload")
    db.session.add(CallSignal(
        call_id=call.id,
        sender_id=current_user_id,
        kind=kind,
        payload=json.dumps(payload) if payload is not None else None
    ))
    db.session.commit()
    return jsonify({"success": True})


@messages_bp.route("/call/<int:call_id>/signals")
def call_signals(call_id):
    if "user_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403

    current_user_id = session["user_id"]
    call = CallSession.query.get_or_404(call_id)
    if current_user_id not in (call.caller_id, call.callee_id):
        return jsonify({"error": "غير مصرح"}), 403

    after_id = request.args.get("after_id", type=int) or 0
    q = CallSignal.query.filter(
        CallSignal.call_id == call_id,
        CallSignal.id > after_id,
        CallSignal.sender_id != current_user_id  # فقط إشارات الطرف الآخر
    ).order_by(CallSignal.id.asc())

    signals = []
    for s in q.all():
        signals.append({
            "id": s.id,
            "kind": s.kind,
            "payload": json.loads(s.payload) if s.payload else None
        })

    return jsonify({"success": True, "signals": signals, "status": call.status})

