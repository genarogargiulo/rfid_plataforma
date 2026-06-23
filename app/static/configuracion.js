// configuracion.js — Gestión de readers/antenas + configuración del sistema.

// ── Referencias DOM ──────────────────────────────────────────────────
const dbBanner       = document.getElementById("db-status-banner");
const listaContainer = document.getElementById("readers-config-list");
const modalReader    = document.getElementById("modal-reader");
const formReader     = document.getElementById("form-reader");
const modalReaderTitulo = document.getElementById("modal-reader-titulo");
const modalAntena    = document.getElementById("modal-antena");
const formAntena     = document.getElementById("form-antena");
const formSistema    = document.getElementById("form-sistema");
const saveBanner     = document.getElementById("sistema-save-banner");

let readersCache = [];

// ── Tooltips ─────────────────────────────────────────────────────────
document.querySelectorAll(".tooltip-icon").forEach(el => {
  const tip = document.createElement("div");
  tip.className = "tooltip-bubble";
  tip.textContent = el.dataset.tip;
  el.appendChild(tip);
});

// ── Pestañas ─────────────────────────────────────────────────────────
document.querySelectorAll(".tab-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById("tab-" + btn.dataset.tab).classList.add("active");
  });
});

// ── Fetch helpers ────────────────────────────────────────────────────
async function apiGet(url) {
  const res = await fetch(url);
  if (!res.ok) return { ok: false, error: `HTTP ${res.status}` };
  return res.json();
}

async function apiSend(url, method, body) {
  const res = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detalle = `HTTP ${res.status}`;
    try { const d = await res.json(); detalle = d.error || detalle; } catch {}
    console.error(`apiSend ${method} ${url}:`, detalle);
    return { ok: false, error: detalle };
  }
  return res.json();
}

// ── Estado de BD ──────────────────────────────────────────────────────
async function verificarBd() {
  try {
    const data = await apiGet("/api/db/test");
    dbBanner.textContent = data.ok
      ? `✓ Conectado a SQL Server: ${data.mensaje}`
      : `✗ Sin conexión a SQL Server: ${data.mensaje}`;
    dbBanner.className = "db-status-banner " + (data.ok ? "ok" : "error");
  } catch {
    dbBanner.textContent = "Error verificando conexión a SQL Server.";
    dbBanner.className = "db-status-banner error";
  }
}

// ════════════════════════════════════════════════════════════════════
// PESTAÑA: Readers y antenas
// ════════════════════════════════════════════════════════════════════

function renderReaders() {
  if (readersCache.length === 0) {
    listaContainer.innerHTML = `
      <div class="readers-empty">
        No hay readers configurados. Usá <strong>+ Nuevo reader</strong> para agregar el primero.
      </div>`;
    return;
  }

  listaContainer.innerHTML = readersCache.map(r => `
    <div class="reader-config-card" data-reader-id="${r.reader_id}">
      <div class="reader-config-card-header">
        <div class="reader-config-info">
          <h3>${r.nombre}</h3>
          <div class="reader-config-meta">
            <span>IP: <b>${r.ip_address}:${r.puerto}</b></span>
            <span>Modelo: ${r.modelo || "—"}</span>
            <span>Ubicación: ${r.ubicacion || "—"}</span>
            <span>Sesión Gen2: ${r.session_gen2}</span>
            <span>Potencia TX: ${r.tx_power_dbm != null ? r.tx_power_dbm + " dBm" : "Auto"}</span>
          </div>
        </div>
        <div class="reader-config-actions">
          <button class="btn-small btn-add-antena" data-reader-id="${r.reader_id}">+ Antena</button>
          <button class="btn-small btn-edit-reader" data-reader-id="${r.reader_id}">Editar</button>
          <button class="btn-danger btn-del-reader"
                  data-reader-id="${r.reader_id}"
                  data-reader-nombre="${r.nombre.replace(/"/g, '&quot;')}">Eliminar</button>
        </div>
      </div>
      <div class="antenas-list">
        ${r.antenas.length === 0
          ? '<div class="antenas-empty">Sin antenas configuradas.</div>'
          : r.antenas.map(a => `
              <div class="antena-row">
                <div class="antena-row-info">
                  <span>Puerto <b>${a.puerto_fisico}</b></span>
                  <span><b>${a.nombre}</b></span>
                  <span>${a.ubicacion || ""}</span>
                </div>
                <button class="btn-danger btn-del-antena"
                        data-antena-id="${a.antena_id}"
                        data-reader-id="${r.reader_id}">Quitar</button>
              </div>`).join("")
        }
      </div>
    </div>`).join("");

  // Eventos usando delegación — NUNCA onclick inline para evitar bugs de scope
  listaContainer.querySelectorAll(".btn-add-antena").forEach(btn => {
    btn.addEventListener("click", () => abrirModalAntena(parseInt(btn.dataset.readerId)));
  });
  listaContainer.querySelectorAll(".btn-edit-reader").forEach(btn => {
    btn.addEventListener("click", () => editarReader(parseInt(btn.dataset.readerId)));
  });
  listaContainer.querySelectorAll(".btn-del-reader").forEach(btn => {
    btn.addEventListener("click", () =>
      confirmarEliminarReader(parseInt(btn.dataset.readerId), btn.dataset.readerNombre));
  });
  listaContainer.querySelectorAll(".btn-del-antena").forEach(btn => {
    btn.addEventListener("click", () =>
      eliminarAntena(parseInt(btn.dataset.antenaId), parseInt(btn.dataset.readerId)));
  });
}

async function cargarReaders() {
  const data = await apiGet("/api/readers");
  readersCache = Array.isArray(data) ? data : [];
  renderReaders();
}

// ── Modal reader ──────────────────────────────────────────────────────
document.getElementById("btn-nuevo-reader").addEventListener("click", () => {
  formReader.reset();
  document.getElementById("reader-id-edit").value = "";
  document.getElementById("reader-puerto").value = "5084";
  document.getElementById("reader-session").value = "2";
  document.getElementById("reader-tag-population").value = "4";
  modalReaderTitulo.textContent = "Nuevo reader";
  modalReader.hidden = false;
});

document.getElementById("btn-cancelar-reader").addEventListener("click", () => {
  modalReader.hidden = true;
});

function editarReader(readerId) {
  const r = readersCache.find(x => x.reader_id === readerId);
  if (!r) return;
  document.getElementById("reader-id-edit").value = r.reader_id;
  document.getElementById("reader-nombre").value = r.nombre;
  document.getElementById("reader-ip").value = r.ip_address;
  document.getElementById("reader-puerto").value = r.puerto;
  document.getElementById("reader-modelo").value = r.modelo || "";
  document.getElementById("reader-ubicacion").value = r.ubicacion || "";
  document.getElementById("reader-session").value = r.session_gen2;
  document.getElementById("reader-tag-population").value = r.tag_population;
  document.getElementById("reader-tx-power").value = r.tx_power_dbm ?? "";
  modalReaderTitulo.textContent = "Editar reader";
  modalReader.hidden = false;
}

formReader.addEventListener("submit", async (e) => {
  e.preventDefault();
  const readerIdEdit = document.getElementById("reader-id-edit").value;
  const txRaw = document.getElementById("reader-tx-power").value;
  const payload = {
    nombre:         document.getElementById("reader-nombre").value.trim(),
    ip_address:     document.getElementById("reader-ip").value.trim(),
    puerto:         parseInt(document.getElementById("reader-puerto").value, 10),
    modelo:         document.getElementById("reader-modelo").value.trim() || null,
    ubicacion:      document.getElementById("reader-ubicacion").value.trim() || null,
    session_gen2:   parseInt(document.getElementById("reader-session").value, 10),
    tag_population: parseInt(document.getElementById("reader-tag-population").value, 10),
    tx_power_dbm:   txRaw === "" ? null : parseInt(txRaw, 10),
  };
  const url    = readerIdEdit ? `/api/readers/${readerIdEdit}` : "/api/readers";
  const method = readerIdEdit ? "PUT" : "POST";
  const res = await apiSend(url, method, payload);
  if (res.ok) { modalReader.hidden = true; await cargarReaders(); }
  else alert("Error al guardar el reader: " + (res.error || "desconocido"));
});

async function confirmarEliminarReader(readerId, nombre) {
  if (!confirm(`¿Eliminar el reader "${nombre}"?\nEl historial de lecturas se conserva en la base de datos.`)) return;
  const res = await apiSend(`/api/readers/${readerId}`, "DELETE", {});
  if (res.ok) await cargarReaders();
  else alert("Error al eliminar: " + (res.error || "desconocido"));
}

// ── Modal antena ──────────────────────────────────────────────────────
function abrirModalAntena(readerId) {
  if (!readerId) return;
  const existe = readersCache.some(r => r.reader_id === readerId);
  if (!existe) { alert("Reader no encontrado. Recargá la página."); cargarReaders(); return; }
  formAntena.reset();
  document.getElementById("antena-reader-id").value = readerId;
  modalAntena.hidden = false;
}

document.getElementById("btn-cancelar-antena").addEventListener("click", () => {
  modalAntena.hidden = true;
});

formAntena.addEventListener("submit", async (e) => {
  e.preventDefault();
  const readerId = document.getElementById("antena-reader-id").value;
  if (!readerId) { alert("Error interno: reader no identificado."); return; }
  const payload = {
    puerto_fisico: parseInt(document.getElementById("antena-puerto").value, 10),
    nombre:        document.getElementById("antena-nombre").value.trim(),
    ubicacion:     document.getElementById("antena-ubicacion").value.trim() || null,
  };
  const res = await apiSend(`/api/readers/${readerId}/antenas`, "POST", payload);
  if (res.ok) { modalAntena.hidden = true; await cargarReaders(); }
  else alert("Error al agregar la antena: " + (res.error || "desconocido"));
});

async function eliminarAntena(antenaId) {
  if (!confirm("¿Quitar esta antena? El historial se conserva.")) return;
  const res = await apiSend(`/api/antenas/${antenaId}`, "DELETE", {});
  if (res.ok) await cargarReaders();
  else alert("Error al quitar la antena: " + (res.error || "desconocido"));
}

// Escape y clic fuera para cerrar modales
document.addEventListener("keydown", e => { if (e.key === "Escape") { modalReader.hidden = true; modalAntena.hidden = true; } });
[modalReader, modalAntena].forEach(m => m.addEventListener("click", e => { if (e.target === m) { modalReader.hidden = true; modalAntena.hidden = true; } }));

// ════════════════════════════════════════════════════════════════════
// PESTAÑA: Sistema
// ════════════════════════════════════════════════════════════════════

const authSelect     = document.getElementById("cfg-auth-type");
const sqlAuthFields  = document.getElementById("cfg-sqlauth-fields");

authSelect.addEventListener("change", () => {
  sqlAuthFields.style.display = authSelect.value === "false" ? "block" : "none";
});

async function cargarConfigSistema() {
  const data = await apiGet("/api/config/sistema");
  if (!data.DB_DRIVER) return;

  document.getElementById("cfg-db-driver").value   = data.DB_DRIVER;
  document.getElementById("cfg-db-server").value   = data.DB_SERVER;
  document.getElementById("cfg-db-database").value = data.DB_DATABASE;
  authSelect.value = data.DB_TRUSTED_CONNECTION ? "true" : "false";
  sqlAuthFields.style.display = data.DB_TRUSTED_CONNECTION ? "none" : "block";
  document.getElementById("cfg-db-username").value   = data.DB_USERNAME || "";
  document.getElementById("cfg-db-password").value   = data.DB_PASSWORD || "";
  document.getElementById("cfg-db-encrypt").checked  = !!data.DB_ENCRYPT;
  document.getElementById("cfg-db-trust-cert").checked = !!data.DB_TRUST_SERVER_CERTIFICATE;
  document.getElementById("cfg-flush-seg").value     = data.INTERVALO_FLUSH_SEGUNDOS;
  document.getElementById("cfg-buffer-max").value    = data.TAMANO_MAXIMO_BUFFER;
  document.getElementById("cfg-recarga-seg").value   = data.INTERVALO_RECARGA_CONFIG_SEGUNDOS;
  document.getElementById("cfg-session").value       = data.SESSION_DEFAULT;
  document.getElementById("cfg-tag-pop").value       = data.TAG_POPULATION_DEFAULT;
  document.getElementById("cfg-report-n").value      = data.REPORT_EVERY_N_TAGS;
  document.getElementById("cfg-web-host").value      = data.WEB_HOST;
  document.getElementById("cfg-web-port").value      = data.WEB_PORT;
}

document.getElementById("btn-recargar-config").addEventListener("click", cargarConfigSistema);

formSistema.addEventListener("submit", async (e) => {
  e.preventDefault();
  const payload = {
    DB_DRIVER:                     document.getElementById("cfg-db-driver").value.trim(),
    DB_SERVER:                     document.getElementById("cfg-db-server").value.trim(),
    DB_DATABASE:                   document.getElementById("cfg-db-database").value.trim(),
    DB_TRUSTED_CONNECTION:         authSelect.value === "true",
    DB_USERNAME:                   document.getElementById("cfg-db-username").value.trim(),
    DB_PASSWORD:                   document.getElementById("cfg-db-password").value,
    DB_ENCRYPT:                    document.getElementById("cfg-db-encrypt").checked,
    DB_TRUST_SERVER_CERTIFICATE:   document.getElementById("cfg-db-trust-cert").checked,
    INTERVALO_FLUSH_SEGUNDOS:      parseFloat(document.getElementById("cfg-flush-seg").value),
    TAMANO_MAXIMO_BUFFER:          parseInt(document.getElementById("cfg-buffer-max").value, 10),
    INTERVALO_RECARGA_CONFIG_SEGUNDOS: parseInt(document.getElementById("cfg-recarga-seg").value, 10),
    SESSION_DEFAULT:               parseInt(document.getElementById("cfg-session").value, 10),
    TAG_POPULATION_DEFAULT:        parseInt(document.getElementById("cfg-tag-pop").value, 10),
    REPORT_EVERY_N_TAGS:           parseInt(document.getElementById("cfg-report-n").value, 10),
    WEB_HOST:                      document.getElementById("cfg-web-host").value.trim(),
    WEB_PORT:                      parseInt(document.getElementById("cfg-web-port").value, 10),
  };
  const res = await apiSend("/api/config/sistema", "POST", payload);
  if (res.ok) {
    saveBanner.classList.remove("hidden");
    setTimeout(() => saveBanner.classList.add("hidden"), 8000);
  } else {
    alert("Error al guardar la configuración: " + (res.error || "desconocido"));
  }
});

// ── Inicialización ────────────────────────────────────────────────────
modalReader.hidden = true;
modalAntena.hidden = true;
verificarBd();
cargarReaders();
cargarConfigSistema();
