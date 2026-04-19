let map;
let baseLayer;
let localLayer = null;
let selectedBounds = null;
let selectionRectangle = null;
let selectionStart = null;
let selectionMode = false;
let activeDownloadJobId = null;
let activeEmbedJobId = null;
let activeCollectionId = null;
let activeCollectionName = null;
let sourcePresets = [];
let activeSourceId = "";
let telemetryPollHandle = null;
let livePoseMarker = null;
let liveHeadingLine = null;
let hasCenteredOnLivePose = false;
let config = {
  default_tile_url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
  default_source_id: "",
  default_center: {lat: 38.8462, lon: -77.3064, zoom: 12},
  source_presets: [],
  max_tile_download: 5000,
  default_embed_model: "facebook/dinov3-vitl16-pretrain-sat493m",
  default_embed_device: "auto",
  default_embed_batch_size: 4,
  telemetry: {
    nmea_listen_port: 10110,
    debug_listen_port: 10111,
    camera_stream_port: 8080,
  },
};

const selectionSummary = () => document.getElementById("selection-summary");
const downloadStatus = () => document.getElementById("download-status");
const embedStatus = () => document.getElementById("embed-status");
const sourceStatus = () => document.getElementById("source-status");
const telemetryStatus = () => document.getElementById("telemetry-status");
const imuStatus = () => document.getElementById("imu-status");
const navRuntimeStatus = () => document.getElementById("nav-runtime-status");
const stereoStatus = () => document.getElementById("stereo-status");
const voStatus = () => document.getElementById("vo-status");
const geoStatus = () => document.getElementById("geo-status");
const mapRuntimeStatus = () => document.getElementById("map-runtime-status");
const nmeaRawStatus = () => document.getElementById("nmea-raw-status");
const debugPacketStatus = () => document.getElementById("debug-packet-status");

function formatValue(value, digits = 3) {
  if (value === null || value === undefined || value === "") {
    return "n/a";
  }
  const asNumber = Number(value);
  if (Number.isFinite(asNumber)) {
    return asNumber.toFixed(digits);
  }
  if (typeof value === "boolean") {
    return value ? "true" : "false";
  }
  return String(value);
}

function getSourcePreset(sourceId) {
  return sourcePresets.find((source) => source.id === sourceId) || null;
}

function renderSourceStatus(source) {
  if (!source) {
    sourceStatus().textContent = "No imagery source selected.";
    return;
  }
  sourceStatus().textContent = [
    `source=${source.name}`,
    `tile_url=${source.tile_url_template}`,
    `default_zoom=${source.default_min_zoom}-${source.default_max_zoom}`,
    source.note ? `note=${source.note}` : "",
  ].filter(Boolean).join("\n");
}

function setBaseLayer(urlTemplate, attribution, maxZoom = 23) {
  if (baseLayer) {
    baseLayer.remove();
  }
  baseLayer = L.tileLayer(urlTemplate, {
    maxZoom,
    attribution: attribution || "",
  }).addTo(map);
}

function applySourcePreset(sourceId, {recenter = true} = {}) {
  const source = getSourcePreset(sourceId);
  if (!source) {
    return;
  }
  activeSourceId = source.id;
  document.getElementById("source-preset").value = source.id;
  document.getElementById("tile-url-template").value = source.tile_url_template;
  document.getElementById("min-zoom").value = source.default_min_zoom;
  document.getElementById("max-zoom").value = source.default_max_zoom;
  document.getElementById("active-source-label").textContent = source.name;
  renderSourceStatus(source);
  setBaseLayer(source.preview_url_template || source.tile_url_template, source.attribution || "");
  if (recenter && source.default_center) {
    map.setView([source.default_center.lat, source.default_center.lon], source.default_center.zoom || 12);
  }
}

function formatBbox(bounds) {
  if (!bounds) {
    return "No area selected.";
  }
  const north = bounds.getNorth().toFixed(6);
  const south = bounds.getSouth().toFixed(6);
  const east = bounds.getEast().toFixed(6);
  const west = bounds.getWest().toFixed(6);
  return `north=${north}\nsouth=${south}\neast=${east}\nwest=${west}`;
}

function updateSelectionDisplay() {
  selectionSummary().textContent = formatBbox(selectedBounds);
}

function clearSelection() {
  selectedBounds = null;
  selectionStart = null;
  if (selectionRectangle) {
    selectionRectangle.remove();
    selectionRectangle = null;
  }
  updateSelectionDisplay();
}

function setSelection(bounds) {
  selectedBounds = bounds;
  if (selectionRectangle) {
    selectionRectangle.remove();
  }
  selectionRectangle = L.rectangle(bounds, {
    color: "#c96a2b",
    weight: 2,
    fillOpacity: 0.08,
  }).addTo(map);
  updateSelectionDisplay();
}

function setActiveCollection(collection) {
  activeCollectionId = collection.collection_id;
  activeCollectionName = collection.name;
  document.getElementById("embed-collection-id").value = `${collection.name} (${collection.collection_id})`;
}

function formatAge(serverTime, receivedAt) {
  if (!receivedAt) {
    return "n/a";
  }
  return `${Math.max(0, serverTime - receivedAt).toFixed(1)}s`;
}

function updateTelemetryPanels(snapshot) {
  const pose = snapshot.pose || {};
  const nmea = snapshot.listeners?.nmea || {};
  const debug = snapshot.listeners?.debug || {};
  const debugPacket = snapshot.debug || {};
  const poseLat = Number(pose.lat);
  const poseLon = Number(pose.lon);
  const telemetryLines = [
    `source_ip=${pose.source_ip || debug.source_ip || nmea.source_ip || "none"}`,
    `mode=${debugPacket.mode || "unknown"}`,
    `lat=${pose.lat ?? "n/a"}`,
    `lon=${pose.lon ?? "n/a"}`,
    `alt_m=${pose.alt_m ?? "n/a"}`,
    `heading_deg=${pose.heading_deg ?? "n/a"}`,
    `fix_quality=${pose.fix_quality ?? "n/a"}`,
    `status=${pose.status || "n/a"}`,
    `nmea_port=${nmea.port}`,
    `nmea_packets=${nmea.packets}`,
    `nmea_age=${formatAge(snapshot.server_time, nmea.last_received_at)}`,
    nmea.error ? `nmea_error=${nmea.error}` : "",
  ].filter(Boolean);
  telemetryStatus().textContent = telemetryLines.join("\n");

  const imu = debugPacket.imu || {};
  const camera = debugPacket.camera || {};
  const cam0 = camera.cam0 || {};
  const cam1 = camera.cam1 || {};
  const navConfidence = debugPacket.confidence || {};
  const stereo = debugPacket.stereo || {};
  const vo = debugPacket.vo || {};
  const geo = debugPacket.geo || {};
  const terrain = debugPacket.terrain || {};
  const mapRuntime = debugPacket.map || {};
  const nmeaPacket = debugPacket.nmea || {};
  const imuLines = [
    `debug_port=${debug.port}`,
    `debug_packets=${debug.packets}`,
    `debug_age=${formatAge(snapshot.server_time, debug.last_received_at)}`,
    debug.error ? `debug_error=${debug.error}` : "",
    `roll=${(debugPacket.attitude?.roll ?? "n/a")}`,
    `pitch=${(debugPacket.attitude?.pitch ?? "n/a")}`,
    `yaw=${(debugPacket.attitude?.yaw ?? "n/a")}`,
    `ax=${imu.ax ?? "n/a"} ay=${imu.ay ?? "n/a"} az=${imu.az ?? "n/a"}`,
    `gx=${imu.gx ?? "n/a"} gy=${imu.gy ?? "n/a"} gz=${imu.gz ?? "n/a"}`,
    `cam0_ok=${cam0.ok ?? "n/a"} fps=${cam0.fps ?? "n/a"}`,
    `cam1_ok=${cam1.ok ?? "n/a"} fps=${cam1.fps ?? "n/a"}`,
  ].filter(Boolean);
  imuStatus().textContent = imuLines.join("\n");

  const liveFixPill = document.getElementById("live-fix-pill");
  if (Number.isFinite(poseLat) && Number.isFinite(poseLon)) {
    liveFixPill.textContent = `${debugPacket.mode || "fix"} ${poseLat.toFixed(5)}, ${poseLon.toFixed(5)}`;
  } else {
    liveFixPill.textContent = "No live fix";
  }

  const navLines = [
    `mode=${debugPacket.mode || "unknown"}`,
    `fix_type=${pose.fix_type || navConfidence.fix_type || "n/a"}`,
    `confidence=${formatValue(navConfidence.confidence ?? pose.confidence)}`,
    `fix_quality=${formatValue(navConfidence.fix_quality ?? pose.fix_quality, 0)}`,
    `last_abs_fix_age_s=${formatValue(debugPacket.last_absolute_fix_age_s)}`,
    `terrain=${terrain.terrain_class || "n/a"} conf=${formatValue(terrain.confidence)}`,
    `cam0_ok=${cam0.ok ?? "n/a"} cam1_ok=${cam1.ok ?? "n/a"}`,
    `servo=${camera.servo_position || "n/a"}`,
  ];
  navRuntimeStatus().textContent = navLines.join("\n");

  const stereoLines = [
    `valid=${stereo.valid ?? "n/a"}`,
    `altitude_m=${formatValue(stereo.altitude_m)}`,
    `center_depth_m=${formatValue(stereo.center_depth_m)}`,
    `disp_conf=${formatValue(stereo.disparity_confidence)}`,
    `depth_variance=${formatValue(stereo.depth_variance)}`,
  ];
  stereoStatus().textContent = stereoLines.join("\n");

  const voLines = [
    `valid=${vo.valid ?? "n/a"}`,
    `confidence=${formatValue(vo.confidence)}`,
    `track_count=${formatValue(vo.track_count, 0)}`,
    `inlier_ratio=${formatValue(vo.inlier_ratio)}`,
    `parallax=${formatValue(vo.parallax_score)}`,
    `reproj_error=${formatValue(vo.reprojection_error)}`,
  ];
  voStatus().textContent = voLines.join("\n");

  const geoLines = [
    `valid=${geo.valid ?? "n/a"}`,
    `verified=${geo.verified ?? "n/a"}`,
    `confidence=${formatValue(geo.confidence)}`,
    `match_score=${formatValue(geo.match_score)}`,
    `structural=${formatValue(geo.structural_score)}`,
    `inliers=${formatValue(geo.inlier_count, 0)}`,
    `candidates=${formatValue(geo.candidate_count, 0)}`,
    `tile=${geo.tile_path || "n/a"}`,
  ];
  geoStatus().textContent = geoLines.join("\n");

  const mapLines = [
    `collection_id=${mapRuntime.collection_id || "n/a"}`,
    `runtime_embeddings=${mapRuntime.runtime_embeddings ?? "n/a"}`,
    `embedding_backend=${mapRuntime.embedding_backend || "n/a"}`,
    `embedding_backend_ok=${mapRuntime.embedding_backend_ok ?? "n/a"}`,
    `camera_source=${snapshot.camera?.source_ip || "n/a"}`,
  ];
  mapRuntimeStatus().textContent = mapLines.join("\n");

  const nmeaLines = [
    `gga=${nmea.gga || nmeaPacket.gga || "n/a"}`,
    `rmc=${nmea.rmc || nmeaPacket.rmc || "n/a"}`,
  ];
  nmeaRawStatus().textContent = nmeaLines.join("\n");

  debugPacketStatus().textContent = debugPacket && Object.keys(debugPacket).length
    ? JSON.stringify(debugPacket, null, 2)
    : "Waiting for debug packet.";
}

function buildCameraBaseUrl(snapshot) {
  const overrideHost = document.getElementById("camera-host").value.trim();
  const overridePort = document.getElementById("camera-port").value.trim();
  const port = overridePort || String(config.telemetry.camera_stream_port || 8080);
  if (overrideHost) {
    return `http://${overrideHost}:${port}`;
  }
  return snapshot.camera?.base_url || "";
}

function updateCameraStreams(snapshot) {
  const baseUrl = buildCameraBaseUrl(snapshot);
  const cam0 = document.getElementById("cam0-stream");
  const cam1 = document.getElementById("cam1-stream");
  if (!baseUrl) {
    cam0.removeAttribute("src");
    cam1.removeAttribute("src");
    delete cam0.dataset.baseUrl;
    delete cam1.dataset.baseUrl;
    return;
  }
  const cam0Url = `${baseUrl}/stream/cam0`;
  const cam1Url = `${baseUrl}/stream/cam1`;
  if (cam0.dataset.baseUrl !== cam0Url) {
    cam0.src = cam0Url;
    cam0.dataset.baseUrl = cam0Url;
  }
  if (cam1.dataset.baseUrl !== cam1Url) {
    cam1.src = cam1Url;
    cam1.dataset.baseUrl = cam1Url;
  }
}

function updateLivePoseOverlay(snapshot) {
  const pose = snapshot.pose || {};
  const poseLat = Number(pose.lat);
  const poseLon = Number(pose.lon);
  if (!Number.isFinite(poseLat) || !Number.isFinite(poseLon)) {
    return;
  }
  const latLng = [poseLat, poseLon];
  if (!livePoseMarker) {
    livePoseMarker = L.circleMarker(latLng, {
      radius: 8,
      color: "#0b5a74",
      weight: 2,
      fillColor: "#ca6e2d",
      fillOpacity: 0.95,
    }).addTo(map);
  } else {
    livePoseMarker.setLatLng(latLng);
  }

  const heading = Number.isFinite(pose.heading_deg) ? Number(pose.heading_deg) : null;
  if (heading !== null) {
    const headingPoint = projectHeading(latLng[0], latLng[1], heading, 35);
    if (!liveHeadingLine) {
      liveHeadingLine = L.polyline([latLng, headingPoint], {
        color: "#ca6e2d",
        weight: 3,
        opacity: 0.9,
      }).addTo(map);
    } else {
      liveHeadingLine.setLatLngs([latLng, headingPoint]);
    }
  }

  const popupLines = [
    `lat=${poseLat.toFixed(6)}`,
    `lon=${poseLon.toFixed(6)}`,
    `alt_m=${pose.alt_m ?? "n/a"}`,
    `heading=${pose.heading_deg ?? "n/a"}`,
    `fix=${pose.fix_type || "n/a"}`,
    `conf=${pose.confidence ?? "n/a"}`,
  ];
  livePoseMarker.bindPopup(popupLines.join("<br>"));

  if (!hasCenteredOnLivePose) {
    hasCenteredOnLivePose = true;
    map.setView(latLng, Math.max(map.getZoom(), 17));
  }
}

function projectHeading(lat, lon, headingDeg, distanceMeters) {
  const headingRad = headingDeg * Math.PI / 180.0;
  const dNorth = Math.cos(headingRad) * distanceMeters;
  const dEast = Math.sin(headingRad) * distanceMeters;
  const dLat = dNorth / 111320.0;
  const dLon = dEast / (Math.cos(lat * Math.PI / 180.0) * 111320.0);
  return [lat + dLat, lon + dLon];
}

async function loadTelemetry() {
  const response = await fetch("/api/telemetry/latest");
  const snapshot = await response.json();
  updateTelemetryPanels(snapshot);
  updateLivePoseOverlay(snapshot);
  updateCameraStreams(snapshot);
}

async function pollTelemetry() {
  try {
    await loadTelemetry();
  } catch (error) {
    telemetryStatus().textContent = `telemetry_error=${error.message}`;
  } finally {
    telemetryPollHandle = window.setTimeout(pollTelemetry, 1000);
  }
}

function milesToLatDegrees(miles) {
  return miles / 69.0;
}

function milesToLonDegrees(miles, latitude) {
  return miles / (Math.cos(latitude * Math.PI / 180.0) * 69.172);
}

function setSquareAroundCenter(totalMiles) {
  const center = map.getCenter();
  const halfMiles = totalMiles / 2.0;
  const latDelta = milesToLatDegrees(halfMiles);
  const lonDelta = milesToLonDegrees(halfMiles, center.lat);
  const bounds = L.latLngBounds(
    [center.lat - latDelta, center.lng - lonDelta],
    [center.lat + latDelta, center.lng + lonDelta],
  );
  setSelection(bounds);
}

async function loadConfig() {
  const response = await fetch("/api/config");
  config = await response.json();
  sourcePresets = config.source_presets || [];
  const sourceSelect = document.getElementById("source-preset");
  sourceSelect.innerHTML = "";
  for (const source of sourcePresets) {
    const option = document.createElement("option");
    option.value = source.id;
    option.textContent = source.name;
    sourceSelect.appendChild(option);
  }
  document.getElementById("tile-url-template").value = config.default_tile_url;
  document.getElementById("embed-model-name").value = config.default_embed_model;
  document.getElementById("embed-device").value = config.default_embed_device;
  document.getElementById("embed-batch-size").value = config.default_embed_batch_size;
  document.getElementById("camera-port").value = config.telemetry.camera_stream_port || 8080;
  applySourcePreset(config.default_source_id || sourcePresets[0]?.id || "", {recenter: true});
}

async function loadCollections() {
  const response = await fetch("/api/collections");
  const collections = await response.json();
  const container = document.getElementById("collections-list");
  container.innerHTML = "";
  if (!collections.length) {
    container.innerHTML = "<p class='muted'>No cached collections yet.</p>";
    return;
  }

  let stillSelected = false;
  for (const collection of collections) {
    if (collection.collection_id === activeCollectionId) {
      stillSelected = true;
      setActiveCollection(collection);
    }
    const card = document.createElement("div");
    card.className = "collection-card";
    card.innerHTML = `
      <h3>${collection.name}</h3>
      <p>ID: ${collection.collection_id}</p>
      <p>Zooms: ${collection.min_zoom}-${collection.max_zoom}</p>
      <p>Tiles: ${collection.tile_count}</p>
      <p>Embeddings: ${collection.has_embeddings ? "ready" : "missing"}</p>
      <div class="button-row">
        <button data-action="preview">Preview</button>
        <button data-action="embed" class="secondary">Embed</button>
      </div>
    `;
    card.querySelector('[data-action="preview"]').addEventListener("click", () => previewCollection(collection));
    card.querySelector('[data-action="embed"]').addEventListener("click", async () => {
      setActiveCollection(collection);
      try {
        await startEmbed();
      } catch (error) {
        embedStatus().textContent = error.message;
      }
    });
    container.appendChild(card);
  }

  if (!stillSelected && collections.length) {
    setActiveCollection(collections[0]);
  }
}

function previewCollection(collection) {
  if (localLayer) {
    localLayer.remove();
  }
  localLayer = L.tileLayer(`/tiles/${collection.collection_id}/{z}/{x}/{y}.png`, {
    maxZoom: collection.max_zoom,
    opacity: 0.9,
    errorTileUrl: "",
  }).addTo(map);
  const bbox = collection.bbox;
  const bounds = L.latLngBounds([bbox.south, bbox.west], [bbox.north, bbox.east]);
  setSelection(bounds);
  setActiveCollection(collection);
  map.fitBounds(bounds, {padding: [30, 30]});
}

function getSelectionPayload() {
  if (!selectedBounds) {
    throw new Error("Select an area first.");
  }
  return {
    north: selectedBounds.getNorth(),
    south: selectedBounds.getSouth(),
    east: selectedBounds.getEast(),
    west: selectedBounds.getWest(),
  };
}

async function estimateSelection() {
  const payload = {
    bbox: getSelectionPayload(),
    min_zoom: Number(document.getElementById("min-zoom").value),
    max_zoom: Number(document.getElementById("max-zoom").value),
  };
  const response = await fetch("/api/estimate", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  downloadStatus().textContent = `Estimated tile count: ${data.tile_count}\nLimit: ${config.max_tile_download}`;
  return data.tile_count;
}

async function startDownload() {
  const tileCount = await estimateSelection();
  if (tileCount > config.max_tile_download) {
    return;
  }
  const payload = {
    name: document.getElementById("collection-name").value.trim(),
    bbox: getSelectionPayload(),
    min_zoom: Number(document.getElementById("min-zoom").value),
    max_zoom: Number(document.getElementById("max-zoom").value),
    tile_url_template: document.getElementById("tile-url-template").value.trim(),
  };
  const response = await fetch("/api/downloads", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) {
    downloadStatus().textContent = data.error || "Download request failed.";
    return;
  }
  activeDownloadJobId = data.job_id;
  pollDownloadJob();
}

function formatJobStatus(job) {
  return [
    `type=${job.job_type}`,
    `status=${job.status}`,
    `progress=${job.completed_items}/${job.total_items}`,
    job.detail ? `detail=${job.detail}` : "",
    job.error ? `error=${job.error}` : "",
  ].filter(Boolean).join("\n");
}

async function pollDownloadJob() {
  if (!activeDownloadJobId) {
    return;
  }
  const response = await fetch(`/api/jobs/${activeDownloadJobId}`);
  const job = await response.json();
  downloadStatus().textContent = formatJobStatus(job);

  if (job.status === "completed" || job.status === "failed") {
    activeDownloadJobId = null;
    await loadCollections();
    return;
  }
  window.setTimeout(pollDownloadJob, 1000);
}

async function startEmbed() {
  if (!activeCollectionId) {
    throw new Error("Preview or select a cached collection first.");
  }
  const payload = {
    model_name: document.getElementById("embed-model-name").value.trim(),
    device: document.getElementById("embed-device").value.trim(),
    batch_size: Number(document.getElementById("embed-batch-size").value),
    limit: Number(document.getElementById("embed-limit").value),
    overwrite: document.getElementById("embed-overwrite").checked,
  };
  const response = await fetch(`/api/collections/${activeCollectionId}/embed`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) {
    embedStatus().textContent = data.error || "Embed request failed.";
    return;
  }
  activeEmbedJobId = data.job_id;
  embedStatus().textContent = `Queued embedding job for ${activeCollectionName || activeCollectionId}.`;
  pollEmbedJob();
}

async function pollEmbedJob() {
  if (!activeEmbedJobId) {
    return;
  }
  const response = await fetch(`/api/jobs/${activeEmbedJobId}`);
  const job = await response.json();
  embedStatus().textContent = formatJobStatus(job);

  if (job.status === "completed" || job.status === "failed") {
    activeEmbedJobId = null;
    await loadCollections();
    return;
  }
  window.setTimeout(pollEmbedJob, 1000);
}

function initMap() {
  map = L.map("map").setView([38.8462, -77.3064], 12);
  setBaseLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", "&copy; OpenStreetMap contributors", 19);

  map.on("click", (event) => {
    if (!selectionMode) {
      return;
    }
    if (!selectionStart) {
      selectionStart = event.latlng;
      downloadStatus().textContent = "First corner set. Click second corner.";
      return;
    }
    const bounds = L.latLngBounds(selectionStart, event.latlng);
    setSelection(bounds);
    selectionStart = null;
    selectionMode = false;
    downloadStatus().textContent = "Selection ready.";
  });
}

function bindUi() {
  document.getElementById("source-preset").addEventListener("change", () => {
    applySourcePreset(document.getElementById("source-preset").value, {recenter: true});
    downloadStatus().textContent = "Imagery source updated.";
  });

  document.getElementById("start-selection").addEventListener("click", () => {
    selectionMode = true;
    selectionStart = null;
    downloadStatus().textContent = "Click first corner, then second corner.";
  });

  document.getElementById("clear-selection").addEventListener("click", () => {
    clearSelection();
    downloadStatus().textContent = "Selection cleared.";
  });

  document.querySelectorAll(".preset-range").forEach((button) => {
    button.addEventListener("click", () => {
      const miles = Number(button.dataset.miles);
      setSquareAroundCenter(miles);
      downloadStatus().textContent = `${miles}x${miles} mile square selected around map center.`;
    });
  });

  document.getElementById("estimate-download").addEventListener("click", async () => {
    try {
      await estimateSelection();
    } catch (error) {
      downloadStatus().textContent = error.message;
    }
  });

  document.getElementById("start-download").addEventListener("click", async () => {
    try {
      await startDownload();
    } catch (error) {
      downloadStatus().textContent = error.message;
    }
  });

  document.getElementById("start-embed").addEventListener("click", async () => {
    try {
      await startEmbed();
    } catch (error) {
      embedStatus().textContent = error.message;
    }
  });

  document.getElementById("refresh-cameras").addEventListener("click", async () => {
    try {
      await loadTelemetry();
    } catch (error) {
      telemetryStatus().textContent = `telemetry_error=${error.message}`;
    }
  });
}

async function main() {
  initMap();
  bindUi();
  await loadConfig();
  await loadCollections();
  await loadTelemetry();
  if (telemetryPollHandle) {
    window.clearTimeout(telemetryPollHandle);
  }
  pollTelemetry();
}

main();
