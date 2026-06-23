// informes.js — Dashboard estadístico con Chart.js

// ── Paleta coherente con el resto de la app ──────────────────────────
const C_ACCENT   = "#2E8FCC";
const C_GREEN    = "#3DCB7A";
const C_AMBER    = "#E0A638";
const C_RED      = "#E0524A";
const C_PURPLE   = "#9B72CF";
const C_TEAL     = "#2BC0B4";
const MULTI_COLS = [C_ACCENT, C_GREEN, C_AMBER, C_RED, C_PURPLE, C_TEAL,
                    "#E07B54", "#54A0E0", "#A0C455", "#CF7272"];

// Configuración global de Chart.js para el tema oscuro
Chart.defaults.color = "#8A97A6";
Chart.defaults.borderColor = "#283341";
Chart.defaults.font.family = "-apple-system, 'Segoe UI', Roboto, sans-serif";
Chart.defaults.font.size = 12;

// ── Estado ────────────────────────────────────────────────────────────
let diasActivos = 30;
let graficos = {};

// ── Helpers ───────────────────────────────────────────────────────────
async function apiGet(url) {
  const res = await fetch(url);
  if (!res.ok) return { ok: false, datos: null };
  return res.json();
}

function fmt(n) {
  if (n == null) return "—";
  return n >= 1_000_000 ? (n / 1_000_000).toFixed(1) + "M"
       : n >= 1_000     ? (n / 1_000).toFixed(1) + "k"
       : String(n);
}

function fmtFecha(iso) {
  if (!iso) return "—";
  const [y, m, d] = iso.split("-");
  return `${d}/${m}/${y}`;
}

function destruirSiExiste(id) {
  if (graficos[id]) { graficos[id].destroy(); delete graficos[id]; }
}

// ── KPIs gerenciales ──────────────────────────────────────────────────
async function cargarKpis() {
  const data = await apiGet("/api/informes/kpis_generales");
  if (!data.ok || !data.datos) return;
  const d = data.datos;
  document.getElementById("kpi-hoy").textContent          = fmt(d.lecturas_hoy);
  document.getElementById("kpi-tags-total").textContent   = fmt(d.total_tags_unicos);
  document.getElementById("kpi-lecturas-total").textContent = fmt(d.total_lecturas);
  document.getElementById("kpi-antenas").textContent      = d.antenas_activas ?? "—";
  document.getElementById("kpi-primera").textContent      = fmtFecha(d.primera_lectura);
}

// ── Gráfico: lecturas por día ─────────────────────────────────────────
async function cargarDiario() {
  const data = await apiGet(`/api/informes/resumen_diario?dias=${diasActivos}`);
  document.getElementById("sub-diario").textContent = `últimos ${diasActivos} días`;
  destruirSiExiste("diario");
  if (!data.ok || !data.datos?.length) {
    dibujarVacio("chart-diario");
    return;
  }
  const labels  = data.datos.map(r => fmtFecha(r.fecha));
  const lecturas = data.datos.map(r => r.lecturas);
  const tags     = data.datos.map(r => r.tags_unicos);

  graficos["diario"] = new Chart(document.getElementById("chart-diario"), {
    type: "bar",
    data: {
      labels,
      datasets: [
        { label: "Lecturas", data: lecturas, backgroundColor: C_ACCENT + "BB",
          borderColor: C_ACCENT, borderWidth: 1, borderRadius: 3, yAxisID: "y" },
        { label: "Tags únicos", data: tags, type: "line", borderColor: C_GREEN,
          backgroundColor: "transparent", borderWidth: 2, pointRadius: 3,
          pointBackgroundColor: C_GREEN, tension: 0.3, yAxisID: "y1" },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: { legend: { position: "bottom" } },
      scales: {
        x: { grid: { color: "#283341" }, ticks: { maxTicksLimit: 12, maxRotation: 45 } },
        y:  { grid: { color: "#283341" }, position: "left",  title: { display: true, text: "Lecturas" } },
        y1: { grid: { drawOnChartArea: false }, position: "right", title: { display: true, text: "Tags únicos" } },
      },
    },
  });
}

// ── Gráfico: distribución por hora ────────────────────────────────────
async function cargarHora() {
  const diasHora = Math.min(diasActivos, 30);
  const data = await apiGet(`/api/informes/por_hora?dias=${diasHora}`);
  document.getElementById("sub-hora").textContent = `últimos ${diasHora} días`;
  destruirSiExiste("hora");
  if (!data.ok || !data.datos?.length) { dibujarVacio("chart-hora"); return; }

  // Rellenar horas sin lecturas con 0
  const mapa = {};
  data.datos.forEach(r => { mapa[r.hora] = r.lecturas; });
  const labels   = Array.from({ length: 24 }, (_, i) => `${String(i).padStart(2, "0")}:00`);
  const lecturas = Array.from({ length: 24 }, (_, i) => mapa[i] || 0);

  graficos["hora"] = new Chart(document.getElementById("chart-hora"), {
    type: "bar",
    data: {
      labels,
      datasets: [{ label: "Lecturas", data: lecturas,
        backgroundColor: lecturas.map(v => v === Math.max(...lecturas) ? C_AMBER + "DD" : C_ACCENT + "88"),
        borderColor: C_ACCENT, borderWidth: 1, borderRadius: 3 }],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { color: "#283341" }, ticks: { maxRotation: 45 } },
        y: { grid: { color: "#283341" }, title: { display: true, text: "Lecturas" } },
      },
    },
  });
}

// ── Gráfico + tabla: por antena ────────────────────────────────────────
async function cargarPorAntena() {
  const data = await apiGet(`/api/informes/por_antena?dias=${diasActivos}`);
  document.getElementById("sub-antena").textContent = `últimos ${diasActivos} días`;
  document.getElementById("sub-tabla").textContent  = `últimos ${diasActivos} días`;
  destruirSiExiste("antena");

  const tbody = document.getElementById("tbody-antenas");

  if (!data.ok || !data.datos?.length) {
    dibujarVacio("chart-antena");
    tbody.innerHTML = '<tr class="fila-vacia"><td colspan="5">Sin datos para el período seleccionado</td></tr>';
    return;
  }

  const total = data.datos.reduce((s, r) => s + r.lecturas, 0);
  const labels = data.datos.map(r => r.antena);
  const vals   = data.datos.map(r => r.lecturas);

  graficos["antena"] = new Chart(document.getElementById("chart-antena"), {
    type: "doughnut",
    data: {
      labels,
      datasets: [{ data: vals, backgroundColor: MULTI_COLS.slice(0, vals.length),
        borderColor: "#161D26", borderWidth: 2 }],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { position: "bottom", labels: { boxWidth: 12, padding: 10 } },
        tooltip: { callbacks: {
          label: ctx => ` ${ctx.label}: ${fmt(ctx.parsed)} (${((ctx.parsed / total) * 100).toFixed(1)}%)`
        }},
      },
    },
  });

  // Tabla
  tbody.innerHTML = data.datos.map((r, i) => `
    <tr>
      <td><span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${MULTI_COLS[i % MULTI_COLS.length]};margin-right:8px"></span>${r.antena}</td>
      <td>${r.reader}</td>
      <td style="font-family:var(--mono)">${r.lecturas.toLocaleString("es-AR")}</td>
      <td style="font-family:var(--mono)">${r.tags_unicos.toLocaleString("es-AR")}</td>
      <td style="font-family:var(--mono)">${((r.lecturas / total) * 100).toFixed(1)}%</td>
    </tr>`).join("");
}

// ── Gráfico: mensual ──────────────────────────────────────────────────
async function cargarMensual() {
  const data = await apiGet("/api/informes/resumen_mensual");
  destruirSiExiste("mensual");
  if (!data.ok || !data.datos?.length) { dibujarVacio("chart-mensual"); return; }

  const labels   = data.datos.map(r => r.mes);
  const lecturas = data.datos.map(r => r.lecturas);
  const tags     = data.datos.map(r => r.tags_unicos);

  graficos["mensual"] = new Chart(document.getElementById("chart-mensual"), {
    type: "line",
    data: {
      labels,
      datasets: [
        { label: "Lecturas", data: lecturas, borderColor: C_ACCENT,
          backgroundColor: C_ACCENT + "22", fill: true, borderWidth: 2,
          pointRadius: 4, pointBackgroundColor: C_ACCENT, tension: 0.3, yAxisID: "y" },
        { label: "Tags únicos", data: tags, borderColor: C_GREEN,
          backgroundColor: "transparent", borderWidth: 2,
          pointRadius: 4, pointBackgroundColor: C_GREEN, tension: 0.3, yAxisID: "y1" },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: { legend: { position: "bottom" } },
      scales: {
        x: { grid: { color: "#283341" } },
        y:  { grid: { color: "#283341" }, position: "left",  title: { display: true, text: "Lecturas" } },
        y1: { grid: { drawOnChartArea: false }, position: "right", title: { display: true, text: "Tags únicos" } },
      },
    },
  });
}

function dibujarVacio(canvasId) {
  const canvas = document.getElementById(canvasId);
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#8A97A6";
  ctx.font = "14px -apple-system, sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText("Sin datos para este período", canvas.width / 2, canvas.height / 2);
}

// ── Selector de período ────────────────────────────────────────────────
document.querySelectorAll(".periodo-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".periodo-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    diasActivos = parseInt(btn.dataset.dias);
    cargarTodo();
  });
});

document.getElementById("btn-actualizar").addEventListener("click", cargarTodo);

function cargarTodo() {
  cargarKpis();
  cargarDiario();
  cargarHora();
  cargarPorAntena();
  cargarMensual();
}

// ── Init ──────────────────────────────────────────────────────────────
cargarTodo();
