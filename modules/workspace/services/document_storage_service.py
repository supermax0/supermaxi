from __future__ import annotations

import hashlib
import os
import threading
import time
from datetime import datetime
from typing import List, Optional

from flask import current_app
from werkzeug.datastructures import FileStorage

from extensions import db

from modules.workspace.models.workspace_document import WorkspaceDocument
from modules.workspace.models.workspace_session import WorkspaceSession
from modules.workspace.services import event_bus
from modules.workspace.services.file_validation_service import FileValidationError, validate_upload


class DocumentStorageService:
    @staticmethod
    def _upload_root() -> str:
        folder = current_app.config.get("WORKSPACE_UPLOAD_FOLDER", "static/uploads/workspace")
        if os.path.isabs(folder):
            return folder
        return os.path.join(current_app.root_path, folder)

    @staticmethod
    def _tenant_folder(tenant_slug: Optional[str]) -> str:
        slug = (tenant_slug or "default").strip() or "default"
        slug = slug.replace("..", "").replace("/", "").replace("\\", "")
        return slug

    @staticmethod
    def list_session_documents(session_id: str, include_deleted: bool = False) -> List[WorkspaceDocument]:
        query = WorkspaceDocument.query.filter_by(session_id=session_id)
        if not include_deleted:
            query = query.filter(WorkspaceDocument.status != "deleted")
        return query.order_by(WorkspaceDocument.created_at.asc()).all()

    @staticmethod
    def get_document(document_id: str) -> Optional[WorkspaceDocument]:
        return WorkspaceDocument.query.get(document_id)

    @staticmethod
    def get_document_for_access(
        document_id: str,
        user_id: Optional[int] = None,
        tenant_slug: Optional[str] = None,
    ) -> Optional[WorkspaceDocument]:
        doc = WorkspaceDocument.query.get(document_id)
        if not doc or doc.status == "deleted":
            return None
        if tenant_slug and doc.tenant_slug and doc.tenant_slug != tenant_slug:
            return None
        session = WorkspaceSession.query.get(doc.session_id)
        if not session:
            return None
        if user_id is not None and session.user_id is not None and session.user_id != user_id:
            return None
        return doc

    @staticmethod
    def upload_to_session(
        session: WorkspaceSession,
        file_storage: FileStorage,
        user_id: Optional[int] = None,
    ) -> WorkspaceDocument:
        if not file_storage or not file_storage.filename:
            raise FileValidationError("لم يتم اختيار ملف")

        filename = file_storage.filename
        file_storage.stream.seek(0, os.SEEK_END)
        file_size = file_storage.stream.tell()
        file_storage.stream.seek(0)

        safe_name, mime_type = validate_upload(filename, file_storage.mimetype, file_size)

        event_bus.emit_event(
            session.id,
            "document.upload.started",
            {"filename": filename},
            message="جاري رفع المستند...",
            user_id=user_id,
        )
        event_bus.emit_event(
            session.id,
            "report.appended",
            {"line": "جاري رفع المستند..."},
            message="جاري رفع المستند...",
            user_id=user_id,
        )

        doc_id = None
        doc = WorkspaceDocument(
            session_id=session.id,
            tenant_slug=session.tenant_slug,
            user_id=user_id or session.user_id,
            original_filename=filename,
            stored_filename="",
            storage_path="",
            mime_type=mime_type,
            file_ext=os.path.splitext(safe_name)[1].lower(),
            file_size=file_size,
            status="uploaded",
        )
        db.session.add(doc)
        db.session.flush()
        doc_id = doc.id

        tenant_dir = DocumentStorageService._tenant_folder(session.tenant_slug)
        rel_dir = os.path.join(tenant_dir, session.id)
        abs_dir = os.path.join(DocumentStorageService._upload_root(), rel_dir)
        os.makedirs(abs_dir, exist_ok=True)

        stored_name = f"{doc_id}_{safe_name}"
        abs_path = os.path.join(abs_dir, stored_name)
        abs_path = os.path.normpath(abs_path)
        if not abs_path.startswith(os.path.normpath(DocumentStorageService._upload_root())):
            raise FileValidationError("مسار التخزين غير صالح")

        file_storage.save(abs_path)

        sha256 = DocumentStorageService._sha256_file(abs_path)
        rel_path = os.path.join(rel_dir, stored_name).replace("\\", "/")

        doc.stored_filename = stored_name
        doc.storage_path = rel_path
        doc.public_preview_path = f"/workspace/api/documents/{doc.id}/preview"
        doc.sha256 = sha256
        doc.status = "preview_ready"
        doc.updated_at = datetime.utcnow()
        db.session.commit()

        DocumentStorageService._link_document_to_session(session, doc, user_id)
        DocumentStorageService._start_visual_scan(session.id, user_id)

        return doc

    @staticmethod
    def _sha256_file(path: str) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def _link_document_to_session(
        session: WorkspaceSession,
        doc: WorkspaceDocument,
        user_id: Optional[int],
    ) -> None:
        meta = session.get_metadata()
        doc_ids = list(meta.get("document_ids") or [])
        if doc.id not in doc_ids:
            doc_ids.append(doc.id)
        meta["document_ids"] = doc_ids
        meta["active_document_id"] = doc.id
        meta["phase"] = 2
        session.set_metadata(meta)

        windows = session.get_windows()
        for w in windows:
            if w.get("type") == "document_viewer":
                w["status"] = "ready"
                w["props"] = {
                    **(w.get("props") or {}),
                    "documentId": doc.id,
                    "fileName": doc.original_filename,
                    "mimeType": doc.mime_type,
                    "previewUrl": doc.preview_url(),
                    "fileSize": doc.file_size,
                    "status": "preview_ready",
                    "scan_active": False,
                    "scan_progress": 0,
                }
        session.set_windows(windows)

        avatar = session.get_avatar_state()
        avatar["mode"] = "reading_document"
        avatar["position"] = {"x": 0.62, "y": 0.5}
        avatar["speech"] = "تم استلام المستند. أستطيع الآن عرضه داخل مساحة العمل."
        session.set_avatar_state(avatar)
        session.updated_at = datetime.utcnow()
        db.session.commit()

        event_bus.emit_event(
            session.id,
            "document.uploaded",
            {"document": doc.to_dict()},
            message="تم رفع المستند بنجاح",
            user_id=user_id,
        )
        event_bus.emit_event(
            session.id,
            "report.appended",
            {"line": "تم رفع المستند بنجاح."},
            message="تم رفع المستند بنجاح.",
            user_id=user_id,
        )
        event_bus.emit_event(
            session.id,
            "report.appended",
            {"line": "تم رفع المستند وربطه بجلسة العمل."},
            message="تم رفع المستند وربطه بجلسة العمل.",
            user_id=user_id,
        )
        event_bus.emit_event(
            session.id,
            "avatar.updated",
            {"avatar_state": avatar},
            user_id=user_id,
        )
        event_bus.emit_event(
            session.id,
            "window.updated",
            {"windows": windows},
            user_id=user_id,
        )
        event_bus.emit_event(
            session.id,
            "document.preview.ready",
            {"document": doc.to_dict()},
            user_id=user_id,
        )

    @staticmethod
    def _start_visual_scan(session_id: str, user_id: Optional[int]) -> None:
        app = current_app._get_current_object()

        def run_scan():
            try:
                from flask import g, has_app_context

                def body():
                    for progress in (10, 30, 55, 80, 100):
                        event_bus.emit_event(
                            session_id,
                            "document.scan.updated",
                            {
                                "active": progress < 100,
                                "progress": progress,
                                "scanMode": "preview",
                                "currentPage": 1,
                            },
                            user_id=user_id,
                        )
                        time.sleep(0.25)
                    event_bus.emit_event(
                        session_id,
                        "document.scan.updated",
                        {
                            "active": False,
                            "progress": 100,
                            "scanMode": "preview",
                            "currentPage": 1,
                        },
                        user_id=user_id,
                    )

                if has_app_context():
                    body()
                else:
                    with app.app_context():
                        body()
            except Exception:
                pass

        threading.Thread(target=run_scan, daemon=True).start()

    @staticmethod
    def resolve_absolute_path(doc: WorkspaceDocument) -> str:
        root = DocumentStorageService._upload_root()
        abs_path = os.path.normpath(os.path.join(root, doc.storage_path.replace("/", os.sep)))
        if not abs_path.startswith(os.path.normpath(root)):
            raise FileValidationError("مسار الملف غير صالح")
        if not os.path.isfile(abs_path):
            raise FileNotFoundError("الملف غير موجود على القرص")
        return abs_path

    @staticmethod
    def soft_delete_document(
        doc: WorkspaceDocument,
        user_id: Optional[int] = None,
    ) -> WorkspaceDocument:
        doc.status = "deleted"
        doc.updated_at = datetime.utcnow()
        db.session.commit()
        event_bus.emit_event(
            doc.session_id,
            "document.deleted",
            {"document_id": doc.id},
            user_id=user_id,
        )
        return doc

    @staticmethod
    def enrich_session_dict(session: WorkspaceSession) -> dict:
        from modules.workspace.services.document_intelligence.document_intelligence_service import (
            DocumentIntelligenceService,
        )

        data = session.to_dict()
        docs = DocumentStorageService.list_session_documents(session.id)
        data["documents"] = [
            DocumentIntelligenceService.enrich_document_dict(d.to_dict()) for d in docs
        ]
        active_id = (session.get_metadata() or {}).get("active_document_id")
        if active_id:
            active = next((d for d in docs if d.id == active_id), None)
            if active:
                data["active_document"] = DocumentIntelligenceService.enrich_document_dict(
                    active.to_dict()
                )
        results = DocumentIntelligenceService.list_session_results(session.id)
        data["intelligence_results"] = [r.to_dict() for r in results]
        from modules.workspace.services.courier_settlement.courier_readonly_analysis_service import (
            CourierReadonlyAnalysisService,
        )

        courier = CourierReadonlyAnalysisService.get_latest_for_session(session.id)
        if courier:
            data["courier_analysis"] = courier.to_dict()
        return data
