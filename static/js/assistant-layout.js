/* Keep the shared assistant launcher clear of fixed clinic navigation and actions. */
(() => {
  const start = () => {
    const root = document.documentElement;
    const viewport = window.visualViewport;
    const bars = new Set();
    let frame;
    const set = (key, value) => {
      if (root.style.getPropertyValue(key) !== value) root.style.setProperty(key, value);
    };
    const update = () => {
      frame = null;
      let clearance = 0;
      const visibleTop = viewport?.offsetTop || 0;
      const visibleHeight = viewport?.height || innerHeight;
      const visibleBottom = visibleTop + visibleHeight;
      const currentBars = new Set(document.querySelectorAll('.cx-mobile-nav,.cx-ws-footer'));
      for (const bar of bars) {
        if (!currentBars.has(bar)) { observer?.unobserve(bar); bars.delete(bar); }
      }
      for (const bar of currentBars) {
        if (!bars.has(bar)) { bars.add(bar); observer?.observe(bar, {box: 'border-box'}); }
        const style = getComputedStyle(bar);
        const rect = bar.getBoundingClientRect();
        if (style.position !== 'fixed' || style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0) continue;
        if (rect.width && rect.height && rect.top < visibleBottom && rect.bottom > visibleTop) {
          clearance = Math.max(clearance, visibleBottom - rect.top + 14);
        }
      }
      set('--finora-assistant-bottom', clearance ? `${Math.ceil(clearance)}px` : 'max(24px, env(safe-area-inset-bottom, 0px))');
      set('--finora-assistant-keyboard-inset', `${Math.max(0,Math.round(innerHeight - visibleBottom))}px`);
      set('--finora-assistant-viewport-height', `${Math.round(visibleHeight)}px`);
      set('--finora-assistant-viewport-top', `${Math.round(visibleTop)}px`);
      window.dispatchEvent(new Event('finora:assistantlayout'));
    };
    const schedule = () => { if (!frame) frame = requestAnimationFrame(update); };
    const observer = window.ResizeObserver ? new ResizeObserver(schedule) : null;
    new MutationObserver(schedule).observe(document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ['class', 'hidden'] });
    window.addEventListener('resize', schedule);
    document.addEventListener('transitionend', event => {
      if (event.target.matches?.('.cx-mobile-nav,.cx-ws-footer')) schedule();
    }, true);
    viewport?.addEventListener('resize', schedule);
    viewport?.addEventListener('scroll', schedule);
    update();
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, { once: true });
  else start();
})();
