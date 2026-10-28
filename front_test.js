// front_test.js — тестовая страница ICON-EU изобары + P_front, три тира
// (near / far / very_far). Читает data/icon_front_<tier>/manifest.json и
// latest_log.txt. Ничего не пишет, ничего не триггерит — генерация идёт
// по cron на VPS (раз в час в :06).
// Добавлено: анимация по кадрам манифеста, слои включаются отдельно,
// слой «Контуры» (береговая линия + границы + города, data/basemap_europe.json,
// проекция CRS:84 — линейно по bbox снимка, как у GeoColour).

const IFVF_TIERS = {
    near:     { dir: "data/icon_front_near/",     label: "Центральный тайл" },
    far:      { dir: "data/icon_front_far/",      label: "Дальний (~1000км)" },
    very_far: { dir: "data/icon_front_very_far/", label: "Very far" },
};

// слои-картинки; контуры (canvas) обрабатываются отдельно
const IFVF_LAYERS = [
    { key: "geocolour", img: "ifvfGeocolour", chk: "ifvfChkGeocolour" },
    { key: "ir",        img: "ifvfIr",        chk: "ifvfChkIr" },
    { key: "pfront",    img: "ifvfPfront",    chk: "ifvfChkPfront" },
    { key: "isobars",   img: "ifvfIsobars",   chk: "ifvfChkIsobars" },
    { key: "fronts",    img: "ifvfFronts",    chk: "ifvfChkFronts" },
];

let ifvfTier = "very_far";
try {
    const saved = localStorage.getItem("ifvfTier");
    if (saved && IFVF_TIERS[saved]) ifvfTier = saved;
} catch (e) { /* localStorage может быть недоступен — не критично */ }

let ifvfManifest = null;
let ifvfSelectedIdx = -1;
let ifvfSelectedValid = null;   // valid_time выбранного кадра (индексы сдвигаются, когда старые кадры удаляются)
let ifvfToken = 0;              // «последний показ выигрывает»
let ifvfPlaying = false;
let ifvfLoadingFrames = false;
let ifvfCancelLoad = false;
let ifvfTimer = null;
const ifvfWarm = new Set();     // URL, уже подтянутые в HTTP-кеш
let ifvfBasemapData = null;
let ifvfBasemapKey = "";

function ifvfBase() { return IFVF_TIERS[ifvfTier].dir; }
function ifvfEl(id) { return document.getElementById(id); }
function ifvfChecked(id) { const e = ifvfEl(id); return !!(e && e.checked); }

function ifvfFormatTime(iso) {
    try {
        const d = new Date(iso);
        return d.toLocaleString("ru-RU", { timeZone: "Europe/Kiev", hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit" }) + " (Киев)";
    } catch (e) {
        return iso;
    }
}

function ifvfShortLabel(iso) {
    try {
        const d = new Date(iso);
        return d.toLocaleString("ru-RU", { timeZone: "Europe/Kiev", day: "2-digit", month: "2-digit" }) +
               " " + d.toLocaleString("ru-RU", { timeZone: "Europe/Kiev", hour: "2-digit", minute: "2-digit" });
    } catch (e) {
        return iso;
    }
}

function ifvfAgoMinutes(iso) {
    const diffMs = Date.now() - new Date(iso).getTime();
    return Math.round(diffMs / 60000);
}

function ifvfUrl(snap, key) {
    const fn = snap.files && snap.files[key];
    if (!fn) return null;
    return ifvfBase() + fn + "?v=" + encodeURIComponent(snap.generated_at_utc);
}

function ifvfDecode(url) {
    return new Promise((resolve) => {
        const im = new Image();
        im.onerror = () => resolve(false);
        im.src = url;
        if (im.decode) im.decode().then(() => resolve(true), () => resolve(false));
        else im.onload = () => resolve(true);
    });
}

// ---------- вкладки тиров ----------

function ifvfBuildTierTabs() {
    const wrap = ifvfEl("ifvfTierTabs");
    wrap.innerHTML = "";
    Object.keys(IFVF_TIERS).forEach((key) => {
        const btn = document.createElement("button");
        btn.textContent = IFVF_TIERS[key].label;
        btn.style.cssText = "margin:2px;padding:8px 12px;border-radius:6px;border:1px solid #444;color:#eee;font-size:13px;";
        btn.style.background = (key === ifvfTier) ? "#2a5d8f" : "#222";
        btn.onclick = () => {
            ifvfStop();
            ifvfToken++;
            ifvfTier = key;
            ifvfSelectedIdx = -1;
            ifvfSelectedValid = null;
            ifvfManifest = null;
            ifvfBasemapKey = "";
            try { localStorage.setItem("ifvfTier", key); } catch (e) {}
            ifvfBuildTierTabs();
            ifvfEl("ifvfMeta").textContent = "Загрузка...";
            ifvfEl("ifvfLog").textContent = "—";
            ifvfEl("ifvfSnapButtons").innerHTML = "";
            ifvfEl("ifvfPreloadStatus").textContent = "";
            loadIconFrontVeryFar();
        };
        wrap.appendChild(btn);
    });
}

// ---------- контуры (canvas) ----------

async function ifvfLoadBasemap() {
    if (ifvfBasemapData) return ifvfBasemapData;
    try {
        const res = await fetch("data/basemap_europe.json");
        if (!res.ok) throw new Error(res.status);
        ifvfBasemapData = await res.json();
    } catch (e) {
        ifvfBasemapData = { coast: [], borders: [], cities: [] };
    }
    return ifvfBasemapData;
}

async function ifvfDrawBasemap(snap, force) {
    const cv = ifvfEl("ifvfBasemap");
    if (!cv || !snap) return;
    const data = await ifvfLoadBasemap();
    const [w, s, e, n] = snap.bbox;
    const W = snap.width, H = snap.height;
    const cssW = cv.clientWidth || 360;
    const showCities = ifvfChecked("ifvfChkCities");
    const key = [ifvfTier, W, H, Math.round(cssW), showCities].join("|");
    if (!force && key === ifvfBasemapKey) return;
    ifvfBasemapKey = key;

    cv.width = W; cv.height = H;
    const ctx = cv.getContext("2d");
    ctx.clearRect(0, 0, W, H);
    const k = cssW / W;                       // canvas-px -> CSS-px
    const X = (lon) => (lon - w) / (e - w) * W;
    const Y = (lat) => (n - lat) / (n - s) * H;

    function strokeLines(lines, halo, main, haloW, mainW, dash) {
        for (const pass of [0, 1]) {
            ctx.beginPath();
            for (const ln of lines) {
                let started = false;
                for (const p of ln) {
                    if (p[0] < w - 1 || p[0] > e + 1 || p[1] < s - 1 || p[1] > n + 1) { started = false; continue; }
                    const x = X(p[0]), y = Y(p[1]);
                    if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y);
                }
            }
            ctx.lineJoin = "round"; ctx.lineCap = "round";
            ctx.setLineDash(pass === 1 && dash ? dash.map(v => v / k) : []);
            ctx.strokeStyle = pass === 0 ? halo : main;
            ctx.lineWidth = (pass === 0 ? haloW : mainW) / k;
            ctx.stroke();
        }
        ctx.setLineDash([]);
    }
    strokeLines(data.borders, "rgba(0,0,0,0.40)", "rgba(255,150,40,0.90)", 2.2, 1.0, [5, 3]);
    strokeLines(data.coast,   "rgba(0,0,0,0.55)", "rgba(255,225,60,0.95)", 2.6, 1.2, null);

    if (!showCities) return;
    const placed = [];
    const font = Math.round(12 / k * 10) / 10;
    ctx.font = `${font}px sans-serif`;
    ctx.textBaseline = "middle";
    const maxLevel = (ifvfTier === "near") ? 2 : 1;
    const cities = data.cities.filter(c => c[3] <= maxLevel &&
        c[1] > w && c[1] < e && c[2] > s && c[2] < n).sort((a, b) => a[3] - b[3]);
    for (const [name, lon, lat, lvl] of cities) {
        const x = X(lon), y = Y(lat), r = (lvl === 0 ? 4 : 2.6) / k;
        ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2);
        ctx.fillStyle = lvl === 0 ? "#ff3b30" : "#ffffff"; ctx.fill();
        ctx.lineWidth = 1.2 / k; ctx.strokeStyle = "#000"; ctx.stroke();
        const tw = ctx.measureText(name).width, th = font;
        const right = (x + r + 3 / k + tw) < W - 2 / k;
        const lx = right ? x + r + 3 / k : x - r - 3 / k - tw;
        const box = [lx, y - th / 2, lx + tw, y + th / 2];
        if (lvl > 0 && placed.some(b => !(box[2] < b[0] || box[0] > b[2] || box[3] < b[1] || box[1] > b[3]))) continue;
        placed.push(box);
        ctx.textAlign = "left";
        ctx.lineWidth = 3 / k; ctx.strokeStyle = "rgba(0,0,0,0.85)"; ctx.strokeText(name, lx, y);
        ctx.fillStyle = lvl === 0 ? "#ffb4ae" : "#fff"; ctx.fillText(name, lx, y);
    }
}

// ---------- показ кадра ----------

function ifvfMetaHtml(snap) {
    let eumetsatNote = "";
    if (snap.eumetsat_actual_time && new Date(snap.eumetsat_actual_time).getTime() !== new Date(snap.valid_time).getTime()) {
        eumetsatNote = `<br><span style="color:#f0ad4e;">⚠ EUMETSAT: точного кадра на ${ifvfFormatTime(snap.valid_time)} не было, показан ближайший (${ifvfFormatTime(snap.eumetsat_actual_time)})</span>`;
    }
    const dl = (snap.downloaded_mb !== undefined) ? ` &nbsp; <b>Скачано:</b> ${snap.downloaded_mb} МБ` : "";
    if (ifvfChecked("ifvfChkIr") && !(snap.files && snap.files.ir)) {
        eumetsatNote += `<br><span style="color:#f0ad4e;">⚠ ИК для этого кадра нет (слой добавлен 28.10, старые кадры без него)</span>`;
    }
    return `<b>${IFVF_TIERS[ifvfTier].label}</b><br>` +
        `<b>Valid time:</b> ${ifvfFormatTime(snap.valid_time)} &nbsp;` +
        `<b>Сгенерировано:</b> ${ifvfFormatTime(snap.generated_at_utc)} (${ifvfAgoMinutes(snap.generated_at_utc)} мин назад)<br>` +
        `<b>Run:</b> ICON-EU ${snap.run}, lead +${snap.lead_hours}ч` + dl + ` &nbsp; ` +
        `<b>P_front mean/max:</b> ${snap.pfront_mean.toFixed(3)} / ${snap.pfront_max.toFixed(3)}` +
        eumetsatNote;
}

function ifvfFrameLabelHtml(snaps, idx) {
    const snap = snaps[idx];
    let gap = "";
    if (idx > 0) {
        const h = (new Date(snap.valid_time) - new Date(snaps[idx - 1].valid_time)) / 3600000;
        if (h > 1.01) gap = ` <span style="color:#f0ad4e;">(пропуск ${Math.round(h - 1)} ч до этого)</span>`;
    }
    return `<b>${ifvfShortLabel(snap.valid_time)}</b> · кадр ${idx + 1}/${snaps.length}${gap}`;
}

async function ifvfRenderSnapshot(idx) {
    if (!ifvfManifest || !ifvfManifest.snapshots || !ifvfManifest.snapshots.length) return;
    const snaps = ifvfManifest.snapshots;
    idx = Math.max(0, Math.min(idx, snaps.length - 1));
    ifvfSelectedIdx = idx;
    ifvfSelectedValid = snaps[idx].valid_time;
    const snap = snaps[idx];
    const token = ++ifvfToken;

    const sl = ifvfEl("ifvfSlider");
    sl.max = snaps.length - 1; sl.value = idx;
    ifvfEl("ifvfFrameLabel").innerHTML = ifvfFrameLabelHtml(snaps, idx);
    document.querySelectorAll(".ifvfSnapBtn").forEach((btn, i) => {
        btn.style.background = (i === idx) ? "#2a5d8f" : "#222";
    });

    // декодируем новые картинки заранее и подменяем все слои в один момент — без мерцания
    const need = IFVF_LAYERS.filter(l => ifvfChecked(l.chk) && snap.files[l.key]);
    await Promise.all(need.map(l => ifvfDecode(ifvfUrl(snap, l.key))));
    if (token !== ifvfToken) return;     // уже показан более новый выбор

    ifvfEl("ifvfWrap").style.aspectRatio = `${snap.width} / ${snap.height}`;
    for (const l of IFVF_LAYERS) {
        const img = ifvfEl(l.img);
        const url = snap.files[l.key] ? ifvfUrl(snap, l.key) : null;
        if (ifvfChecked(l.chk) && url) {
            if (img.getAttribute("src") !== url) img.src = url;
            img.style.display = "block";
        } else {
            img.style.display = "none";
            if (!url) img.removeAttribute("src");   // у кадра нет такого слоя (напр. fronts в старых)
        }
    }
    ifvfEl("ifvfBasemap").style.display = ifvfChecked("ifvfChkBase") ? "block" : "none";
    ifvfDrawBasemap(snap, false);
    ifvfEl("ifvfMeta").innerHTML = ifvfMetaHtml(snap);
}

function ifvfBuildSnapshotButtons() {
    const wrap = ifvfEl("ifvfSnapButtons");
    wrap.innerHTML = "";
    ifvfManifest.snapshots.forEach((snap, i) => {
        const btn = document.createElement("button");
        btn.className = "ifvfSnapBtn";
        btn.textContent = ifvfShortLabel(snap.valid_time);
        btn.style.cssText = "width:auto;margin:2px;padding:6px 10px;border-radius:6px;border:1px solid #444;color:#eee;font-size:12px;";
        btn.onclick = () => { ifvfStop(); ifvfRenderSnapshot(i); };
        wrap.appendChild(btn);
    });
}

function ifvfToggleLayer(layerId, checkboxId) {
    // картинка слоя подгружается только когда слой включён (P_front ~1 МБ — не тянем зря)
    if (ifvfManifest && ifvfSelectedIdx >= 0) ifvfRenderSnapshot(ifvfSelectedIdx);
    else ifvfEl(layerId).style.display = ifvfChecked(checkboxId) ? "block" : "none";
    if (ifvfPlaying && ifvfChecked(checkboxId)) ifvfPreloadAll(true);
}

// GeoColour и ИК — взаимоисключающие подложки (обе непрозрачные): включили одну — другая гасится
function ifvfToggleSat(which) {
    const me = which === "ir" ? "ifvfChkIr" : "ifvfChkGeocolour";
    const other = which === "ir" ? "ifvfChkGeocolour" : "ifvfChkIr";
    if (ifvfChecked(me)) ifvfEl(other).checked = false;
    ifvfToggleLayer(which === "ir" ? "ifvfIr" : "ifvfGeocolour", me);
}

function ifvfToggleBase() {
    ifvfEl("ifvfBasemap").style.display = ifvfChecked("ifvfChkBase") ? "block" : "none";
}

function ifvfToggleCities() {
    if (ifvfManifest && ifvfManifest.snapshots.length) {
        const snaps = ifvfManifest.snapshots;
        ifvfDrawBasemap(snaps[Math.max(0, ifvfSelectedIdx)] || snaps[snaps.length - 1], true);
    }
}

// ---------- анимация ----------

function ifvfSetPlayButton() {
    const b = ifvfEl("ifvfPlay");
    if (ifvfLoadingFrames) b.textContent = "⏳ Стоп";
    else b.textContent = ifvfPlaying ? "⏸ Пауза" : "▶ Анимация";
}

// подтягивает в HTTP-кеш все кадры включённых слоёв (по 4 параллельно)
async function ifvfPreloadAll(background) {
    if (!ifvfManifest) return;
    const tierAtStart = ifvfTier;
    const jobs = [];
    for (const snap of ifvfManifest.snapshots) {
        for (const l of IFVF_LAYERS) {
            if (!ifvfChecked(l.chk)) continue;
            const url = ifvfUrl(snap, l.key);
            if (url && !ifvfWarm.has(url)) jobs.push(url);
        }
    }
    if (!jobs.length) return;
    const total = jobs.length;
    let done = 0;
    if (!background) { ifvfLoadingFrames = true; ifvfCancelLoad = false; ifvfSetPlayButton(); }
    const status = ifvfEl("ifvfPreloadStatus");
    async function worker() {
        while (jobs.length && !ifvfCancelLoad && tierAtStart === ifvfTier) {
            const url = jobs.shift();
            await ifvfDecode(url);
            ifvfWarm.add(url);
            done++;
            status.textContent = `Загрузка кадров: ${done}/${total}`;
        }
    }
    await Promise.all([worker(), worker(), worker(), worker()]);
    status.textContent = (ifvfCancelLoad || tierAtStart !== ifvfTier) ? "" : "Кадры загружены (в кеше браузера)";
    if (!background) { ifvfLoadingFrames = false; ifvfSetPlayButton(); }
}

function ifvfStop() {
    ifvfPlaying = false;
    ifvfCancelLoad = true;
    if (ifvfTimer) { clearTimeout(ifvfTimer); ifvfTimer = null; }
    ifvfSetPlayButton();
}

function ifvfFrameDelay() {
    const sp = parseFloat(ifvfEl("ifvfSpeed").value) || 1;
    return 700 / sp;
}

async function ifvfLoopStep() {
    if (!ifvfPlaying || !ifvfManifest) return;
    const n = ifvfManifest.snapshots.length;
    await ifvfRenderSnapshot(ifvfSelectedIdx);
    if (!ifvfPlaying) return;
    const atLast = ifvfSelectedIdx >= n - 1;
    ifvfTimer = setTimeout(() => {
        if (!ifvfPlaying || !ifvfManifest) return;
        const nn = ifvfManifest.snapshots.length;
        ifvfSelectedIdx = (ifvfSelectedIdx + 1) % nn;
        ifvfLoopStep();
    }, ifvfFrameDelay() + (atLast ? 1200 : 0));
}

async function ifvfTogglePlay() {
    if (ifvfLoadingFrames) { ifvfStop(); return; }          // отмена загрузки
    if (ifvfPlaying) { ifvfStop(); return; }
    if (!ifvfManifest || ifvfManifest.snapshots.length < 2) {
        ifvfEl("ifvfPreloadStatus").textContent = "Для анимации нужно минимум 2 кадра";
        return;
    }
    ifvfCancelLoad = false;
    await ifvfPreloadAll(false);
    if (ifvfCancelLoad) return;
    ifvfPlaying = true;
    ifvfSetPlayButton();
    if (ifvfSelectedIdx >= ifvfManifest.snapshots.length - 1) ifvfSelectedIdx = 0;
    ifvfLoopStep();
}

function ifvfStep(delta) {
    if (!ifvfManifest) return;
    ifvfStop();
    const n = ifvfManifest.snapshots.length;
    ifvfRenderSnapshot((Math.max(0, ifvfSelectedIdx) + delta + n) % n);
}

function ifvfOnSlider(v) {
    ifvfStop();
    ifvfRenderSnapshot(parseInt(v, 10) || 0);
}

function ifvfInitUi() {
    ifvfEl("ifvfSlider").addEventListener("input", (e) => ifvfOnSlider(e.target.value));
    document.addEventListener("visibilitychange", () => { if (document.hidden) ifvfStop(); });
    if (window.ResizeObserver) {
        let raf = 0;
        new ResizeObserver(() => {
            cancelAnimationFrame(raf);
            raf = requestAnimationFrame(() => {
                if (ifvfManifest && ifvfManifest.snapshots.length) {
                    const snaps = ifvfManifest.snapshots;
                    ifvfDrawBasemap(snaps[Math.max(0, ifvfSelectedIdx)] || snaps[snaps.length - 1], false);
                }
            });
        }).observe(ifvfEl("ifvfWrap"));
    }
    ifvfSetPlayButton();
}

// ---------- загрузка манифеста ----------

async function loadIconFrontVeryFar() {
    const base = ifvfBase();
    const tierAtStart = ifvfTier;
    try {
        const res = await fetch(base + "manifest.json?_=" + Date.now());
        if (!res.ok) throw new Error("manifest.json недоступен (" + res.status + ")");
        const m = await res.json();
        if (tierAtStart !== ifvfTier) return; // пользователь уже переключил вкладку
        const wasLast = ifvfManifest && ifvfSelectedIdx >= ifvfManifest.snapshots.length - 1;
        ifvfManifest = m;
        if (!ifvfManifest.snapshots || !ifvfManifest.snapshots.length) {
            ifvfEl("ifvfMeta").textContent = "Пока нет ни одного снимка для этого тира — ждём первый прогон cron (раз в час, в :06).";
            return;
        }
        const snaps = ifvfManifest.snapshots;
        ifvfBuildSnapshotButtons();
        // выбранный кадр ищем по valid_time; если на последнем — «едем» за новым
        let idx = snaps.length - 1;
        if (ifvfSelectedValid && !wasLast) {
            const f = snaps.findIndex(s => s.valid_time === ifvfSelectedValid);
            if (f >= 0) idx = f;
        }
        if (ifvfPlaying) {
            // не прерываем анимацию: обновляем только границы слайдера и индекс
            ifvfEl("ifvfSlider").max = snaps.length - 1;
            ifvfSelectedIdx = Math.min(ifvfSelectedIdx, snaps.length - 1);
        } else {
            ifvfRenderSnapshot(idx);
        }
    } catch (e) {
        if (tierAtStart === ifvfTier) {
            ifvfEl("ifvfMeta").textContent = "Ошибка загрузки: " + e.message;
        }
    }

    try {
        const logRes = await fetch(base + "latest_log.txt?_=" + Date.now());
        if (logRes.ok && tierAtStart === ifvfTier) {
            ifvfEl("ifvfLog").textContent = await logRes.text();
        }
    } catch (e) {
        // лог необязателен
    }
}
