document.addEventListener("DOMContentLoaded", function () {
  if (typeof Chart === "undefined") return;
  var monthly = JSON.parse(document.getElementById("monthly-data").textContent);
  new Chart(document.getElementById("monthly-chart"), {
    type: "bar",
    data: { labels: monthly.labels, datasets: [
      { label: "Sales", data: monthly.sales, backgroundColor: "#176b4a" },
      { label: "Payments", data: monthly.payments, backgroundColor: "#d5aa50" }
    ] },
    options: { responsive: true, maintainAspectRatio: false, scales: { y: { beginAtZero: true } } }
  });
  new Chart(document.getElementById("land-chart"), {
    type: "doughnut",
    data: {
      labels: JSON.parse(document.getElementById("land-labels").textContent),
      datasets: [{ data: JSON.parse(document.getElementById("land-values").textContent),
        backgroundColor: ["#176b4a", "#d5aa50", "#7c8e86"] }]
    },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: "bottom" } } }
  });
});
