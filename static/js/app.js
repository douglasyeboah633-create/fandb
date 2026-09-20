document.addEventListener("DOMContentLoaded", function () {
  var toggle = document.getElementById("menu-toggle");
  var sidebar = document.getElementById("sidebar");
  if (toggle && sidebar) {
    toggle.addEventListener("click", function () {
      var open = sidebar.classList.toggle("open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
    document.addEventListener("click", function (event) {
      if (sidebar.classList.contains("open") && !sidebar.contains(event.target) && event.target !== toggle && !toggle.contains(event.target)) {
        sidebar.classList.remove("open");
        toggle.setAttribute("aria-expanded", "false");
      }
    });
  }
  document.querySelectorAll("[data-print]").forEach(function (button) {
    button.addEventListener("click", function () { window.print(); });
  });
  var current = window.location.pathname;
  document.querySelectorAll(".sidebar nav a").forEach(function (link) {
    var href = link.getAttribute("href");
    if (href && current.startsWith(href.replace(/\/$/, "") + "/")) {
      link.classList.add("active");
    }
  });
  document.querySelectorAll("form.confirm-form").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      if (!window.confirm(form.dataset.confirm || "Are you sure? This action cannot be undone.")) {
        event.preventDefault();
      }
    });
  });

  // Payment register: extra blank rows and a live page total.
  var registerRows = document.getElementById("register-rows");
  var registerTemplate = document.getElementById("register-empty-row");
  if (registerRows && registerTemplate) {
    var totalFormsInput = document.querySelector('input[name="row-TOTAL_FORMS"]');
    var liveTotal = document.getElementById("register-live-total");
    var registerCurrency = registerRows.dataset.currency || "";
    var addAmounts = function () {
      var total = 0;
      registerRows.querySelectorAll('input[name$="-amount"]').forEach(function (input) {
        var row = input.closest("tr");
        var tick = row ? row.querySelector('input[name$="-DELETE"]') : null;
        if (tick && tick.checked) return;
        var value = parseFloat(input.value);
        if (!isNaN(value) && value > 0) total += value;
      });
      return total;
    };
    var updateTotal = function () {
      if (!liveTotal) return;
      var total = addAmounts();
      liveTotal.textContent = (registerCurrency ? registerCurrency + " " : "") + total.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    };
    var addRegisterRow = function () {
      var index = totalFormsInput ? parseInt(totalFormsInput.value, 10) || 0 : 0;
      var markup = "<table>" + registerTemplate.innerHTML.replace(/__prefix__/g, index) + "</table>";
      var parsed = new DOMParser().parseFromString(markup, "text/html");
      var row = parsed.querySelector("tr");
      if (!row) return;
      var imported = document.importNode(row, true);
      registerRows.appendChild(imported);
      if (totalFormsInput) totalFormsInput.value = index + 1;
      var firstField = imported.querySelector("select, input");
      if (firstField) firstField.focus();
      updateTotal();
    };
    var addRowButton = document.getElementById("register-add-row");
    if (addRowButton) addRowButton.addEventListener("click", addRegisterRow);
    registerRows.addEventListener("input", function (event) {
      if (event.target.name && /-amount$/.test(event.target.name)) updateTotal();
    });
    registerRows.addEventListener("change", function (event) {
      if (event.target.name && /-DELETE$/.test(event.target.name)) updateTotal();
    });
    updateTotal();
  }

  // Records table: add space (more rows), live balances and page totals.
  var recordRows = document.getElementById("record-rows");
  var recordTemplate = document.getElementById("record-empty-row");
  if (recordRows && recordTemplate) {
    var recordCount = document.querySelector('input[name="rec-TOTAL_FORMS"]');
    var recordCurrency = recordRows.dataset.currency || "";
    var formatMoney = function (value) {
      return value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    };
    var numberIn = function (row, suffix) {
      var field = row.querySelector('input[name$="' + suffix + '"]');
      var value = field ? parseFloat(field.value) : NaN;
      return isNaN(value) ? 0 : value;
    };
    var rowIsDeleted = function (row) {
      var tick = row.querySelector('input[name$="-DELETE"]');
      return tick ? tick.checked : false;
    };
    var refreshRecordTable = function () {
      var prices = 0;
      var paid = 0;
      recordRows.querySelectorAll("tr").forEach(function (row) {
        var price = numberIn(row, "-total_price");
        var received = numberIn(row, "-amount_paid");
        var balanceLabel = row.querySelector("[data-balance] .row-balance");
        if (balanceLabel) {
          balanceLabel.textContent = price > 0 ? formatMoney(Math.max(price - received, 0)) : "—";
        }
        if (rowIsDeleted(row)) return;
        prices += price;
        paid += received;
      });
      var priceOut = document.getElementById("rec-total-price");
      var paidOut = document.getElementById("rec-total-paid");
      var balanceOut = document.getElementById("rec-total-balance");
      if (priceOut) priceOut.textContent = recordCurrency + " " + formatMoney(prices);
      if (paidOut) paidOut.textContent = recordCurrency + " " + formatMoney(paid);
      if (balanceOut) balanceOut.textContent = recordCurrency + " " + formatMoney(Math.max(prices - paid, 0));
    };
    var addRecordRows = function (count) {
      for (var step = 0; step < count; step += 1) {
        var index = recordCount ? parseInt(recordCount.value, 10) || 0 : 0;
        var markup = "<table>" + recordTemplate.innerHTML.replace(/__prefix__/g, index) + "</table>";
        var parsed = new DOMParser().parseFromString(markup, "text/html");
        var row = parsed.querySelector("tr");
        if (!row) return;
        var imported = document.importNode(row, true);
        recordRows.appendChild(imported);
        if (recordCount) recordCount.value = index + 1;
        if (step === 0) {
          var firstField = imported.querySelector("input, select");
          if (firstField) firstField.focus();
        }
      }
      refreshRecordTable();
    };
    var addRowButton = document.getElementById("records-add-row");
    if (addRowButton) addRowButton.addEventListener("click", function () { addRecordRows(1); });
    var addRowsButton = document.getElementById("records-add-rows");
    if (addRowsButton) {
      addRowsButton.addEventListener("click", function () {
        addRecordRows(parseInt(addRowsButton.dataset.rows, 10) || 5);
      });
    }
    recordRows.addEventListener("input", function (event) {
      if (event.target.name && /-(total_price|amount_paid)$/.test(event.target.name)) {
        refreshRecordTable();
      }
    });
    recordRows.addEventListener("change", function (event) {
      if (event.target.name && /-DELETE$/.test(event.target.name)) refreshRecordTable();
    });
    refreshRecordTable();
  }

  // Filters that load immediately (e.g. "rows per page").
  document.querySelectorAll("select[data-autosubmit]").forEach(function (select) {
    select.addEventListener("change", function () {
      if (select.form) select.form.submit();
    });
  });

  // One click of Save: lock the button so a double click cannot save twice.
  document.querySelectorAll("form.save-guard").forEach(function (form) {
    form.addEventListener("submit", function () {
      var button = form.querySelector(".save-button");
      if (!button) return;
      window.setTimeout(function () {
        button.disabled = true;
        button.textContent = "Saving…";
      }, 0);
    });
  });

  // Records: make it obvious there is something waiting to be saved, and warn
  // if the page is left (refresh, back, close) with unsaved entries.
  var guardForm = document.querySelector("form.save-guard");
  if (guardForm && recordRows) {
    var guardButton = guardForm.querySelector(".save-button");
    var cleanLabel = guardButton ? guardButton.textContent.trim() : "";
    var hasUnsaved = false;
    var setUnsaved = function (value) {
      if (hasUnsaved === value) return;
      hasUnsaved = value;
      if (!guardButton) return;
      guardButton.textContent = value ? "\u2714 Save now" : cleanLabel;
      guardButton.classList.toggle("save-button-active", value);
    };
    recordRows.addEventListener("input", function () { setUnsaved(true); });
    recordRows.addEventListener("change", function () { setUnsaved(true); });
    guardForm.addEventListener("submit", function () { setUnsaved(false); });
    window.addEventListener("beforeunload", function (event) {
      if (!hasUnsaved) return;
      event.preventDefault();
      event.returnValue = "";
    });
  }
});
