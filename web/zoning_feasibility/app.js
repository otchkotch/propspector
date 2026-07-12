const state = {
  view: null,
  parcelGraphic: null,
  result: null,
  reportToken: "",
  layers: {},
};

const elements = {
  form: document.querySelector("#analysisForm"),
  parcelInput: document.querySelector("#parcelInput"),
  intendedUseInput: document.querySelector("#intendedUseInput"),
  runButton: document.querySelector("#runButton"),
  statusPill: document.querySelector("#statusPill"),
  mapStatus: document.querySelector("#mapStatus"),
  fitParcelButton: document.querySelector("#fitParcelButton"),
  snapshotHeadline: document.querySelector("#snapshotHeadline"),
  parcelFacts: document.querySelector("#parcelFacts"),
  recommendations: document.querySelector("#recommendations"),
  optionCount: document.querySelector("#optionCount"),
  resources: document.querySelector("#resources"),
  resourceCount: document.querySelector("#resourceCount"),
  notes: document.querySelector("#notes"),
  downloadReport: document.querySelector("#downloadReport"),
};

require([
  "esri/Map",
  "esri/views/MapView",
  "esri/Graphic",
  "esri/layers/MapImageLayer",
  "esri/layers/GraphicsLayer",
  "esri/widgets/LayerList",
  "esri/widgets/BasemapToggle",
], (Map, MapView, Graphic, MapImageLayer, GraphicsLayer, LayerList, BasemapToggle) => {
  const parcelLayer = new GraphicsLayer({ title: "Subject parcel" });
  const environmentalLayer = new MapImageLayer({
    url: "https://gis.nccde.org/agsserver/rest/services/BaseMaps/Environmental/MapServer",
    title: "NCC Environmental",
    opacity: 0.62,
    visible: true,
  });
  const wrpaLayer = new MapImageLayer({
    url: "https://gis.nccde.org/agsserver/rest/services/BaseMaps/WRPA/MapServer",
    title: "NCC WRPA",
    opacity: 0.54,
    visible: false,
  });

  const map = new Map({
    basemap: "hybrid",
    layers: [environmentalLayer, wrpaLayer, parcelLayer],
  });

  const view = new MapView({
    container: "mapView",
    map,
    center: [-75.62, 39.68],
    zoom: 11,
    constraints: { snapToZoom: false },
    popup: { dockEnabled: true, dockOptions: { position: "bottom-right" } },
  });

  state.view = view;
  state.layers.parcel = parcelLayer;
  state.layers.environmental = environmentalLayer;
  state.layers.wrpa = wrpaLayer;

  view.ui.add(new BasemapToggle({ view, nextBasemap: "topo-vector" }), "bottom-right");
  view.ui.add(new LayerList({ view }), "top-right");

  view.when(() => {
    elements.mapStatus.textContent = "Map ready. Run a feasibility check to draw the parcel.";
  }).catch((error) => {
    elements.mapStatus.textContent = `Map failed to load: ${error.message}`;
  });

  state.Graphic = Graphic;
});

elements.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const parcel = elements.parcelInput.value.trim();
  const intendedUse = elements.intendedUseInput.value.trim();
  if (!parcel) {
    showError("Enter at least one parcel number.");
    return;
  }

  setBusy(true, "Running");
  clearResults();
  elements.mapStatus.textContent = "Querying NCC GIS, measuring resources, and screening yields...";

  try {
    const response = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ parcel, intendedUse }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "Analysis failed.");
    }
    state.result = payload.result;
    state.reportToken = payload.reportToken;
    renderResult(payload.result);
    drawParcel(payload.result);
    setBusy(false, "Complete");
  } catch (error) {
    showError(error.message);
    setBusy(false, "Error");
  }
});

elements.fitParcelButton.addEventListener("click", () => {
  fitParcel();
});

function setBusy(isBusy, label) {
  elements.runButton.disabled = isBusy;
  elements.statusPill.textContent = label;
}

function showError(message) {
  elements.snapshotHeadline.textContent = "The feasibility check hit a snag.";
  elements.parcelFacts.innerHTML = "";
  elements.recommendations.className = "recommendation-list empty-state";
  elements.recommendations.textContent = message;
  elements.mapStatus.textContent = message;
}

function clearResults() {
  elements.snapshotHeadline.textContent = "Running feasibility screen...";
  elements.parcelFacts.innerHTML = "";
  elements.recommendations.className = "recommendation-list empty-state";
  elements.recommendations.textContent = "Working...";
  elements.resources.className = "resource-list empty-state";
  elements.resources.textContent = "Working...";
  elements.notes.innerHTML = "";
  elements.downloadReport.classList.add("hidden");
}

function renderResult(result) {
  elements.snapshotHeadline.textContent = result.headline || result.summary;
  renderFacts(result);
  renderRecommendations(result);
  renderResources(result);
  renderNotes(result);
  elements.downloadReport.href = `/api/report?token=${encodeURIComponent(state.reportToken)}`;
  elements.downloadReport.classList.toggle("hidden", !state.reportToken);
  elements.mapStatus.textContent = `${result.parcel.parcel_number} loaded. ${result.municipality}.`;
}

function renderFacts(result) {
  const zoning = result.zoningDistricts.map((district) => district.code).join(", ") || "-";
  const areaAc = result.parcelAreaSf / 43560;
  const facts = [
    ["Parcel", result.parcel.parcel_number],
    ["Address", result.parcel.address || "-"],
    ["Owner", result.parcel.owner || "-"],
    ["Zoning", zoning],
    ["Jurisdiction", result.municipality],
    ["Site area", `${areaAc.toFixed(2)} ac`],
  ];
  elements.parcelFacts.innerHTML = facts.map(([label, value]) => `
    <div class="fact"><b>${escapeHtml(label)}</b><span>${escapeHtml(value)}</span></div>
  `).join("");
}

function renderRecommendations(result) {
  const recommendations = result.recommendations || [];
  elements.optionCount.textContent = String(recommendations.length);
  if (!recommendations.length) {
    elements.recommendations.className = "recommendation-list empty-state";
    elements.recommendations.textContent = "No recommendations returned.";
    return;
  }
  elements.recommendations.className = "recommendation-list";
  elements.recommendations.innerHTML = recommendations.map((item, index) => {
    const statusClass = statusClassName(item.status);
    const detailLines = [
      `Status: ${item.status}`,
      item.limiting_factors?.length ? `Primary limits: ${item.limiting_factors.join(", ")}.` : "",
      item.note || "",
    ].filter(Boolean);
    return `
      <details class="recommendation ${statusClass}" ${index === 0 ? "open" : ""}>
        <summary>
          <div>
            <h4>${escapeHtml(item.displayName)}</h4>
            <div class="yield">${escapeHtml(item.yieldText)} · ${escapeHtml(item.status)}</div>
          </div>
          <div class="market">${escapeHtml(item.marketText)}</div>
        </summary>
        <div class="recommendation-body">${detailLines.map((line) => `<p>${escapeHtml(line)}</p>`).join("")}</div>
      </details>
    `;
  }).join("");
}

function renderResources(result) {
  const present = (result.protectedResources || []).filter((resource) => resource.measured_acres > 0.005);
  elements.resourceCount.textContent = String(present.length);
  if (!present.length) {
    elements.resources.className = "resource-list empty-state";
    elements.resources.textContent = "No mapped protected resources found on the parcel.";
    return;
  }
  elements.resources.className = "resource-list";
  elements.resources.innerHTML = present
    .sort((a, b) => b.protected_acres - a.protected_acres)
    .map((resource) => `
      <div class="resource">
        <div>
          <strong>${escapeHtml(cleanResourceName(resource.name))}</strong>
          <span>${resource.measured_acres.toFixed(2)} ac measured · ${resource.protected_acres.toFixed(2)} ac protected</span>
        </div>
        <div class="present">Present</div>
      </div>
    `).join("");
}

function renderNotes(result) {
  const notes = [
    result.summary,
    ...(result.details || []).slice(0, 5),
    ...(result.standards || []).slice(0, 4),
  ].filter(Boolean);
  elements.notes.innerHTML = notes.map((note) => `<li>${escapeHtml(note)}</li>`).join("");
}

function drawParcel(result) {
  if (!state.view || !state.Graphic || !state.layers.parcel || !result.geometry?.rings) {
    return;
  }
  state.layers.parcel.removeAll();
  const graphic = new state.Graphic({
    geometry: {
      type: "polygon",
      rings: result.geometry.rings,
      spatialReference: result.geometry.spatialReference || { wkid: 102657 },
    },
    symbol: {
      type: "simple-fill",
      color: [79, 149, 115, 0.08],
      outline: { color: [118, 244, 197, 1], width: 2.4 },
    },
    attributes: {
      Parcel: result.parcel.parcel_number,
      Zoning: result.zoningDistricts.map((district) => district.code).join(", "),
      Owner: result.parcel.owner,
    },
    popupTemplate: {
      title: "Subject parcel",
      content: [
        { type: "fields", fieldInfos: [
          { fieldName: "Parcel", label: "Parcel" },
          { fieldName: "Zoning", label: "Zoning" },
          { fieldName: "Owner", label: "Owner" },
        ] },
      ],
    },
  });
  state.parcelGraphic = graphic;
  state.layers.parcel.add(graphic);
  fitParcel();
}

function fitParcel() {
  if (!state.view || !state.parcelGraphic) {
    return;
  }
  state.view.goTo(state.parcelGraphic.geometry.extent.expand(1.7), { duration: 700 }).catch(() => {});
}

function statusClassName(status) {
  return `status-${String(status || "review").toLowerCase().replace(/[^a-z]+/g, "-").replace(/^-|-$/g, "")}`;
}

function cleanResourceName(name) {
  return String(name || "")
    .replace(" (see section 10.320)", "")
    .replace(", assumed Tier 3", "");
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[char]));
}
