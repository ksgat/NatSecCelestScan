const config = {
  source_presets: [
    {
      id: "fairfax_2025",
      name: "Fairfax 2025 Ortho",
      tile_url_template: "https://www.fairfaxcounty.gov/gisimagery/rest/services/AerialPhotography/2025AerialPhotographyCached/ImageServer/tile/{z}/{y}/{x}",
      preview_url_template: "https://www.fairfaxcounty.gov/gisimagery/rest/services/AerialPhotography/2025AerialPhotographyCached/ImageServer/tile/{z}/{y}/{x}",
      attribution: "Fairfax County GIS",
      default_center: {lat: 38.8462, lon: -77.3064, zoom: 12},
      default_min_zoom: 17,
      default_max_zoom: 19,
      note: "Representative northern Virginia collection for the demo build.",
    },
    {
      id: "loudoun_2023",
      name: "Loudoun 2023 Ortho",
      tile_url_template: "https://logis.loudoun.gov/image/rest/services/Aerial/COLOR_2023_CACHED/ImageServer/tile/{z}/{y}/{x}",
      preview_url_template: "https://logis.loudoun.gov/image/rest/services/Aerial/COLOR_2023_CACHED/ImageServer/tile/{z}/{y}/{x}",
      attribution: "Loudoun County LOGIS",
      default_center: {lat: 39.081, lon: -77.55, zoom: 11},
      default_min_zoom: 17,
      default_max_zoom: 19,
      note: "Alternate public orthophoto source for demo browsing.",
    },
    {
      id: "osm_placeholder",
      name: "OSM Placeholder",
      tile_url_template: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
      preview_url_template: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
      attribution: "&copy; OpenStreetMap contributors",
      default_center: {lat: 38.89, lon: -77.2, zoom: 11},
      default_min_zoom: 14,
      default_max_zoom: 17,
      note: "UI-only backup layer.",
    },
  ],
  collections: [
    {
      collection_id: "fairfax-runtime-1mi-b6f538ab",
      name: "fairfax-runtime-1mi",
      min_zoom: 17,
      max_zoom: 19,
      tile_count: 1036,
      has_embeddings: false,
      bbox: {north: 38.8532, south: 38.8392, east: -77.2964, west: -77.3164},
    },
    {
      collection_id: "loudoun-demo-0a2c9911",
      name: "loudoun-demo-grid",
      min_zoom: 17,
      max_zoom: 18,
      tile_count: 612,
      has_embeddings: true,
      bbox: {north: 39.087, south: 39.074, east: -77.54, west: -77.563},
    },
  ],
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

let map;
let baseLayer;
let selectionMode = false;
let selectionStart = null;
let selectionRectangle = null;
let selectedBounds = null;
let livePoseMarker = null;
let liveHeadingLine = null;
let hasCenteredOnLivePose = false;
let activeCollection = config.collections[0];
let activeSourceId = config.source_presets[0].id;
let telemetryTimer = null;
let topbarRigState = document.getElementById("topbar-rig-state");

function inlineCameraSvg(title, accent, secondary) {
  const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 480">
      <defs>
        <linearGradient id="g" x1="0" x2="1" y1="0" y2="1">
          <stop stop-color="#ffffff" offset="0"/>
          <stop stop-color="#ffffff" offset="1"/>
        </linearGradient>
      </defs>
      <rect width="640" height="480" fill="#ffffff"/>
      <rect x="28" y="28" width="584" height="424" fill="url(#g)" stroke="#000000" stroke-width="2"/>
      <path d="M0 356 L120 288 L210 318 L320 246 L436 306 L640 214" fill="none" stroke="#000000" stroke-width="3"/>
      <path d="M0 404 L148 334 L262 360 L390 286 L474 328 L640 266" fill="none" stroke="#000000" stroke-width="2"/>
      <circle cx="470" cy="118" r="44" fill="#ffffff" stroke="#000000" stroke-width="2"/>
      <circle cx="470" cy="118" r="26" fill="#ffffff" stroke="#000000" stroke-width="2"/>
      <rect x="52" y="54" width="220" height="84" rx="0" fill="#ffffff" stroke="#000000" stroke-width="2"/>
      <text x="72" y="96" font-family="Arial, Helvetica, sans-serif" font-size="26" fill="#000000">${title}</text>
      <text x="72" y="126" font-family="Arial, Helvetica, sans-serif" font-size="16" fill="#000000">sample feed</text>
    </svg>
  `.trim();
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

function checksum(sentenceBody) {
  let value = 0;
  for (const char of sentenceBody) {
    value ^= char.charCodeAt(0);
  }
  return value.toString(16).toUpperCase().padStart(2, "0");
}

function formatLat(lat) {
  const hemisphere = lat >= 0 ? "N" : "S";
  const abs = Math.abs(lat);
  const degrees = Math.trunc(abs);
  const minutes = (abs - degrees) * 60.0;
  return [`${String(degrees).padStart(2, "0")}${minutes.toFixed(4).padStart(7, "0")}`, hemisphere];
}

function formatLon(lon) {
  const hemisphere = lon >= 0 ? "E" : "W";
  const abs = Math.abs(lon);
  const degrees = Math.trunc(abs);
  const minutes = (abs - degrees) * 60.0;
  return [`${String(degrees).padStart(3, "0")}${minutes.toFixed(4).padStart(7, "0")}`, hemisphere];
}

function hhmmss(date) {
  return `${String(date.getUTCHours()).padStart(2, "0")}${String(date.getUTCMinutes()).padStart(2, "0")}${String(date.getUTCSeconds()).padStart(2, "0")}`;
}

function ddmmyy(date) {
  return `${String(date.getUTCDate()).padStart(2, "0")}${String(date.getUTCMonth() + 1).padStart(2, "0")}${String(date.getUTCFullYear()).slice(-2)}`;
}

function formatGGA(lat, lon, altM, fixQuality = 1, satellites = 9) {
  const now = new Date();
  const [latValue, latHemisphere] = formatLat(lat);
  const [lonValue, lonHemisphere] = formatLon(lon);
  const body = `GPGGA,${hhmmss(now)},${latValue},${latHemisphere},${lonValue},${lonHemisphere},${fixQuality},${satellites},0.8,${altM.toFixed(1)},M,,,`;
  return `$${body}*${checksum(body)}`;
}

function formatRMC(lat, lon, headingDeg, speedKnots) {
  const now = new Date();
  const [latValue, latHemisphere] = formatLat(lat);
  const [lonValue, lonHemisphere] = formatLon(lon);
  const body = `GPRMC,${hhmmss(now)},A,${latValue},${latHemisphere},${lonValue},${lonHemisphere},${speedKnots.toFixed(1)},${headingDeg.toFixed(1)},${ddmmyy(now)},,,`;
  return `$${body}*${checksum(body)}`;
}

function formatAge(seconds) {
  return `${Math.max(0, seconds).toFixed(1)}s`;
}

function formatValue(value, digits = 3) {
  if (value === null || value === undefined || value === "") {
    return "n/a";
  }
  const numeric = Number(value);
  if (Number.isFinite(numeric)) {
    return numeric.toFixed(digits);
  }
  if (typeof value === "boolean") {
    return value ? "true" : "false";
  }
  return String(value);
}

function getSourcePreset(sourceId) {
  return config.source_presets.find((source) => source.id === sourceId) || null;
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

function applySourcePreset(sourceId, { recenter = true } = {}) {
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
  sourceStatus().textContent = [
    `source=${source.name}`,
    `tile_url=${source.tile_url_template}`,
    `default_zoom=${source.default_min_zoom}-${source.default_max_zoom}`,
    source.note ? `note=${source.note}` : "",
  ].filter(Boolean).join("\n");
  setBaseLayer(source.preview_url_template || source.tile_url_template, source.attribution || "");
  if (recenter && source.default_center) {
    map.setView([source.default_center.lat, source.default_center.lon], source.default_center.zoom || 12);
  }
}

function formatBbox(bounds) {
  if (!bounds) {
    return "No area selected.";
  }
  return [
    `north=${bounds.getNorth().toFixed(6)}`,
    `south=${bounds.getSouth().toFixed(6)}`,
    `east=${bounds.getEast().toFixed(6)}`,
    `west=${bounds.getWest().toFixed(6)}`,
  ].join("\n");
}

function setSelection(bounds) {
  selectedBounds = bounds;
  if (selectionRectangle) {
    selectionRectangle.remove();
  }
  selectionRectangle = L.rectangle(bounds, {
    color: "#000000",
    weight: 2,
    fillOpacity: 0,
  }).addTo(map);
  selectionSummary().textContent = formatBbox(bounds);
}

function clearSelection() {
  selectedBounds = null;
  selectionStart = null;
  if (selectionRectangle) {
    selectionRectangle.remove();
    selectionRectangle = null;
  }
  selectionSummary().textContent = "No area selected.";
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
  downloadStatus().textContent = `${totalMiles}x${totalMiles} mile square selected around map center.\nStatic demo mode: no backend request sent.`;
}

function renderCollections() {
  const container = document.getElementById("collections-list");
  container.innerHTML = "";
  for (const collection of config.collections) {
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
        <button data-action="embed" class="secondary">Sample Embed</button>
      </div>
    `;
    card.querySelector('[data-action="preview"]').addEventListener("click", () => previewCollection(collection));
    card.querySelector('[data-action="embed"]').addEventListener("click", () => {
      setActiveCollection(collection);
      embedStatus().textContent = [
        `type=embed`,
        `status=completed`,
        `progress=${collection.tile_count}/${collection.tile_count}`,
        `detail=sample embedding index already built for showcase`,
      ].join("\n");
    });
    container.appendChild(card);
  }
  setActiveCollection(activeCollection);
}

function setActiveCollection(collection) {
  activeCollection = collection;
  document.getElementById("embed-collection-id").value = `${collection.name} (${collection.collection_id})`;
}

function previewCollection(collection) {
  setActiveCollection(collection);
  const bounds = L.latLngBounds(
    [collection.bbox.south, collection.bbox.west],
    [collection.bbox.north, collection.bbox.east],
  );
  setSelection(bounds);
  map.fitBounds(bounds, { padding: [30, 30] });
  downloadStatus().textContent = `Previewed cached collection ${collection.collection_id}.\nStatic demo mode: this mimics selecting an existing runtime cache.`;
}

function updateLivePoseOverlay(snapshot) {
  const pose = snapshot.pose || {};
  const lat = Number(pose.lat);
  const lon = Number(pose.lon);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
    return;
  }
  const latLng = [lat, lon];
  if (!livePoseMarker) {
    livePoseMarker = L.circleMarker(latLng, {
      radius: 8,
      color: "#000000",
      weight: 2,
      fillColor: "#ffffff",
      fillOpacity: 1,
    }).addTo(map);
  } else {
    livePoseMarker.setLatLng(latLng);
  }

  const heading = Number(pose.heading_deg || 0.0);
  const headingPoint = projectHeading(lat, lon, heading, 35);
  if (!liveHeadingLine) {
    liveHeadingLine = L.polyline([latLng, headingPoint], {
      color: "#000000",
      weight: 3,
      opacity: 0.9,
    }).addTo(map);
  } else {
    liveHeadingLine.setLatLngs([latLng, headingPoint]);
  }

  livePoseMarker.bindPopup([
    `lat=${lat.toFixed(6)}`,
    `lon=${lon.toFixed(6)}`,
    `alt_m=${formatValue(pose.alt_m)}`,
    `heading=${formatValue(heading)}`,
    `fix=${pose.fix_type || "n/a"}`,
    `conf=${formatValue(pose.confidence)}`,
  ].join("<br>"));

  if (!hasCenteredOnLivePose) {
    hasCenteredOnLivePose = true;
    map.setView(latLng, 17);
  }
}

function projectHeading(lat, lon, headingDeg, distanceMeters) {
  const headingRad = headingDeg * Math.PI / 180.0;
  const dNorth = Math.cos(headingRad) * distanceMeters;
  const dEast = Math.sin(headingRad) * distanceMeters;
  return [
    lat + dNorth / 111320.0,
    lon + dEast / (Math.cos(lat * Math.PI / 180.0) * 111320.0),
  ];
}

function dummyTelemetrySnapshot(tSeconds) {
  const center = config.source_presets[0].default_center;
  const radiusLat = 0.0028;
  const radiusLon = 0.0042;
  const lat = center.lat + Math.sin(tSeconds * 0.18) * radiusLat;
  const lon = center.lon + Math.cos(tSeconds * 0.18) * radiusLon;
  const headingDeg = (90 + tSeconds * 11) % 360;
  const altM = 61 + Math.sin(tSeconds * 0.24) * 7;
  const speedKnots = 14.8 + Math.sin(tSeconds * 0.3) * 2.1;
  const confidence = 0.82 + Math.sin(tSeconds * 0.21) * 0.08;
  const gga = formatGGA(lat, lon, altM, 1, 10);
  const rmc = formatRMC(lat, lon, headingDeg, speedKnots);
  return {
    server_time: tSeconds,
    pose: {
      lat,
      lon,
      alt_m: altM,
      heading_deg: headingDeg,
      confidence,
      fix_type: "geo_match",
      fix_quality: 1,
      source_ip: "192.168.0.93",
      status: "A",
    },
    listeners: {
      nmea: {
        port: 10110,
        packets: Math.floor(tSeconds * 2.0),
        last_received_at: tSeconds - 0.2,
        source_ip: "192.168.0.93",
        error: "",
        gga,
        rmc,
      },
      debug: {
        port: 10111,
        packets: Math.floor(tSeconds),
        last_received_at: tSeconds - 0.25,
        source_ip: "192.168.0.93",
        error: "",
      },
    },
    camera: {
      source_ip: "192.168.0.93",
      port: 8080,
    },
    debug: {
      type: "nav_debug",
      ts: tSeconds,
      mode: "GEO_MATCH",
      last_absolute_fix_age_s: 0.6 + Math.abs(Math.sin(tSeconds * 0.14)) * 1.4,
      pose: { lat, lon, alt_m: altM, heading_deg: headingDeg, confidence, fix_type: "geo_match" },
      attitude: {
        roll: Math.sin(tSeconds * 0.42) * 2.8,
        pitch: Math.cos(tSeconds * 0.31) * 1.9,
        yaw: headingDeg,
      },
      imu: {
        ax: Math.sin(tSeconds * 0.28) * 0.03,
        ay: Math.cos(tSeconds * 0.33) * 0.02,
        az: 1.0 + Math.sin(tSeconds * 0.15) * 0.01,
        gx: Math.sin(tSeconds * 0.5) * 0.8,
        gy: Math.cos(tSeconds * 0.45) * 0.5,
        gz: Math.sin(tSeconds * 0.24) * 1.1,
        temp: 31.6,
      },
      stereo: {
        valid: true,
        altitude_m: altM,
        center_depth_m: altM,
        disparity_confidence: 0.78 + Math.sin(tSeconds * 0.17) * 0.07,
        depth_variance: 0.18 + Math.abs(Math.cos(tSeconds * 0.25)) * 0.09,
      },
      vo: {
        valid: true,
        confidence: 0.69 + Math.sin(tSeconds * 0.22) * 0.09,
        track_count: 132 + Math.round(Math.sin(tSeconds * 0.35) * 24),
        inlier_ratio: 0.56 + Math.sin(tSeconds * 0.27) * 0.08,
        parallax_score: 6.4 + Math.cos(tSeconds * 0.41) * 1.2,
        reprojection_error: 1.1 + Math.abs(Math.sin(tSeconds * 0.31)) * 0.4,
      },
      geo: {
        valid: true,
        verified: true,
        confidence: confidence,
        candidate_count: 6,
        inlier_count: 54 + Math.round(Math.sin(tSeconds * 0.3) * 8),
        structural_score: 0.71 + Math.sin(tSeconds * 0.14) * 0.05,
        match_score: 0.77 + Math.cos(tSeconds * 0.16) * 0.04,
        tile_path: "fairfax-runtime-1mi-b6f538ab/tiles/18/74778/100330.png",
      },
      terrain: {
        terrain_class: "urban",
        confidence: 0.87,
        inference_ms: 18.2,
      },
      confidence: {
        confidence,
        fix_quality: 1,
        fix_type: "geo_match",
      },
      camera: {
        cam0: { ok: true, fps: 4.9 },
        cam1: { ok: true, fps: 5.0 },
        servo_position: "DOWN",
      },
      map: {
        collection_id: activeCollection.collection_id,
        runtime_embeddings: false,
        embedding_backend: "disabled",
        embedding_backend_ok: false,
      },
      nmea: { gga, rmc },
    },
  };
}

function updateTelemetryPanels(snapshot) {
  const pose = snapshot.pose || {};
  const debugPacket = snapshot.debug || {};
  const nmea = snapshot.listeners.nmea || {};
  const debug = snapshot.listeners.debug || {};
  const imu = debugPacket.imu || {};
  const camera = debugPacket.camera || {};
  const stereo = debugPacket.stereo || {};
  const vo = debugPacket.vo || {};
  const geo = debugPacket.geo || {};
  const terrain = debugPacket.terrain || {};
  const mapRuntime = debugPacket.map || {};
  const nmeaPacket = debugPacket.nmea || {};

  telemetryStatus().textContent = [
    `source_ip=${pose.source_ip || "192.168.0.93"}`,
    `mode=${debugPacket.mode || "unknown"}`,
    `lat=${formatValue(pose.lat, 6)}`,
    `lon=${formatValue(pose.lon, 6)}`,
    `alt_m=${formatValue(pose.alt_m)}`,
    `heading_deg=${formatValue(pose.heading_deg)}`,
    `fix_quality=${formatValue(pose.fix_quality, 0)}`,
    `status=${pose.status || "A"}`,
    `nmea_port=${nmea.port}`,
    `nmea_packets=${nmea.packets}`,
    `nmea_age=${formatAge(snapshot.server_time - nmea.last_received_at)}`,
  ].join("\n");

  imuStatus().textContent = [
    `debug_port=${debug.port}`,
    `debug_packets=${debug.packets}`,
    `debug_age=${formatAge(snapshot.server_time - debug.last_received_at)}`,
    `roll=${formatValue(debugPacket.attitude?.roll)}`,
    `pitch=${formatValue(debugPacket.attitude?.pitch)}`,
    `yaw=${formatValue(debugPacket.attitude?.yaw)}`,
    `ax=${formatValue(imu.ax, 4)} ay=${formatValue(imu.ay, 4)} az=${formatValue(imu.az, 4)}`,
    `gx=${formatValue(imu.gx, 4)} gy=${formatValue(imu.gy, 4)} gz=${formatValue(imu.gz, 4)}`,
    `cam0_ok=${camera.cam0?.ok ?? "n/a"} fps=${formatValue(camera.cam0?.fps, 2)}`,
    `cam1_ok=${camera.cam1?.ok ?? "n/a"} fps=${formatValue(camera.cam1?.fps, 2)}`,
  ].join("\n");

  navRuntimeStatus().textContent = [
    `mode=${debugPacket.mode || "unknown"}`,
    `fix_type=${pose.fix_type || debugPacket.confidence?.fix_type || "n/a"}`,
    `confidence=${formatValue(debugPacket.confidence?.confidence ?? pose.confidence)}`,
    `fix_quality=${formatValue(debugPacket.confidence?.fix_quality ?? pose.fix_quality, 0)}`,
    `last_abs_fix_age_s=${formatValue(debugPacket.last_absolute_fix_age_s)}`,
    `terrain=${terrain.terrain_class || "n/a"} conf=${formatValue(terrain.confidence)}`,
    `cam0_ok=${camera.cam0?.ok ?? "n/a"} cam1_ok=${camera.cam1?.ok ?? "n/a"}`,
    `servo=${camera.servo_position || "n/a"}`,
  ].join("\n");

  stereoStatus().textContent = [
    `valid=${stereo.valid ?? "n/a"}`,
    `altitude_m=${formatValue(stereo.altitude_m)}`,
    `center_depth_m=${formatValue(stereo.center_depth_m)}`,
    `disp_conf=${formatValue(stereo.disparity_confidence)}`,
    `depth_variance=${formatValue(stereo.depth_variance)}`,
  ].join("\n");

  voStatus().textContent = [
    `valid=${vo.valid ?? "n/a"}`,
    `confidence=${formatValue(vo.confidence)}`,
    `track_count=${formatValue(vo.track_count, 0)}`,
    `inlier_ratio=${formatValue(vo.inlier_ratio)}`,
    `parallax=${formatValue(vo.parallax_score)}`,
    `reproj_error=${formatValue(vo.reprojection_error)}`,
  ].join("\n");

  geoStatus().textContent = [
    `valid=${geo.valid ?? "n/a"}`,
    `verified=${geo.verified ?? "n/a"}`,
    `confidence=${formatValue(geo.confidence)}`,
    `match_score=${formatValue(geo.match_score)}`,
    `structural=${formatValue(geo.structural_score)}`,
    `inliers=${formatValue(geo.inlier_count, 0)}`,
    `candidates=${formatValue(geo.candidate_count, 0)}`,
    `tile=${geo.tile_path || "n/a"}`,
  ].join("\n");

  mapRuntimeStatus().textContent = [
    `collection_id=${mapRuntime.collection_id || activeCollection.collection_id}`,
    `runtime_embeddings=${mapRuntime.runtime_embeddings ?? false}`,
    `embedding_backend=${mapRuntime.embedding_backend || "disabled"}`,
    `embedding_backend_ok=${mapRuntime.embedding_backend_ok ?? false}`,
    `camera_source=${snapshot.camera.source_ip}`,
  ].join("\n");

  nmeaRawStatus().textContent = [
    `gga=${nmea.gga || nmeaPacket.gga || "n/a"}`,
    `rmc=${nmea.rmc || nmeaPacket.rmc || "n/a"}`,
  ].join("\n");

  debugPacketStatus().textContent = JSON.stringify(debugPacket, null, 2);
  document.getElementById("live-fix-pill").textContent = `geo ${Number(pose.lat).toFixed(5)}, ${Number(pose.lon).toFixed(5)}`;
  topbarRigState.textContent = pose.confidence >= 0.8 ? "Nominal" : "Monitoring";
}

function updateCameraStreams() {
  document.getElementById("cam0-stream").src = inlineCameraSvg("cam0 / sky", "#000000", "#8c8c8c");
  document.getElementById("cam1-stream").src = inlineCameraSvg("cam1 / ground", "#000000", "#8c8c8c");
}

function estimateSelection() {
  if (!selectedBounds) {
    downloadStatus().textContent = "Select an area first.";
    return;
  }
  const source = getSourcePreset(activeSourceId);
  const zoomSpan = Number(document.getElementById("max-zoom").value) - Number(document.getElementById("min-zoom").value) + 1;
  const roughTileCount = Math.round((selectedBounds.getNorth() - selectedBounds.getSouth()) * (selectedBounds.getEast() - selectedBounds.getWest()) * 12500000 * Math.max(1, zoomSpan));
  downloadStatus().textContent = `Estimated tile count: ${roughTileCount}\nStatic demo mode: no backend request sent.\nSource=${source?.name || "n/a"}`;
}

function startDownload() {
  downloadStatus().textContent = [
    `type=download`,
    `status=completed`,
    `progress=1036/1036`,
    `detail=demo collection already cached locally`,
  ].join("\n");
}

function startEmbed() {
  embedStatus().textContent = [
    `type=embed`,
    `status=completed`,
    `progress=1036/1036`,
    `detail=sample embedding index ready for retrieval`,
  ].join("\n");
}

function initMap() {
  map = L.map("map").setView([38.8462, -77.3064], 12);
  setBaseLayer(config.source_presets[0].preview_url_template, config.source_presets[0].attribution, 19);
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
    downloadStatus().textContent = "Selection ready. Static demo mode: estimate/download buttons update local status only.";
  });
}

function bindUi() {
  const sourceSelect = document.getElementById("source-preset");
  for (const source of config.source_presets) {
    const option = document.createElement("option");
    option.value = source.id;
    option.textContent = source.name;
    sourceSelect.appendChild(option);
  }
  sourceSelect.addEventListener("change", () => applySourcePreset(sourceSelect.value, { recenter: true }));

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
    button.addEventListener("click", () => setSquareAroundCenter(Number(button.dataset.miles)));
  });
  document.getElementById("estimate-download").addEventListener("click", estimateSelection);
  document.getElementById("start-download").addEventListener("click", startDownload);
  document.getElementById("start-embed").addEventListener("click", startEmbed);
  document.getElementById("refresh-cameras").addEventListener("click", updateCameraStreams);
}

function startTelemetryLoop() {
  if (telemetryTimer) {
    window.clearInterval(telemetryTimer);
  }
  const render = () => {
    const tSeconds = performance.now() / 1000.0;
    const snapshot = dummyTelemetrySnapshot(tSeconds);
    updateTelemetryPanels(snapshot);
    updateLivePoseOverlay(snapshot);
  };
  render();
  telemetryTimer = window.setInterval(render, 1000);
}

function init() {
  initMap();
  bindUi();
  renderCollections();
  applySourcePreset(activeSourceId, { recenter: true });
  previewCollection(activeCollection);
  updateCameraStreams();
  startTelemetryLoop();
}

init();
