// Summer — small client-side helpers.
//
// We intentionally keep this minimal: no framework, no build step. The app
// works without JS; this is just progressive enhancement.

(function () {
  "use strict";

  // Auto-dismiss flash messages after a few seconds.
  document.addEventListener("DOMContentLoaded", function () {
    var flashes = document.querySelectorAll(".flash");
    flashes.forEach(function (el) {
      setTimeout(function () {
        el.style.transition = "opacity 0.4s, max-height 0.4s";
        el.style.opacity = "0";
        el.style.maxHeight = "0";
        el.style.padding = "0";
        el.style.margin = "0";
        el.style.border = "0";
        setTimeout(function () { el.remove(); }, 500);
      }, 5000);
    });
  });

  // Sanitize form submits on PIN field: only allow digits.
  var pinInput = document.getElementById("pin");
  if (pinInput) {
    pinInput.addEventListener("input", function () {
      this.value = this.value.replace(/\D/g, "").slice(0, 12);
    });
  }
})();
