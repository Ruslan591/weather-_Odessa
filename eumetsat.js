/* =========================================================
   EUMETSAT.JS — карта спутника EUMETSAT (EUMETView WMS) для eumetsat.html.
   Источник: https://view.eumetsat.int/geoserver/wms — бесплатно, без
   регистрации (EUMETView WMS, "Fees: none", "AccessConstraints: none").

   Слои:
     msg_fes:clm    — Cloud Mask (ясно/облачно, пиксельно), геостационар
                      Meteosat-0°, обновление раз в 15 мин
     msg_fes:cth    — Cloud Top Height (высота верхней границы облака,
                      непрерывное значение — ярусов low/mid/high как
                      готового продукта у EUMETSAT нет, это ближайшая
                      альтернатива), тоже 15 мин
     mtg_fd:li_afa  — Lightning Imager Accumulated Flash Area (MTG-I) —
                      РЕАЛЬНАЯ детекция вспышек молний со спутника,
                      не прокси. Обновление раз в 5 мин.

   ВАЖНО: эти слои отдаются WMS только в EPSG:4326 (не EPSG:3857) — для
   каждого TileLayer.WMS указан crs: L.CRS.EPSG4326, базовая карта (OSM)
   остаётся в обычной проекции, Leaflet сам делает трансформацию per-tile.
========================================================= */

const WMS_BASE = "https://view.eumetsat.int/geoserver/wms";
const CENTER_LAT = 46.4406;
const CENTER_LON = 30.7703;

const LAYERS = {
    clm: {
        name: "msg_fes:clm",
        stepMinutes: 15,
        legend: `${WMS_BASE}?service=WMS&version=1.3.0&request=GetLegendGraphic&format=image%2Fpng&width=640&height=80&layer=msg_fes%3Aclm`,
    },
    cth: {
        name: "msg_fes:cth",
        stepMinutes: 15,
        legend: `${WMS_BASE}?service=WMS&version=1.3.0&request=GetLegendGraphic&format=image%2Fpng&width=640&height=80&layer=msg_fes%3Acth`,
    },
    li_afa: {
        name: "mtg_fd:li_afa",
        stepMinutes: 5,
        legend: `${WMS_BASE}?service=WMS&version=1.3.0&request=GetLegendGraphic&format=image%2Fpng&width=640&height=80&layer=mtg_fd%3Ali_afa`,
    },
};

let currentKey = "clm";
let currentWmsLayer = null;
let timeSteps = [];       // массив Date, от старых к новым
let position = 0;
let animationTimer = false;

const map = L.map("mapid", { maxZoom: 10, attributionControl: true })
    .setView([CENTER_LAT, CENTER_LON], 6);

L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: '&copy; <a href="https://openstreetmap.org">OpenStreetMap</a> contributors',
    subdomains: "abc",
}).addTo(map);

L.marker([CENTER_LAT, CENTER_LON]).addTo(map).bindPopup("Одесса (СИНОП 33837)");

function isoNoMillis(d){
    return d.toISOString().replace(/\.\d{3}Z$/, ".000Z");
}

function buildTimeSteps(stepMinutes){
    // последние 2 часа реальных кадров, округлено вниз до шага сетки EUMETSAT
    const now = new Date();
    const stepMs = stepMinutes * 60000;
    const lastStep = new Date(Math.floor(now.getTime() / stepMs) * stepMs);
    const steps = [];
    const count = Math.floor(120 / stepMinutes); // 2 часа истории
    for(let i = count; i >= 0; i--){
        steps.push(new Date(lastStep.getTime() - i * stepMs));
    }
    return steps;
}

function updateTimestampLabel(){
    const d = timeSteps[position];
    if(!d) return;
    const label = d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
    const isNow = position === timeSteps.length - 1;
    document.getElementById("eumTimestamp").textContent = isNow ? `${label} · сейчас` : label;
    document.getElementById("eumSlider").value = position;
}

function setLayer(key){
    currentKey = key;
    document.querySelectorAll("#eumLayerTabs button").forEach(b => {
        b.classList.toggle("active", b.dataset.layer === key);
    });
    document.getElementById("eumLegendImg").src = LAYERS[key].legend;

    timeSteps = buildTimeSteps(LAYERS[key].stepMinutes);
    position = timeSteps.length - 1;
    const slider = document.getElementById("eumSlider");
    slider.min = 0;
    slider.max = timeSteps.length - 1;
    slider.value = position;

    if(currentWmsLayer){
        map.removeLayer(currentWmsLayer);
        currentWmsLayer = null;
    }
    renderCurrentFrame();
}

function renderCurrentFrame(){
    const timeIso = isoNoMillis(timeSteps[position]);
    if(currentWmsLayer){
        currentWmsLayer.setParams({ time: timeIso });
    } else {
        currentWmsLayer = L.tileLayer.wms(WMS_BASE, {
            layers: LAYERS[currentKey].name,
            format: "image/png",
            transparent: true,
            version: "1.3.0",
            crs: L.CRS.EPSG4326,
            opacity: 0.75,
            time: timeIso,
        }).addTo(map);
    }
    updateTimestampLabel();
}

function stopAnim(){
    if(animationTimer){
        clearTimeout(animationTimer);
        animationTimer = false;
        document.getElementById("eumPlayBtn").textContent = "▶";
        return true;
    }
    return false;
}

function stepTo(newPos){
    if(newPos < 0) newPos = 0;
    if(newPos >= timeSteps.length) newPos = 0; // зациклить
    position = newPos;
    renderCurrentFrame();
}

function playTick(){
    stepTo(position + 1);
    if(animationTimer) animationTimer = setTimeout(playTick, 800);
}

function playStop(){
    if(stopAnim()) return;
    animationTimer = true;
    document.getElementById("eumPlayBtn").textContent = "⏸";
    playTick();
}

document.getElementById("eumPrevBtn").addEventListener("click", () => { stopAnim(); stepTo(position - 1); });
document.getElementById("eumNextBtn").addEventListener("click", () => { stopAnim(); stepTo(position + 1); });
document.getElementById("eumPlayBtn").addEventListener("click", playStop);
document.getElementById("eumSlider").addEventListener("input", (e) => {
    stopAnim();
    stepTo(parseInt(e.target.value, 10));
});
document.querySelectorAll("#eumLayerTabs button").forEach(btn => {
    btn.addEventListener("click", () => { stopAnim(); setLayer(btn.dataset.layer); });
});

setLayer("clm");
// раз в 5 минут пересчитываем сетку времени (появляются новые кадры)
setInterval(() => { if(!animationTimer) setLayer(currentKey); }, 5 * 60000);
