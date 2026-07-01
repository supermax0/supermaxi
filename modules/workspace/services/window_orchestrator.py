from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

from modules.workspace.models.workspace_session import WorkspaceSession
from modules.workspace.services import event_bus

DEFAULT_POSITIONS = {
    "document_viewer": {"x": 520, "y": 100, "width": 420, "height": 520, "placement": "right"},
    "live_report": {"x": 40, "y": 100, "width": 380, "height": 480, "placement": "left"},
    "assistant_notes": {"x": 280, "y": 420, "width": 340, "height": 220, "placement": "bottom"},
    "approval_panel": {"x": 200, "y": 360, "width": 400, "height": 240, "placement": "bottom"},
    "workflow_selector": {"x": 180, "y": 400, "width": 420, "height": 260, "placement": "bottom"},
    "session_timeline": {"x": 40, "y": 420, "width": 360, "height": 220, "placement": "bottom"},
    "document_intelligence": {"x": 40, "y": 320, "width": 400, "height": 360, "placement": "left"},
    "raw_table_preview": {"x": 200, "y": 480, "width": 480, "height": 280, "placement": "bottom"},
    "courier_settlement_analysis": {"x": 32, "y": 72, "width": 470, "height": 640, "placement": "left"},
    "courier_rows": {"x": 40, "y": 730, "width": 720, "height": 300, "placement": "bottom"},
    "courier_issues": {"x": 900, "y": 430, "width": 360, "height": 260, "placement": "right"},
    "financial_preview": {"x": 900, "y": 120, "width": 380, "height": 300, "placement": "center"},
}

DOC_PREVIEW_KEYS = frozenset({
    "documentId", "fileName", "mimeType", "previewUrl", "fileSize", "status",
})

# Windows that stay open across workflow changes.
CORE_WINDOW_TYPES = frozenset({"document_viewer", "live_report"})

# Windows that belong to a specific workflow/analysis and must be cleared
# when a new workflow starts, so the workspace never piles up stale cards.
TRANSIENT_WINDOW_TYPES = frozenset({
    "approval_panel",
    "workflow_selector",
    "document_intelligence",
    "raw_table_preview",
    "courier_settlement_analysis",
    "courier_rows",
    "courier_issues",
    "financial_preview",
    "assistant_notes",
})


def _window_identity(window: Dict[str, Any]) -> str:
    props = window.get("props") or {}
    key = props.get("analysisId") or props.get("documentId") or ""
    return f"{window.get('type')}::{key}"


class WindowOrchestrator:
  @staticmethod
  def _find_window(
      windows: List[Dict],
      window_type: str,
      window_id: Optional[str] = None,
      document_id: Optional[str] = None,
  ):
      for w in windows:
          if window_id and w.get("id") == window_id:
              return w
          if w.get("type") != window_type:
              continue
          if document_id:
              if (w.get("props") or {}).get("documentId") == document_id:
                  return w
              continue
          return w
      return None

  @staticmethod
  def _merge_props(existing: Dict, patch: Dict, window_type: str) -> Dict:
      merged = {**(existing or {}), **(patch or {})}
      if window_type == "document_viewer" and existing:
          for key in DOC_PREVIEW_KEYS:
              if existing.get(key) and key not in (patch or {}):
                  merged[key] = existing[key]
          if existing.get("previewUrl") and not patch.get("error"):
              merged.setdefault("loading", False)
      return merged

  @staticmethod
  def ensure_window(session: WorkspaceSession, spec: Dict[str, Any], step_id: str) -> Dict[str, Any]:
      windows = session.get_windows()
      wtype = spec.get("type")
      existing = WindowOrchestrator._find_window(windows, wtype)
      defaults = DEFAULT_POSITIONS.get(wtype, {"x": 200, "y": 200, "width": 360, "height": 300, "placement": "center"})
      pos = spec.get("position") or {
          "x": defaults["x"],
          "y": defaults["y"],
          "width": defaults["width"],
          "height": defaults["height"],
      }

      if existing:
          existing["title"] = spec.get("title") or existing.get("title")
          existing["placement"] = spec.get("placement") or existing.get("placement") or defaults.get("placement")
          existing["opened_by_step_id"] = step_id
          existing["reason"] = spec.get("reason") or existing.get("reason", "")
          existing["props"] = WindowOrchestrator._merge_props(
              existing.get("props") or {},
              spec.get("props") or {},
              wtype,
          )
          if spec.get("status"):
              existing["status"] = spec["status"]
          return existing

      window = {
          "id": spec.get("id") or f"win_{wtype}_1",
          "type": wtype,
          "title": spec.get("title") or wtype,
          "status": spec.get("status", "ready"),
          "position": pos,
          "placement": spec.get("placement") or defaults.get("placement", "center"),
          "z_index": spec.get("z_index", 10 + len(windows)),
          "opened_by_step_id": step_id,
          "reason": spec.get("reason", f"فتح {wtype}"),
          "props": spec.get("props") or {},
          "interactive": spec.get("interactive", wtype in ("approval_panel", "workflow_selector")),
      }
      windows.append(window)
      return window

  @staticmethod
  def open_window(session: WorkspaceSession, spec: Dict[str, Any], step_id: str) -> Dict[str, Any]:
      windows = session.get_windows()
      wtype = spec.get("type")
      existing = WindowOrchestrator._find_window(windows, wtype)
      if existing and not spec.get("allow_duplicate"):
          existing.update({
              "title": spec.get("title", existing.get("title")),
              "status": spec.get("status", existing.get("status")),
              "opened_by_step_id": step_id,
              "props": WindowOrchestrator._merge_props(
                  existing.get("props") or {},
                  spec.get("props") or {},
                  wtype,
              ),
          })
          if spec.get("position"):
              existing["position"] = spec["position"]
          session.set_windows(windows)
          return existing

      window = WindowOrchestrator.ensure_window(session, spec, step_id)
      if window not in windows:
          windows.append(window)
      session.set_windows(windows)
      event_bus.emit_event(
          session.id,
          "window.opened",
          {"window": copy.deepcopy(window)},
          message=f"فتح نافذة {window.get('title')}",
      )
      return window

  @staticmethod
  def update_window(session: WorkspaceSession, window_type: str, patch: Dict[str, Any], step_id: str) -> None:
      windows = session.get_windows()
      target = WindowOrchestrator._find_window(windows, window_type)
      if not target:
          return
      if patch.get("status"):
          target["status"] = patch["status"]
      if patch.get("title"):
          target["title"] = patch["title"]
      props_patch = patch.get("props") or patch.get("patch", {}).get("props") or patch.get("patch") or {}
      if isinstance(props_patch, dict) and "props" not in props_patch:
          target["props"] = WindowOrchestrator._merge_props(
              target.get("props") or {},
              props_patch,
              window_type,
          )
      elif patch.get("props"):
          target["props"] = WindowOrchestrator._merge_props(
              target.get("props") or {},
              patch["props"],
              window_type,
          )
      target["opened_by_step_id"] = step_id
      session.set_windows(windows)

  @staticmethod
  def apply_step_windows(session: WorkspaceSession, step: Dict[str, Any]) -> None:
      step_id = step.get("id", "")

      for spec in step.get("ensure_windows") or []:
          WindowOrchestrator.ensure_window(session, spec, step_id)

      for spec in step.get("open_windows") or []:
          WindowOrchestrator.open_window(session, spec, step_id)

      for upd in step.get("update_windows") or []:
          wtype = upd.get("type")
          patch = upd.get("patch") or upd
          WindowOrchestrator.update_window(session, wtype, patch, step_id)

      session.set_windows(session.get_windows())
      event_bus.emit_event(
          session.id,
          "window.updated",
          {"windows": session.get_windows()},
      )

  @staticmethod
  def close_window(session: WorkspaceSession, window_id: str) -> None:
      windows = [w for w in session.get_windows() if w.get("id") != window_id]
      session.set_windows(windows)
      event_bus.emit_event(session.id, "window.updated", {"windows": windows})

  # ------------------------------------------------------------------
  # Lifecycle helpers
  # ------------------------------------------------------------------
  @staticmethod
  def close_window_types(session: WorkspaceSession, types) -> List[Dict[str, Any]]:
      """Remove all windows whose type is in `types`. Returns remaining windows."""
      types = set(types or [])
      windows = [w for w in session.get_windows() if w.get("type") not in types]
      session.set_windows(windows)
      return windows

  @staticmethod
  def cleanup_for_workflow_start(
      session: WorkspaceSession,
      workflow_type: str,
      emit: bool = True,
      user_id: Optional[int] = None,
  ) -> List[Dict[str, Any]]:
      """
      Preserve core windows (document_viewer, live_report) and remove every
      transient window from a previous workflow (approval panels, selectors,
      old analysis/preview windows). This is what stops overlapping stale
      cards and prevents a demo approval panel from leaking into read-only
      courier analysis.
      """
      to_remove = set(TRANSIENT_WINDOW_TYPES)
      # For mock workspace we still clear old transient windows; its own steps
      # re-open the demo approval panel when the approval step runs.
      windows = [w for w in session.get_windows() if w.get("type") not in to_remove]
      session.set_windows(windows)
      if emit:
          event_bus.emit_event(
              session.id,
              "window.updated",
              {"windows": windows},
              message="تنظيف نوافذ سير العمل السابق",
              user_id=user_id,
          )
      return windows

  @staticmethod
  def normalize_windows(
      session: WorkspaceSession,
      workflow_type: Optional[str] = None,
  ) -> List[Dict[str, Any]]:
      """
      De-duplicate windows by identity (type + document/analysis id) and drop
      a stale approval_panel unless the current workflow is actively waiting
      for the mock demo approval.
      Used on session restore so a refresh yields a clean layout.
      """
      wf = workflow_type or session.workflow_type
      keep_mock_approval = wf == "mock_workspace" and session.status == "waiting_approval"
      seen: Dict[str, Dict[str, Any]] = {}
      order: List[str] = []
      for w in session.get_windows():
          if w.get("type") == "approval_panel" and not keep_mock_approval:
              continue
          ident = _window_identity(w)
          if ident not in seen:
              order.append(ident)
          seen[ident] = w  # keep latest for the identity
      windows = [seen[i] for i in order]
      session.set_windows(windows)
      return windows

  @staticmethod
  def ensure_document_intelligence_window(
      session: WorkspaceSession,
      document_id: str,
      props: Dict[str, Any],
      step_id: str,
  ) -> Dict[str, Any]:
      windows = session.get_windows()
      existing = WindowOrchestrator._find_window(
          windows, "document_intelligence", document_id=document_id
      )
      spec = {
          "id": f"win_doc_intel_{document_id[:8]}",
          "type": "document_intelligence",
          "title": "فهم المستند",
          "placement": "left",
          "props": props,
          "status": props.get("status", "ready"),
      }
      if existing:
          existing["title"] = spec["title"]
          existing["status"] = spec["status"]
          existing["props"] = WindowOrchestrator._merge_props(
              existing.get("props") or {},
              props,
              "document_intelligence",
          )
          existing["opened_by_step_id"] = step_id
          session.set_windows(windows)
          return existing

      window = WindowOrchestrator.ensure_window(session, spec, step_id)
      if window not in windows:
          windows.append(window)
      session.set_windows(windows)
      return window

  @staticmethod
  def ensure_courier_window(
      session: WorkspaceSession,
      window_type: str,
      analysis_id: str,
      props: Dict[str, Any],
      step_id: str,
  ) -> Dict[str, Any]:
      windows = session.get_windows()
      existing = None
      for w in windows:
          if w.get("type") == window_type and (w.get("props") or {}).get("analysisId") == analysis_id:
              existing = w
              break

      titles = {
          "courier_settlement_analysis": "تقرير تحليل كشف شركة التوصيل",
          "courier_rows": "صفوف الكشف",
          "courier_issues": "مشاكل الكشف",
          "financial_preview": "معاينة مالية",
          "assistant_notes": "ملاحظات وتحليل LEON",
      }
      placements = {
          "courier_settlement_analysis": "left",
          "courier_rows": "bottom",
          "courier_issues": "right",
          "financial_preview": "center",
          "assistant_notes": "bottom",
      }
      courier_positions = {
          "assistant_notes": {"x": 900, "y": 430, "width": 380, "height": 240, "placement": "bottom"},
      }
      spec = {
          "id": f"win_{window_type}_{analysis_id[:8]}",
          "type": window_type,
          "title": titles.get(window_type, window_type),
          "placement": placements.get(window_type, "center"),
          "props": {**props, "analysisId": analysis_id},
      }
      if window_type in courier_positions:
          spec["position"] = courier_positions[window_type]
      if existing:
          existing["title"] = spec["title"]
          existing["props"] = WindowOrchestrator._merge_props(
              existing.get("props") or {}, spec["props"], window_type
          )
          existing["opened_by_step_id"] = step_id
          session.set_windows(windows)
          return existing

      window = WindowOrchestrator.ensure_window(session, spec, step_id)
      if window not in windows:
          windows.append(window)
      session.set_windows(windows)
      return window

  @staticmethod
  def ensure_raw_table_preview_window(
      session: WorkspaceSession,
      document_id: str,
      tables: List[Dict[str, Any]],
      step_id: str,
  ) -> Dict[str, Any]:
      windows = session.get_windows()
      existing = WindowOrchestrator._find_window(
          windows, "raw_table_preview", document_id=document_id
      )
      props = {
          "documentId": document_id,
          "tables": tables,
          "maxRows": 100,
          "disclaimer": "جداول خام — بدون تفسير أو ترحيل.",
      }
      spec = {
          "id": f"win_raw_table_{document_id[:8]}",
          "type": "raw_table_preview",
          "title": "معاينة الجداول الخام",
          "placement": "bottom",
          "props": props,
      }
      if existing:
          existing["props"] = WindowOrchestrator._merge_props(
              existing.get("props") or {},
              props,
              "raw_table_preview",
          )
          existing["opened_by_step_id"] = step_id
          session.set_windows(windows)
          return existing

      window = WindowOrchestrator.ensure_window(session, spec, step_id)
      if window not in windows:
          windows.append(window)
      session.set_windows(windows)
      return window
