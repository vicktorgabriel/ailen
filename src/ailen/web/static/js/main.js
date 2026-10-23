// AILÉN Living Appliance — Interactive Web Admin Scripts
(function () {
  "use strict";

  // 1. Mobile Sidebar Toggle
  var menuToggle = document.getElementById("menu-toggle");
  var sidebar = document.getElementById("app-sidebar");
  if (menuToggle && sidebar) {
    menuToggle.addEventListener("click", function () {
      sidebar.classList.toggle("open");
    });
  }

  // 2. Interactive Range Sliders with Dynamic Value Badges
  var rangeInputs = document.querySelectorAll(".range-synced");
  rangeInputs.forEach(function (input) {
    var badgeId = input.getAttribute("data-badge");
    var suffix = input.getAttribute("data-suffix") || "%";
    var scale = parseFloat(input.getAttribute("data-scale") || "1");
    var badge = document.getElementById(badgeId);

    if (badge) {
      input.addEventListener("input", function () {
        var val = parseFloat(input.value) / scale;
        if (scale > 1) {
          badge.textContent = val.toFixed(scale === 1000 ? 3 : 2) + (suffix === "%" ? "" : suffix);
        } else {
          badge.textContent = Math.round(val) + suffix;
        }
      });
    }
  });

  // 4. Live Connection & Telemetry Heartbeat
  var stateEl = document.getElementById("assistant-state");
  var sidebarStateEl = document.getElementById("sidebar-assistant-state");
  var healthEl = document.getElementById("health-overall");
  var componentsEl = document.getElementById("health-components");
  var servicesEl = document.getElementById("services");
  var sessionPill = document.getElementById("live-session-pill");

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function kvList(obj) {
    return Object.keys(obj).map(function (k) {
      return '<li class="kv-item"><span class="kv-key">' + esc(k) + '</span><span class="kv-val status-' + esc(obj[k]) + '">' +
        esc(obj[k]) + "</span></li>";
    }).join("");
  }

  function refreshHeartbeat() {
    fetch("/api/ping", { credentials: "same-origin" })
      .then(function (r) {
        if (r.ok) {
          if (sessionPill) {
            sessionPill.textContent = "🟢 Sincronizado";
            sessionPill.style.color = "var(--status-ok)";
          }
        } else {
          if (sessionPill) {
            sessionPill.textContent = "🟡 Sesión Inactiva";
            sessionPill.style.color = "var(--status-warn)";
          }
        }
      })
      .catch(function () {
        if (sessionPill) {
          sessionPill.textContent = "🔴 Desconectado";
          sessionPill.style.color = "var(--status-error)";
        }
      });

    if (stateEl || sidebarStateEl || healthEl) {
      fetch("/api/status", { credentials: "same-origin" })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (data) {
          if (!data) return;
          if (stateEl) stateEl.textContent = data.assistant_state;
          if (sidebarStateEl) sidebarStateEl.textContent = data.assistant_state;
          if (healthEl && data.health) {
            healthEl.textContent = data.health.overall;
            healthEl.className = "status-pill " + data.health.overall;
          }
          if (componentsEl && data.health && data.health.components) {
            componentsEl.innerHTML = kvList(data.health.components);
          }
          if (servicesEl && data.services) {
            servicesEl.innerHTML = kvList(data.services);
          }
        })
        .catch(function () {});
    }
  }

  setInterval(refreshHeartbeat, 5000);
  refreshHeartbeat();
})();
