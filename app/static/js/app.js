// Small progressive enhancements. Every page works without this file:
// the server validates everything and never relies on the browser to do so.
(function () {
  "use strict";

  // 1. When a form has errors, move keyboard/screen-reader focus to the error summary.
  var summary = document.getElementById("error-summary");
  if (summary) {
    summary.focus();
  }

  // 2. Pre-fill a new transaction's date with today's date in the visitor's own time zone.
  var dateInput = document.querySelector("input[data-default-today]");
  if (dateInput && !dateInput.value) {
    var now = new Date();
    var pad = function (n) {
      return String(n).padStart(2, "0");
    };
    dateInput.value = now.getFullYear() + "-" + pad(now.getMonth() + 1) + "-" + pad(now.getDate());
  }

  // 3. On the add/edit form, only offer the categories that match the chosen type.
  var form = document.querySelector("form[data-txn-form]");
  if (form) {
    var select = form.querySelector("#category");
    var groups = Array.prototype.slice.call(select.querySelectorAll("optgroup"));
    var radios = form.querySelectorAll('input[name="type"]');

    var updateCategories = function () {
      var checked = form.querySelector('input[name="type"]:checked');
      var type = checked ? checked.value : "";
      var current = select.value;

      groups.forEach(function (group) {
        if (group.parentNode === select) {
          select.removeChild(group);
        }
      });
      groups.forEach(function (group) {
        if (!type || group.getAttribute("data-type") === type) {
          select.appendChild(group);
        }
      });

      select.value = current;
      if (select.value !== current) {
        select.value = ""; // the old choice no longer applies; show the placeholder
      }
    };

    radios.forEach(function (radio) {
      radio.addEventListener("change", updateCategories);
    });
    updateCategories();
  }
})();
