/* Presentation-only chart options; source labels and values are never modified. */
(function (root) {
  "use strict";
  const decimal = new Intl.NumberFormat("en-US", {maximumFractionDigits: 1});
  function compact(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return "0";
    const abs = Math.abs(n);
    const unit = abs >= 1e9 ? [1e9, "مليار"] : abs >= 1e6 ? [1e6, "مليون"] : abs >= 1e3 ? [1e3, "ألف"] : [1, ""];
    return decimal.format(n / unit[0]) + (unit[1] ? " " + unit[1] : "");
  }
  function moneyOptions(theme, fullNumber) {
    return {
      responsive: true, maintainAspectRatio: false, resizeDelay: 80,
      animation: root.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? false : {duration: 250},
      interaction: {mode: "index", intersect: false, axis: "x"},
      layout: {padding: {top: 12, left: 2, right: 5, bottom: 2}},
      onResize(chart, size) {
        const x = chart.options.scales.x.ticks;
        x.maxTicksLimit = size.width < 380 ? 4 : size.width < 620 ? 7 : 12;
        x.font.size = size.width < 380 ? 10 : 11;
      },
      plugins: {
        legend: {display: false},
        tooltip: {
          rtl: true, textDirection: "rtl", backgroundColor: "#ffffff", borderColor: "#e4dcf0", borderWidth: 1,
          titleColor: theme.text, bodyColor: theme.text, padding: 12, cornerRadius: 11,
          titleFont: {family: theme.font, size: 12}, bodyFont: {family: theme.font, size: 12},
          usePointStyle: true, boxWidth: 8, boxHeight: 8,
          callbacks: {label(ctx) {return ctx.dataset.label + ": " + fullNumber(ctx.parsed?.y ?? ctx.parsed ?? 0) + " د.ع";}}
        }
      },
      scales: {
        x: {border: {display: false}, grid: {display: false}, ticks: {color: theme.muted, autoSkip: true, maxTicksLimit: 7,
          maxRotation: 0, minRotation: 0, padding: 9, font: {family: theme.font, size: 11}}},
        y: {beginAtZero: true, border: {display: false}, title: {display: false, text: "د.ع", color: theme.muted, font: {family: theme.font, size: 10}},
          grid: {color: "rgba(96, 73, 136, .07)", drawTicks: false},
          ticks: {color: theme.muted, maxTicksLimit: 5, padding: 8, callback: compact, font: {family: theme.font, size: 11}}}
      }
    };
  }
  function statusTooltip(ctx, fullNumber) {
    const value = Number(ctx.parsed) || 0;
    const total = ctx.dataset.data.reduce((sum, n) => sum + (Number(n) || 0), 0);
    return ctx.label + ": " + fullNumber(value) + (total ? " (" + decimal.format(value * 100 / total) + "%)" : "");
  }
  function statusLegend(chart, list, fullNumber) {
    if (!list) return;
    list.replaceChildren();
    chart.data.labels.forEach((label, index) => {
      const item = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.setAttribute("aria-pressed", "true");
      const dot = document.createElement("span"); dot.className = "dashboard-chart-dot";
      dot.style.backgroundColor = chart.data.datasets[0].backgroundColor[index]; dot.setAttribute("aria-hidden", "true");
      const name = document.createElement("span"); name.className = "dashboard-chart-name"; name.textContent = label;
      const count = document.createElement("strong"); count.textContent = fullNumber(chart.data.datasets[0].data[index] || 0);
      button.append(dot, name, count);
      button.addEventListener("click", () => {
        chart.toggleDataVisibility(index);
        const visible = chart.getDataVisibility(index);
        button.setAttribute("aria-pressed", String(visible));
        button.classList.toggle("is-muted", !visible);
        chart.update();
      });
      item.append(button); list.append(item);
    });
  }
  root.FinoraDashboardCharts = {compact, moneyOptions, statusTooltip, statusLegend};
})(typeof window === "undefined" ? globalThis : window);
