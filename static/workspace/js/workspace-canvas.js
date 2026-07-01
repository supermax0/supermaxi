/**
 * Workspace canvas — background grid container.
 */
class WorkspaceCanvas {
  constructor(rootEl) {
    this.root = rootEl;
  }

  getSize() {
    const rect = this.root.getBoundingClientRect();
    return { width: rect.width, height: rect.height };
  }

  relativeToPixels(rel) {
    const { width, height } = this.getSize();
    return {
      x: (rel.x ?? 0.5) * width,
      y: (rel.y ?? 0.5) * height,
    };
  }
}

window.WorkspaceCanvas = WorkspaceCanvas;
