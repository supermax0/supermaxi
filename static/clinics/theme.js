/* Clinics appearance is independent of the accounting workspace preference. */
(() => {
  const storageKey = "finora-clinics-theme";
  const valid = (theme) => theme === "light" || theme === "dark";
  const current = () => document.documentElement.dataset.theme === "dark" ? "dark" : "light";
  const apply = (theme, persist = false) => {
    theme = valid(theme) ? theme : "light";
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", theme === "dark" ? "#0b141b" : "#f4f7fa");
    if (persist) {
      try { localStorage.setItem(storageKey, theme); } catch (_) {}
    }
    document.querySelectorAll('[data-clinic-theme]').forEach((input) => {
      input.checked = input.value === theme;
    });
    window.dispatchEvent(new CustomEvent("finora:themechange", { detail: { theme } }));
  };
  let saved;
  try { saved = localStorage.getItem(storageKey); } catch (_) {}
  window.ClinicsTheme = { current, set: (theme) => apply(theme, true) };
  apply(saved);
  window.addEventListener("storage", (event) => {
    if (event.key === storageKey || event.key === null) apply(event.newValue);
  });
})();
