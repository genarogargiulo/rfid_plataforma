// app.js — Panel en vivo: muestra lecturas y estado de todos los readers
// configurados, conectado por WebSocket a Flask-SocketIO.

const socket = io();

const kpiTagsUnicos = document.getElementById("kpi-tags-unicos");
const kpiLecturasTotales = document.getElementById("kpi-lecturas-totales");
const kpiPendientesBd = document.getElementById("kpi-pendientes-bd");
const kpiCardBdError = document.getElementById("kpi-card-bd-error");
const kpiBdError = document.getElementById("kpi-bd-error");
const readersGrid = document.getElementById("readers-grid");
const readersEmpty = document.getElementById("readers-empty");
const tablaBody = document.getElementById("tabla-eventos-body");

const MAX_FILAS_TABLA = 150;
const tarjetasReaders = new Map(); // reader_id -> elemento DOM

function formatearHora(isoTimestamp) {
  const d = new Date(isoTimestamp);
  return d.toLocaleTimeString("es-AR", { hour12: false });
}

function asegurarTarjetaReader(readerId, nombre, ip) {
  if (tarjetasReaders.has(readerId)) return tarjetasReaders.get(readerId);

  if (readersEmpty) readersEmpty.style.display = "none";

  const card = document.createElement("article");
  card.className = "reader-card";
  card.dataset.readerId = readerId;
  card.innerHTML = `
    <div class="reader-card-header">
      <div>
        <h3 class="reader-nombre">${nombre}</h3>
        <span class="reader-ip">${ip}</span>
      </div>
      <span class="estado-dot" id="dot-reader-${readerId}"></span>
    </div>
    <div class="reader-stat">
      <span>Lecturas</span>
      <b id="reader-${readerId}-lecturas">0</b>
    </div>
    <div class="reader-stat" id="reader-${readerId}-detalle-row" style="display:none;">
      <span id="reader-${readerId}-detalle"></span>
    </div>
  `;
  readersGrid.appendChild(card);
  tarjetasReaders.set(readerId, card);
  return card;
}

function actualizarEstadoReader(readerId, nombre, ip, estado, detalle) {
  asegurarTarjetaReader(readerId, nombre, ip);
  const dot = document.getElementById(`dot-reader-${readerId}`);
  dot.classList.remove("ok", "warn");
  if (estado === "conectado") dot.classList.add("ok");
  else if (estado === "conectando") dot.classList.add("warn");

  if (estado === "error" || estado === "desconectado") {
    const fila = document.getElementById(`reader-${readerId}-detalle-row`);
    const span = document.getElementById(`reader-${readerId}-detalle`);
    if (fila && span) {
      fila.style.display = "flex";
      span.textContent = detalle || estado;
    }
  }
}

function flashearReader(readerId) {
  const card = tarjetasReaders.get(readerId);
  if (!card) return;
  card.classList.add("flash");
  setTimeout(() => card.classList.remove("flash"), 700);
}

function actualizarKpis(kpis) {
  kpiTagsUnicos.textContent = kpis.total_tags_unicos;
  kpiLecturasTotales.textContent = kpis.total_lecturas;
  kpiPendientesBd.textContent = kpis.lecturas_pendientes_bd;

  if (kpis.ultimo_error_bd) {
    kpiCardBdError.style.display = "flex";
    kpiBdError.textContent = "Error al guardar (ver consola del servidor)";
  } else {
    kpiCardBdError.style.display = "none";
  }

  for (const [readerId, conteo] of Object.entries(kpis.lecturas_por_reader || {})) {
    const el = document.getElementById(`reader-${readerId}-lecturas`);
    if (el) el.textContent = conteo;
  }

  for (const [readerId, info] of Object.entries(kpis.estado_readers || {})) {
    actualizarEstadoReader(readerId, info.nombre, info.ip, info.estado, info.detalle);
  }
}

function agregarFilaEvento(evento, esNueva) {
  const filaVacia = tablaBody.querySelector(".fila-vacia");
  if (filaVacia) filaVacia.remove();

  const tr = document.createElement("tr");
  if (esNueva) tr.classList.add("fila-nueva");

  const rssiTexto = (evento.rssi !== null && evento.rssi !== undefined)
    ? `${evento.rssi} dBm` : "—";
  const epcAscii = evento.epc_ascii || "—";

  tr.innerHTML = `
    <td>${formatearHora(evento.timestamp)}</td>
    <td class="epc-cell">${evento.epc_hex}</td>
    <td>${epcAscii}</td>
    <td>${evento.reader_nombre}</td>
    <td>${evento.antena_nombre}</td>
    <td>${rssiTexto}</td>
  `;

  tablaBody.prepend(tr);

  while (tablaBody.children.length > MAX_FILAS_TABLA) {
    tablaBody.removeChild(tablaBody.lastChild);
  }
}

// ── Eventos del servidor ────────────────────────────────────────────
socket.on("estado_inicial", (data) => {
  actualizarKpis(data.kpis);

  if (data.eventos_recientes && data.eventos_recientes.length > 0) {
    tablaBody.innerHTML = "";
    [...data.eventos_recientes].reverse().forEach(ev => agregarFilaEvento(ev, false));
  }
});

socket.on("estado_reader", (data) => {
  actualizarEstadoReader(data.reader_id, data.nombre, "", data.estado, data.detalle);
});

socket.on("kpis_actualizados", (kpis) => {
  actualizarKpis(kpis);
});

socket.on("evento_lectura", (evento) => {
  agregarFilaEvento(evento, true);
  flashearReader(evento.reader_id);
});
