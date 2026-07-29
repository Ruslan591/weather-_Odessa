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
     mtg_fd:h40b    — то же самое (Blended FCI/LEO MW precipitation), но
                      MTG FCI вместо MSG SEVIRI — точнее и чаще (10 мин).
     msg_fes:gii_kindex — GII K-Index (индекс грозовой неустойчивости
                      воздушной массы, только для безоблачных участков).
                      Прокси для потенциала гроз в дополнение к li_afa
                      (реальные молнии). Обновление раз в 15 мин.
     mtg_fd:rgb_geocolour — GeoColour RGB (MTG, полный диск, 0°) —
                      натуральный цвет со спутника (то же самое, что
                      показывает официальный EUMETView, "GeoColour RGB").
                      Обновление раз в 10 мин.
     mtg_fd:ir105_hrfi — ИК-канал 10.5 мкм, MTG FCI HRFI (яркостная
                      температура верхней границы облака), 1км разрешение
                      в надире (точнее старого msg_fes:ir108 ~3км) — в
                      отличие от geocolour работает одинаково днём и ночью
                      (тепловое излучение, не отражённый свет; огней
                      городов на нём физически нет). Обновление раз в
                      10 мин. Нужен явный style (mtg_fd_ir105_hrfi_grayscale).
     mtg_fd:rgb_cloudtype — Cloud Type RGB (MTG) — различение типов
                      облаков (высокие толстые ледяные/средние ледяные/
                      тонкий перистый) через комбинацию NIR1.38+VIS0.64+
                      NIR1.6. РАБОТАЕТ ТОЛЬКО ДНЁМ (нужен отражённый
                      свет) — ночью недостоверно. Style "raster"
                      (дефолтный у GeoServer для этого слоя, без
                      namespace-префикса — подтверждено вручную через
                      GetCapabilities). Обновление раз в 10 мин.

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
    h40b: `
        <div class="swatchRow"><span class="swatch" style="background:transparent;border-style:dashed;"></span>прозрачно = осадков нет</div>
        <div>цвет = осадки есть, оттенок ≈ интенсивность (калиброванной шкалы мм/ч нет); MTG FCI — точнее и чаще (10 мин против 15 мин у msg_fes:h60b)</div>`,
    gii_kindex: `
        <div class="gradBar" style="background:linear-gradient(90deg,#3355ff,#eeee33,#ff3322);"></div>
        <div>цвет ≈ индекс грозовой неустойчивости воздушной массы (K-Index), только над безоблачными участками</div>`,
    li_afa: `
        <div class="swatchRow"><span class="swatch" style="background:transparent;border-style:dashed;"></span>прозрачно = молний за 5 мин нет</div>
        <div>цвет = накопленная площадь вспышек, оттенок ≈ плотность (без калиброванного числа вспышек)</div>`,
    geocolour: `<div>натуральный цвет со спутника (как на официальном EUMETView), не тематическая карта</div>`,
    ir108: `
        <div class="gradBar" style="background:linear-gradient(90deg,#111111,#666666,#cccccc,#ffffff);"></div>
        <div>яркостная температура верхней границы облака (10.5мкм, MTG FCI, 1км) — холоднее (выше облако) обычно светлее на этой шкале; точной шкалы в °C нет. Работает одинаково днём и ночью.</div>`,
    cloudtype: `
        <div>RGB-композит: различает типы облаков по текстуре/фазе (лёд/вода, тонкие/плотные). Официальной калиброванной шкалы нет.</div>
        <div style="margin-top:4px;"><b>Работает только днём</b> — ночью изображение недостоверно/чёрное.</div>`,
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
    h40b: {
        name: "mtg_fd:h40b",
        style: "mtg_fd:mtg_h40b_default",
        stepMinutes: 10,
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
    ir108: {
        name: "mtg_fd:ir105_hrfi",
        style: "mtg_fd:mtg_fd_ir105_hrfi_grayscale",
        stepMinutes: 10,
        opacity: 1.0,
    },
    cloudtype: {
        name: "mtg_fd:rgb_cloudtype",
        style: "raster",
        stepMinutes: 10,
        opacity: 1.0,
    },
};

let currentKey = "clm";
let layerA = null;
let layerB = null;
let activeIsA = true;    // какой из двух слоёв сейчас видим (opacity=target)
let frameToken = 0;      // счётчик поколений кадра — гасит устаревшие callback'и
                          // 'load' от быстрой перемотки/анимации/смены слоя
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

// ПОЧЕМУ ДВА ПОСТОЯННЫХ СЛОЯ, А НЕ add/remove НА КАЖДЫЙ КАДР:
// Раньше новый L.tileLayer.wms создавался заново на каждый кадр и добавлялся
// поверх старого, старый убирался по событию 'load' — но у Leaflet ЕЩЁ есть
// собственный per-tile fade-in (плавное нарастание opacity каждого <img>
// ПОСЛЕ события 'load' всего слоя), поэтому в момент удаления старого слоя
// новый мог быть ещё не полностью непрозрачным — отсюда мелькание базовой
// карты между кадрами. Теперь: два слоя добавлены на карту ОДИН РАЗ и больше
// никогда не удаляются — виден только "активный" (opacity=target), у
// неактивного opacity=0. Новый кадр грузится В НЕВИДИМЫЙ (opacity=0) слой
// через setParams({time}), и только когда он полностью загружен, слои
// меняются местами (мгновенный toggle opacity, а не add/remove DOM-узла) —
// базовая карта (OSM) вообще не участвует в этом процессе.
function buildLayerPair(key, timeIso){
    const opts = {
        layers: LAYERS[key].name,
        styles: LAYERS[key].style || "",
        format: "image/png",
        transparent: true,
        version: "1.3.0",
        crs: L.CRS.EPSG4326,
        opacity: 0,
        time: timeIso,
    };
    return [L.tileLayer.wms(WMS_BASE, opts), L.tileLayer.wms(WMS_BASE, opts)];
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

    // у нового ключа другой layers/styles — старую пару приходится
    // пересоздать (это редкое событие, смена вкладки, а не каждый тик
    // анимации, поэтому небольшой перерыв в отрисовке здесь не проблема)
    frameToken++;
    const myToken = frameToken;
    if(layerA){ map.removeLayer(layerA); }
    if(layerB){ map.removeLayer(layerB); }

    const timeIso = isoNoMillis(timeSteps[position]);
    const [la, lb] = buildLayerPair(key, timeIso);
    layerA = la;
    layerB = lb;
    layerA.addTo(map);
    layerB.addTo(map);
    activeIsA = true;

    const targetOpacity = LAYERS[key].opacity ?? 0.75;
    const reveal = () => {
        if(myToken !== frameToken) return; // сменили вкладку/кадр ещё раз, пока грузилось
        la.setOpacity(targetOpacity);
    };
    la.once("load", reveal);
    setTimeout(reveal, 4000); // подстраховка, если 'load' не пришёл

    updateTimestampLabel();
}

function renderCurrentFrame(){
    const timeIso = isoNoMillis(timeSteps[position]);
    updateTimestampLabel();

    const targetOpacity = LAYERS[currentKey].opacity ?? 0.75;
    const inactive = activeIsA ? layerB : layerA;
    const active = activeIsA ? layerA : layerB;

    const myToken = ++frameToken;
    inactive.setParams({ time: timeIso });

    const swapIn = () => {
        if(myToken !== frameToken) return; // устарело — уже перескочили на другой кадр
        inactive.setOpacity(targetOpacity);
        active.setOpacity(0);
        activeIsA = !activeIsA;
    };
    inactive.once("load", swapIn);
    // подстраховка: если 'load' почему-то не пришёл (например, ошибка
    // одного тайла) — не показывать старый кадр вечно
    setTimeout(swapIn, 4000);
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
