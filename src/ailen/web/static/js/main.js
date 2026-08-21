// AILEN panel: progressive enhancement only. Sin framework.
// Si JS no corre, la página sigue siendo usable con el primer render.
(function () {
  "use strict";

  var stateEl = document.getElementById("assistant-state");
  if (!stateEl) return; // no es el dashboard

  var healthEl = document.getElementById("health-overall");
  var componentsEl = document.getElementById("health-components");
  var servicesEl = document.getElementById("services");

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function kvList(obj) {
    return Object.keys(obj).map(function (k) {
      return "<li><span>" + esc(k) + '</span><span class="status-' + esc(obj[k]) + '">' +
        esc(obj[k]) + "</span></li>";
    }).join("");
  }

  function refresh() {
    fetch("/api/status", { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data) return;
        stateEl.textContent = data.assistant_state;
        healthEl.textContent = data.health.overall;
        healthEl.className = "big status-" + data.health.overall;
        componentsEl.innerHTML = kvList(data.health.components);
        servicesEl.innerHTML = kvList(data.services);
      })
      .catch(function () { /* offline: se reintenta en el próximo tick */ });
  }

  setInterval(refresh, 5000);
})();
