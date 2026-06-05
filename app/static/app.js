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

  // Dark mode toggle. The inline script in base.html applies the persisted
  // theme synchronously before paint; here we handle the click and persist.
  var themeBtn = document.querySelector(".theme-toggle");
  if (themeBtn) {
    themeBtn.addEventListener("click", function () {
      var isDark = document.documentElement.getAttribute("data-theme") === "dark";
      if (isDark) {
        document.documentElement.removeAttribute("data-theme");
        try { localStorage.setItem("summer-theme", "light"); } catch (e) {}
      } else {
        document.documentElement.setAttribute("data-theme", "dark");
        try { localStorage.setItem("summer-theme", "dark"); } catch (e) {}
      }
    });
  }

  // Emoji picker for forms that declare [data-emoji-form]. Each form has a
  // hidden input (the form declares which via [data-emoji-target="<name>"],
  // defaulting to "avatar_emoji" for the kid form) and a grid of buttons;
  // clicking a button sets the hidden input and marks the button selected.
  document.querySelectorAll("[data-emoji-form]").forEach(function (form) {
    var targetName = form.getAttribute("data-emoji-target") || "avatar_emoji";
    var hidden = form.querySelector('input[name="' + targetName + '"]');
    if (!hidden) return;
    var buttons = form.querySelectorAll(".emoji-option");

    function setSelected(emoji) {
      buttons.forEach(function (btn) {
        var match = btn.getAttribute("data-emoji") === emoji;
        btn.classList.toggle("selected", match);
        btn.setAttribute("aria-checked", match ? "true" : "false");
      });
    }

    // If the hidden input already has a value (e.g. editing an existing
    // record), highlight the matching button so the picker shows the
    // current selection.
    if (hidden.value) setSelected(hidden.value);

    buttons.forEach(function (btn) {
      btn.addEventListener("click", function () {
        var emoji = btn.getAttribute("data-emoji");
        hidden.value = emoji;
        setSelected(emoji);
      });
    });
  });

  // Confirm-before-delete. The inline onsubmit="return confirm(...)" pattern
  // is unreliable on some mobile browsers (notably Brave on iOS/Android) when
  // the form is nested inside a <details> element. Using a real submit event
  // listener with preventDefault() is much more robust across browsers.
  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (e) {
      if (!window.confirm(form.getAttribute("data-confirm"))) {
        e.preventDefault();
      }
    });
  });
})();
