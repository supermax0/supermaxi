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
}

DOC_PREVIEW_KEYS = frozenset({
    "documentId", "fileName", "mimeType", "previewUrl", "fileSize", "status",
})


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
