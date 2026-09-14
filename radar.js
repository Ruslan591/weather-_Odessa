/* =========================================================
   RADAR.JS — интерактивная карта осадков (RainViewer) для radar.html.
   Основано на официальном примере rainviewer/rainviewer-api-example
   (Leaflet + weather-maps.json), адаптировано: тёмная тема, ползунок
   по всем кадрам (past + nowcast сразу), метка Одессы, легенда dBZ.

   past  — последние ~2 часа реальных наблюдений радара (шаг 10 мин)
   nowcast — экстраполяция RainViewer на ~1 час вперёд (тоже их расчёт,
             не наш) — помечается пунктирной подписью "прогноз"

   ToS RainViewer: атрибуция "Weather data by RainViewer" есть в HTML
   статично (#radarAttribution) — не убирать.
========================================================= */

const RADAR_TILE_SIZE = window.devicePixelRatio >= 2 ? 512 : 256;
const RADAR_OPACITY = 0.75;
const ANIMATION_DELAY_MS = 600;
const API_URL = "https://api.rainviewer.com/public/weather-maps.json";

const CENTER_LAT = 46.4406;
const CENTER_LON = 30.7703;

let mapFrames = [];       // past + nowcast вместе
let pastCount = 0;        // индекс последнего "past"-кадра (== "сейчас")
let animationPosition = 0;
let animationTimer = false;
let currentLayer = null;
let isLoading = false;
let layerCache = {};

const map = L.map("mapid", { maxZoom: 12, attributionControl: true })
    .setView([CENTER_LAT, CENTER_LON], 7);

L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: '&copy; <a href="https://openstreetmap.org">OpenStreetMap</a> contributors',
    subdomains: "abc",
}).addTo(map);

L.marker([CENTER_LAT, CENTER_LON])
    .addTo(map)
    .bindPopup("Одесса (СИНОП 33837)");

function wrapPosition(pos){
    if(!mapFrames.length) return 0;
    while(pos >= mapFrames.length) pos -= mapFrames.length;
    while(pos < 0) pos += mapFrames.length;
    return pos;
}

function formatFrameLabel(frame, index){
    const t = new Date(frame.time * 1000).toLocaleTimeString("ru-RU", { hour:"2-digit", minute:"2-digit" });
    return index > pastCount ? `${t} (прогноз)` : (index === pastCount ? `${t} · сейчас` : t);
}

function createRadarLayer(frame){
    return new L.TileLayer(
        `${apiData.host}${frame.path}/${RADAR_TILE_SIZE}/{z}/{x}/{y}/2/0_0.png`,
        { tileSize: 256, opacity: 0.001, maxNativeZoom: 7, maxZoom: 12 }
    );
}

function clearLayerCache(){
    stopAnim();
    for(const pos in layerCache){
        if(parseInt(pos) !== animationPosition){
            map.removeLayer(layerCache[pos]);
            delete layerCache[pos];
        }
    }
}

function stopAnim(){
    if(animationTimer){
        clearTimeout(animationTimer);
        animationTimer = false;
        document.getElementById("radarPlayBtn").textContent = "▶";
        return true;
    }
    return false;
}

function playAnim(){
    animationTimer = true;
    document.getElementById("radarPlayBtn").textContent = "⏸";
    showFrame(animationPosition + 1);
}

function playStop(){
    if(!stopAnim()) playAnim();
}

function updateUI(frame, position){
    document.getElementById("radarTimestamp").textContent = formatFrameLabel(frame, position);
    const slider = document.getElementById("radarSlider");
    if(slider) slider.value = position;
}

function showFrame(position){
    if(isLoading || !mapFrames.length) return;
    position = wrapPosition(position);
    const frame = mapFrames[position];
    updateUI(frame, position);

    const oldLayer = currentLayer;
    if(layerCache[position]){
        if(oldLayer) oldLayer.setOpacity(0);
        layerCache[position].setOpacity(RADAR_OPACITY);
        currentLayer = layerCache[position];
        animationPosition = position;
        if(animationTimer) animationTimer = setTimeout(playAnim, ANIMATION_DELAY_MS);
        return;
    }

    isLoading = true;
    const newLayer = createRadarLayer(frame);
    newLayer.on("load", () => {
        newLayer.setOpacity(RADAR_OPACITY);
        if(oldLayer) oldLayer.setOpacity(0);
        layerCache[position] = newLayer;
        currentLayer = newLayer;
        animationPosition = position;
        isLoading = false;
        if(animationTimer) animationTimer = setTimeout(playAnim, ANIMATION_DELAY_MS);
    });
    newLayer.addTo(map);
}

let apiData = {};

function initFrames(api){
    clearLayerCache();
    currentLayer = null;
    mapFrames = [];
    animationPosition = 0;

    const past = (api.radar && api.radar.past) || [];
    const nowcast = (api.radar && api.radar.nowcast) || [];
    if(!past.length) return;

    mapFrames = past.concat(nowcast);
    pastCount = past.length - 1;

    const slider = document.getElementById("radarSlider");
    if(slider){
        slider.min = 0;
        slider.max = mapFrames.length - 1;
        slider.value = pastCount;
    }
    showFrame(pastCount); // старт на "сейчас"
}

function loadApiData(){
    fetch(API_URL, { cache: "no-store" })
        .then(r => r.json())
        .then(json => { apiData = json; initFrames(json); })
        .catch(e => {
            document.getElementById("radarTimestamp").textContent = "Ошибка загрузки радара";
            console.warn("RainViewer API:", e);
        });
}

/* Управление */
document.getElementById("radarPrevBtn").addEventListener("click", () => { stopAnim(); showFrame(animationPosition - 1); });
document.getElementById("radarNextBtn").addEventListener("click", () => { stopAnim(); showFrame(animationPosition + 1); });
document.getElementById("radarPlayBtn").addEventListener("click", playStop);
document.getElementById("radarSlider").addEventListener("input", (e) => {
    stopAnim();
    showFrame(parseInt(e.target.value, 10));
});

map.on("movestart", clearLayerCache);

loadApiData();
// автообновление списка кадров раз в 10 минут (radar.past/nowcast обновляются на сервере RainViewer)
setInterval(loadApiData, 10 * 60000);
