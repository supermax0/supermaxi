/**
 * Session state store — pub/sub for workspace UI.
 */
class SessionStore {
  constructor() {
    this.session = null;
    this.listeners = new Set();
  }

  setSession(session) {
    this.session = session;
    this._notify();
  }

  patchSession(patch) {
    if (!this.session) return;
    this.session = { ...this.session, ...patch };
    this._notify();
  }

  getSession() {
    return this.session;
  }

  subscribe(fn) {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  _notify() {
    this.listeners.forEach((fn) => {
      try {
        fn(this.session);
      } catch (e) {
        console.error("SessionStore listener error", e);
      }
    });
  }
}

window.WorkspaceSessionStore = SessionStore;
