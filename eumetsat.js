/* =========================================================
   EUMETSAT.JS — карта спутника EUMETSAT для eumetsat.html.

   АРХИТЕКТУРА (после переделки): раньше каждый слой анимировался ЖИВЫМИ
   WMS-тайлами прямо в Leaflet — на каждый кадр уходило НЕСКОЛЬКО отдельных
   GetMap-запросов (по тайлу стандартной XYZ-сетки), и если хоть один тайл
   не успевал/не мог загрузиться — в этом месте кадра было видно НАСКВОЗЬ
   базовую карту (см. обсуждение в чате). Патчи (двойной буфер с
   кроссфейдом, порог ошибок тайлов) снижали частоту, но не убирали
   проблему в принципе — слишком много точек отказа на клиенте.

   Теперь сервер (scripts/eumetsat_anim_render.py, GitHub Actions) сам
   собирает готовую MP4-петлю (последние ~2ч) ОДНИМ GetMap-запросом на
   кадр (не тайлами — цельным широким обзорным изображением), кодирует и
   кладёт ОДИН файл на слой в data/anim/<key>.mp4 (перезаписывается,
   история не копится). Здесь — просто L.videoOverlay поверх карты,
   привязанный к тем же географическим границам (ANIM_BOUNDS), что и
   рендерился на сервере. Ни одного сетевого запроса к EUMETSAT на клиенте
   — мерцать нечему, а base-карта (OSM) как отображалась статично, так и
   отображается (она и не была источником мерцания).

   Прозрачность: у видео (H.264) нет альфа-канала, поэтому сервер кладёт
   "нет данных" на сплошную тёмную подложку, а не на прозрачность — здесь
   компенсируется общей opacity слоя (видно карту сквозь видео равномерно,
   не только в no-data пятнах, это компромисс ради простоты и надёжности).
========================================================= */

const ANIM_BASE = "https://raw.githubusercontent.com/ruslan591/weather-_Odessa/main/data/anim";
const MANIFEST_URL = ANIM_BASE + "/manifest.json";
const CENTER_LAT = 46.4406;
const CENTER_LON = 30.7703;

// Тот же bbox, что в scripts/eumetsat_anim_render.py (BBOX) — если меняешь
// там, поменяй и здесь, иначе видео "уедет" от реальных координат на карте.
const ANIM_BOUNDS = [[43.5, 25.0], [50.5, 37.5]]; // [[lat_min,lon_min],[lat_max,lon_max]]

const LEGEND_HTML = {
    clm: `
        <div class="swatchRow"><span class="swatch" style="background:rgb(0,0,255);"></span>ясно (над водой)</div>
        <div class="swatchRow"><span class="swatch" style="background:rgb(0,170,0);"></span>ясно (над сушей)</div>
        <div class="swatchRow"><span class="swatch" style="background:rgb(255,255,255);"></span>облачно</div>`,
    cth: `
        <div class="gradBar" style="background:linear-gradient(90deg,#3355ff,#33cc66,#eeee33,#ff6633,#cc2222);"></div>
        <div>цвет ≈ позиция на шкале высоты верхней границы облака (точной шкалы в метрах нет)</div>`,
    h60b: `
        <div>тёмный фон = осадков нет</div>
        <div>цвет = осадки есть, оттенок ≈ интенсивность (калиброванной шкалы мм/ч нет)</div>`,
    h40b: `
        <div>тёмный фон = осадков нет</div>
        <div>цвет = осадки есть, оттенок ≈ интенсивность (калиброванной шкалы мм/ч нет); MTG FCI — точнее и чаще (10 мин против 15 мин у msg_fes:h60b)</div>`,
    gii_kindex: `
        <div class="gradBar" style="background:linear-gradient(90deg,#3355ff,#eeee33,#ff3322);"></div>
        <div>цвет ≈ индекс грозовой неустойчивости воздушной массы (K-Index), только над безоблачными участками</div>`,
    li_afa: `
        <div>тёмный фон = молний за 5 мин нет</div>
        <div>цвет = накопленная площадь вспышек, оттенок ≈ плотность (без калиброванного числа вспышек)</div>`,
    geocolour: `<div>натуральный цвет со спутника (как на официальном EUMETView), не тематическая карта</div>`,
    ir108: `
        <div class="gradBar" style="background:linear-gradient(90deg,#111111,#666666,#cccccc,#ffffff);"></div>
        <div>яркостная температура верхней границы облака (10.5мкм, MTG FCI, 1км) — холоднее (выше облако) обычно светлее на этой шкале; точной шкалы в °C нет. Работает одинаково днём и ночью.</div>`,
    cloudtype: `
        <div>RGB-композит: различает типы облаков по текстуре/фазе (лёд/вода, тонкие/плотные). Официальной калиброванной шкалы нет.</div>
        <div style="margin-top:4px;"><b>Работает только днём</b> — ночью изображение недостоверно/чёрное.</div>`,
    cloudphase: `
        <div>RGB-композит: фаза облаков — зелёный/жёлтый/белый ≈ водяные (низкие→плотные), голубой/синий ≈ ледяные (перистые/плотные), розовый ≈ смешанная фаза, красный/фиолетовый ≈ самые холодные ледяные верхушки (мощная конвекция/гроза). Официальной калиброванной шкалы нет.</div>
        <div style="margin-top:4px;"><b>Работает только днём</b> — ночью изображение недостоверно/чёрное.</div>`,
};

const LAYERS = {
    clm:        { opacity: 0.85 },
    cth:        { opacity: 0.85 },
    h60b:       { opacity: 0.85 },
    h40b:       { opacity: 0.85 },
    gii_kindex: { opacity: 0.85 },
    li_afa:     { opacity: 0.85 },
    geocolour:  { opacity: 1.0 },
    ir108:      { opacity: 1.0 },
    cloudtype:  { opacity: 1.0 },
    cloudphase: { opacity: 1.0 },
};

let currentKey = "clm";
let currentVideoOverlay = null;
let manifestData = {};

const map = L.map("mapid", { attributionControl: true });
map.fitBounds(ANIM_BOUNDS);

L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: '&copy; <a href="https://openstreetmap.org">OpenStreetMap</a> contributors',
    subdomains: "abc",
}).addTo(map);

L.marker([CENTER_LAT, CENTER_LON]).addTo(map).bindPopup("Одесса (СИНОП 33837)");

function updateTimestampLabel(key){
    const iso = manifestData[key];
    const el = document.getElementById("eumTimestamp");
    if(!iso){ el.textContent = "нет данных"; return; }
    const d = new Date(iso);
    const label = d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
    const ageMin = Math.round((Date.now() - d.getTime()) / 60000);
    el.textContent = ageMin < 1 ? `обновлено только что` : `обновлено ${label} (${ageMin} мин назад)`;
}

function setLayer(key){
    currentKey = key;
    document.querySelectorAll("#eumLayerTabs button").forEach(b => {
        b.classList.toggle("active", b.dataset.layer === key);
    });
    document.getElementById("eumLegendContent").innerHTML = LEGEND_HTML[key] || "";
    updateTimestampLabel(key);

    if(currentVideoOverlay){
        map.removeLayer(currentVideoOverlay);
        currentVideoOverlay = null;
    }

    const url = `${ANIM_BASE}/${key}.mp4?v=${Date.now()}`; // cache-bust: файл перезаписывается на месте
    const overlay = L.videoOverlay(url, ANIM_BOUNDS, {
        opacity: LAYERS[key].opacity ?? 0.85,
        interactive: false,
    });
    overlay.addTo(map);
    currentVideoOverlay = overlay;

    const videoEl = overlay.getElement();
    if(videoEl){
        videoEl.muted = true;
        videoEl.loop = true;
        videoEl.playsInline = true;
        videoEl.controls = true; // нативный плеер — play/pause/перемотка
        videoEl.autoplay = true;
        videoEl.play().catch(() => {}); // автоплей может требовать жеста на некоторых браузерах — не критично, controls всё равно есть
        videoEl.onerror = () => {
            document.getElementById("eumTimestamp").textContent = "видео недоступно (ещё не сгенерировано?)";
        };
    }
}

async function loadManifest(){
    try {
        const r = await fetch(MANIFEST_URL, { cache: "no-store" });
        if(r.ok) manifestData = await r.json();
    } catch(e){
        manifestData = {};
    }
    updateTimestampLabel(currentKey);
}

document.querySelectorAll("#eumLayerTabs button").forEach(btn => {
    btn.addEventListener("click", () => setLayer(btn.dataset.layer));
});

loadManifest().then(() => setLayer("clm"));
setInterval(async () => {
    await loadManifest();
    setLayer(currentKey); // подхватить свежую петлю, если manifest обновился
}, 5 * 60000);
