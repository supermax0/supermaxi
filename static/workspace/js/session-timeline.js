/**
 * Session timeline helper — tracks events for timeline window.
 */
class SessionTimelineStore {
  constructor(maxItems = 80) {
    this.maxItems = maxItems;
    this.items = [];
    this.listeners = new Set();
  }

  addFromEvent(data) {
    const id = data.id || data.event_id;
    if (id && this.items.some((i) => i.id === id)) return false;

    const item = {
      id: id || `tmp_${Date.now()}`,
      type: data.type,
      message: data.message || (data.payload && data.payload.line) || data.type,
      created_at: data.created_at || new Date().toISOString(),
    };
    this.items.push(item);
    if (this.items.length > this.maxItems) {
      this.items = this.items.slice(-this.maxItems);
    }
    this.listeners.forEach((fn) => fn(this.items));
    return true;
  }

  subscribe(fn) {
    this.listeners.add(fn);
    fn(this.items);
    return () => this.listeners.delete(fn);
  }
}

window.SessionTimelineStore = SessionTimelineStore;
