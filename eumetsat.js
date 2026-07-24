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
     msg_fes:h60b   — Blended SEVIRI/LEO MW precipitation (осадки) —
                      мгновенная интенсивность осадков, комбинация IR
                      геостационара с калибровкой по MW-измерениям LEO
                      спутников. Обновление раз в 15 мин.
     msg_fes:gii_kindex — GII K-Index (индекс грозовой неустойчивости
                      воздушной массы, только для безоблачных участков).
                      Прокси для потенциала гроз в дополнение к li_afa
                      (реальные молнии). Обновление раз в 15 мин.
     mtg_fd:rgb_geocolour — GeoColour RGB (MTG, полный диск, 0°) —
                      натуральный цвет со спутника (то же самое, что
                      показывает официальный EUMETView, "GeoColour RGB").
                      Обновление раз в 10 мин.

   ЛЕГЕНДА: GetLegendGraphic у этого WMS для mosaic-слоёв (clm/cth/h60b/
   gii_kindex/li_afa) НЕ работает надёжно — сервер у части таких слоёв
   отдаёт вместо PNG текст ошибки/XML (подтверждено на аналогичных слоях
   этого же GeoServer). Поэтому легенда здесь — наш собственный статичный
   HTML (LEGEND_HTML ниже), не запрос к серверу: для clm — точные анкеры
   цвета (см. eumetsat_point.py), для остальных — честное качественное
   описание без выдуманных калиброванных чисел.

   ПРИМЕЧАНИЕ: отдельного продукта "тип облаков" (низкая/средняя/высокая
   облачность и т.п.) у EUMETView WMS нет — есть только Cloud Mask (clm,
   ясно/облачно) и Cloud Top Height (cth, высота верхней границы),
   которые вместе и являются ближайшей доступной альтернативой.

   ВАЖНО: эти слои отдаются WMS только в EPSG:4326 (не EPSG:3857) — для
   каждого TileLayer.WMS указан crs: L.CRS.EPSG4326, базовая карта (OSM)
   остаётся в обычной проекции, Leaflet сам делает трансформацию per-tile.
========================================================= */

const WMS_BASE = "https://view.eumetsat.int/geoserver/wms";
const CENTER_LAT = 46.4406;
const CENTER_LON = 30.7703;

const LEGEND_HTML = {
    clm: `
        <div class="swatchRow"><span class="swatch" style="background:rgb(0,0,255);"></span>ясно (над водой)</div>
        <div class="swatchRow"><span class="swatch" style="background:rgb(0,170,0);"></span>ясно (над сушей)</div>
        <div class="swatchRow"><span class="swatch" style="background:rgb(255,255,255);"></span>облачно</div>`,
    cth: `
        <div class="gradBar" style="background:linear-gradient(90deg,#3355ff,#33cc66,#eeee33,#ff6633,#cc2222);"></div>
        <div>цвет ≈ позиция на шкале высоты верхней границы облака (точной шкалы в метрах нет)</div>`,
    h60b: `
        <div class="swatchRow"><span class="swatch" style="background:transparent;border-style:dashed;"></span>прозрачно = осадков нет</div>
        <div>цвет = осадки есть, оттенок ≈ интенсивность (калиброванной шкалы мм/ч нет)</div>`,
    gii_kindex: `
        <div class="gradBar" style="background:linear-gradient(90deg,#3355ff,#eeee33,#ff3322);"></div>
        <div>цвет ≈ индекс грозовой неустойчивости воздушной массы (K-Index), только над безоблачными участками</div>`,
    li_afa: `
        <div class="swatchRow"><span class="swatch" style="background:transparent;border-style:dashed;"></span>прозрачно = молний за 5 мин нет</div>
        <div>цвет = накопленная площадь вспышек, оттенок ≈ плотность (без калиброванного числа вспышек)</div>`,
    geocolour: `<div>натуральный цвет со спутника (как на официальном EUMETView), не тематическая карта</div>`,
};

const LAYERS = {
    clm: {
        name: "msg_fes:clm",
        stepMinutes: 15,
    },
    cth: {
        name: "msg_fes:cth",
        stepMinutes: 15,
    },
    h60b: {
        name: "msg_fes:h60b",
        stepMinutes: 15,
    },
    gii_kindex: {
        name: "msg_fes:gii_kindex",
        stepMinutes: 15,
    },
    li_afa: {
        name: "mtg_fd:li_afa",
        stepMinutes: 5,
    },
    geocolour: {
        name: "mtg_fd:rgb_geocolour",
        stepMinutes: 10,
        opacity: 1.0,
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
    document.getElementById("eumLegendContent").innerHTML = LEGEND_HTML[key] || "";

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
            opacity: LAYERS[currentKey].opacity ?? 0.75,
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

/* =========================================================
   СРАВНЕНИЕ 2 ПОСЛЕДНИХ КАДРОВ — отдельная модалка с двумя мини-картами
   (текущий выбранный слой), созданными лениво при открытии и уничтожаемыми
   при закрытии, чтобы не держать лишние Leaflet-инстансы в фоне.
========================================================= */
let compareMapPrev = null;
let compareMapNow = null;

function _buildCompareMap(containerId, timeIso){
    const m = L.map(containerId, {
        maxZoom: 10, zoomControl: false, attributionControl: false,
        dragging: false, scrollWheelZoom: false, doubleClickZoom: false, boxZoom: false,
    }).setView([CENTER_LAT, CENTER_LON], 6);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { subdomains: "abc" }).addTo(m);
    L.marker([CENTER_LAT, CENTER_LON]).addTo(m);
    L.tileLayer.wms(WMS_BASE, {
        layers: LAYERS[currentKey].name,
        format: "image/png",
        transparent: true,
        version: "1.3.0",
        crs: L.CRS.EPSG4326,
        opacity: LAYERS[currentKey].opacity ?? 0.75,
        time: timeIso,
    }).addTo(m);
    return m;
}

function openCompareModal(){
    if(timeSteps.length < 2) return;
    stopAnim();
    const idxNow = timeSteps.length - 1;
    const idxPrev = timeSteps.length - 2;
    const dNow = timeSteps[idxNow];
    const dPrev = timeSteps[idxPrev];

    document.getElementById("eumCompareModal").classList.add("open");
    document.getElementById("eumCompareTitle").textContent =
        `Сравнение 2 последних снимков — ${document.querySelector("#eumLayerTabs button.active").textContent}`;
    document.getElementById("compareLabelPrev").textContent =
        dPrev.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
    document.getElementById("compareLabelNow").textContent =
        dNow.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" }) + " · сейчас";

    compareMapPrev = _buildCompareMap("compareMapPrev", isoNoMillis(dPrev));
    compareMapNow = _buildCompareMap("compareMapNow", isoNoMillis(dNow));
    // Leaflet считает размер контейнера в момент создания — модалка только
    // что стала видимой (display:flex), поэтому пересчитываем на следующий тик
    setTimeout(() => { compareMapPrev.invalidateSize(); compareMapNow.invalidateSize(); }, 50);
}

function closeCompareModal(){
    document.getElementById("eumCompareModal").classList.remove("open");
    if(compareMapPrev){ compareMapPrev.remove(); compareMapPrev = null; }
    if(compareMapNow){ compareMapNow.remove(); compareMapNow = null; }
}

document.getElementById("eumCompareBtn").addEventListener("click", openCompareModal);
document.getElementById("eumCompareCloseBtn").addEventListener("click", closeCompareModal);
