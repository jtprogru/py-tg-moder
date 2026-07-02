/* Dashboard charts (Chart.js). Colors come from the CSS custom properties on
 * <body>, so light/dark stay in sync with the stylesheet; on a color-scheme
 * change the charts are rebuilt with the other mode's palette steps. */
(function () {
  "use strict";

  const dataEl = document.getElementById("chart-data");
  if (!dataEl || typeof Chart === "undefined") return;
  const DATA = JSON.parse(dataEl.textContent);

  const cssVar = (name) => getComputedStyle(document.body).getPropertyValue(name).trim();
  let charts = [];

  function baseOptions() {
    const muted = cssVar("--text-muted");
    const grid = cssVar("--grid");
    const baseline = cssVar("--baseline");
    Chart.defaults.font.family = 'system-ui, -apple-system, "Segoe UI", sans-serif';
    Chart.defaults.font.size = 12;
    return {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: cssVar("--surface-1"),
          titleColor: cssVar("--text-primary"),
          bodyColor: cssVar("--text-secondary"),
          borderColor: baseline,
          borderWidth: 1,
          displayColors: true,
          boxWidth: 8,
          boxHeight: 8,
        },
      },
      scales: {
        x: {
          grid: { display: false },
          border: { color: baseline },
          ticks: { color: muted, maxTicksLimit: 10, maxRotation: 0 },
        },
        y: {
          beginAtZero: true,
          grid: { color: grid },
          border: { display: false },
          ticks: { color: muted, precision: 0, maxTicksLimit: 6 },
        },
      },
      interaction: { mode: "index", intersect: false },
    };
  }

  function build() {
    charts.forEach((chart) => chart.destroy());
    charts = [];
    const s1 = cssVar("--series-1");
    const s2 = cssVar("--series-2");

    // Messages per day: single series -> one hue, no legend (the title names it).
    const messagesEl = document.getElementById("chart-messages");
    if (messagesEl) {
      charts.push(new Chart(messagesEl, {
        type: "bar",
        data: {
          labels: DATA.days,
          datasets: [{
            label: "Сообщения",
            data: DATA.messages,
            backgroundColor: s1,
            borderRadius: 4,
            borderSkipped: "start", // round the data end only, stay anchored to the baseline
            categoryPercentage: 0.85,
          }],
        },
        options: baseOptions(),
      }));
    }

    // Joins vs leaves: two entities -> categorical slots 1/2, legend present.
    const membersEl = document.getElementById("chart-members");
    if (membersEl) {
      const options = baseOptions();
      options.plugins.legend = {
        display: true,
        position: "bottom",
        labels: { color: cssVar("--text-secondary"), boxWidth: 12, boxHeight: 12, usePointStyle: true },
      };
      charts.push(new Chart(membersEl, {
        type: "line",
        data: {
          labels: DATA.days,
          datasets: [
            { label: "Вступления", data: DATA.joins, borderColor: s1, backgroundColor: s1, borderWidth: 2, pointRadius: 0, pointHoverRadius: 4 },
            { label: "Выходы", data: DATA.leaves, borderColor: s2, backgroundColor: s2, borderWidth: 2, pointRadius: 0, pointHoverRadius: 4 },
          ],
        },
        options: options,
      }));
    }

    // Actions breakdown: magnitude comparison -> horizontal bars, one hue.
    const actionsEl = document.getElementById("chart-actions");
    if (actionsEl && DATA.actions.labels.length) {
      const options = baseOptions();
      options.indexAxis = "y";
      options.interaction = { mode: "nearest", intersect: true };
      options.scales = {
        x: {
          beginAtZero: true,
          grid: { color: cssVar("--grid") },
          border: { display: false },
          ticks: { color: cssVar("--text-muted"), precision: 0, maxTicksLimit: 6 },
        },
        y: {
          grid: { display: false },
          border: { color: cssVar("--baseline") },
          ticks: { color: cssVar("--text-secondary"), autoSkip: false },
        },
      };
      charts.push(new Chart(actionsEl, {
        type: "bar",
        data: {
          labels: DATA.actions.labels,
          datasets: [{
            label: "Действий",
            data: DATA.actions.counts,
            backgroundColor: s1,
            borderRadius: 4,
            borderSkipped: "start",
            categoryPercentage: 0.7,
          }],
        },
        options: options,
      }));
    }
  }

  build();
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", build);
})();
