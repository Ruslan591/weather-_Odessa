// front_test.js — тестовая страница ICON-EU изобары + P_front, три тира
// (near / far / very_far). Читает data/icon_front_<tier>/manifest.json и
// latest_log.txt. Ничего не пишет, ничего не триггерит — генерация идёт
// по cron на VPS (раз в час в :06).

const IFVF_TIERS = {
    near:     { dir: "data/icon_front_near/",     label: "Центральный тайл" },
    far:      { dir: "data/icon_front_far/",      label: "Дальний (~1000км)" },
    very_far: { dir: "data/icon_front_very_far/", label: "Very far" },
};

let ifvfTier = "very_far";
try {
    const saved = localStorage.getItem("ifvfTier");
    if (saved && IFVF_TIERS[saved]) ifvfTier = saved;
} catch (e) { /* localStorage может быть недоступен — не критично */ }

let ifvfManifest = null;
let ifvfSelectedIdx = -1;

function ifvfBase() { return IFVF_TIERS[ifvfTier].dir; }

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

function ifvfBuildTierTabs() {
    const wrap = document.getElementById("ifvfTierTabs");
    wrap.innerHTML = "";
    Object.keys(IFVF_TIERS).forEach((key) => {
        const btn = document.createElement("button");
        btn.textContent = IFVF_TIERS[key].label;
        btn.style.cssText = "margin:2px;padding:8px 12px;border-radius:6px;border:1px solid #444;color:#eee;font-size:13px;";
        btn.style.background = (key === ifvfTier) ? "#2a5d8f" : "#222";
        btn.onclick = () => {
            ifvfTier = key;
            ifvfSelectedIdx = -1;
            ifvfManifest = null;
            try { localStorage.setItem("ifvfTier", key); } catch (e) {}
            ifvfBuildTierTabs();
            document.getElementById("ifvfMeta").textContent = "Загрузка...";
            document.getElementById("ifvfLog").textContent = "—";
            document.getElementById("ifvfSnapButtons").innerHTML = "";
            loadIconFrontVeryFar();
        };
        wrap.appendChild(btn);
    });
}

function ifvfRenderSnapshot(idx) {
    if (!ifvfManifest || !ifvfManifest.snapshots || !ifvfManifest.snapshots.length) return;
    const snaps = ifvfManifest.snapshots;
    idx = Math.max(0, Math.min(idx, snaps.length - 1));
    ifvfSelectedIdx = idx;
    const snap = snaps[idx];

    // пропорции контейнера — по фактическому размеру снимка этого тира
    document.getElementById("ifvfWrap").style.aspectRatio = `${snap.width} / ${snap.height}`;

    const base = ifvfBase();
    const bust = "?v=" + encodeURIComponent(snap.generated_at_utc);
    document.getElementById("ifvfGeocolour").src = base + snap.files.geocolour + bust;
    document.getElementById("ifvfIsobars").src = base + snap.files.isobars + bust;
    document.getElementById("ifvfPfront").src = base + snap.files.pfront + bust;

    let eumetsatNote = "";
    if (snap.eumetsat_actual_time && new Date(snap.eumetsat_actual_time).getTime() !== new Date(snap.valid_time).getTime()) {
        eumetsatNote = `<br><span style="color:#f0ad4e;">⚠ EUMETSAT: точного кадра на ${ifvfFormatTime(snap.valid_time)} не было, показан ближайший (${ifvfFormatTime(snap.eumetsat_actual_time)})</span>`;
    }
    const dl = (snap.downloaded_mb !== undefined) ? ` &nbsp; <b>Скачано:</b> ${snap.downloaded_mb} МБ` : "";
    document.getElementById("ifvfMeta").innerHTML =
        `<b>${IFVF_TIERS[ifvfTier].label}</b><br>` +
        `<b>Valid time:</b> ${ifvfFormatTime(snap.valid_time)} &nbsp;` +
        `<b>Сгенерировано:</b> ${ifvfFormatTime(snap.generated_at_utc)} (${ifvfAgoMinutes(snap.generated_at_utc)} мин назад)<br>` +
        `<b>Run:</b> ICON-EU ${snap.run}, lead +${snap.lead_hours}ч` + dl + ` &nbsp; ` +
        `<b>P_front mean/max:</b> ${snap.pfront_mean.toFixed(3)} / ${snap.pfront_max.toFixed(3)}` +
        eumetsatNote;

    document.querySelectorAll(".ifvfSnapBtn").forEach((btn, i) => {
        btn.style.background = (i === idx) ? "#2a5d8f" : "#222";
    });
}

function ifvfBuildSnapshotButtons() {
    const wrap = document.getElementById("ifvfSnapButtons");
    wrap.innerHTML = "";
    ifvfManifest.snapshots.forEach((snap, i) => {
        const btn = document.createElement("button");
        btn.className = "ifvfSnapBtn";
        btn.textContent = ifvfShortLabel(snap.valid_time);
        btn.style.cssText = "margin:2px;padding:6px 10px;border-radius:6px;border:1px solid #444;color:#eee;font-size:12px;";
        btn.onclick = () => ifvfRenderSnapshot(i);
        wrap.appendChild(btn);
    });
}

function ifvfToggleLayer(layerId, checkboxId) {
    const cb = document.getElementById(checkboxId);
    document.getElementById(layerId).style.display = cb.checked ? "block" : "none";
}

async function loadIconFrontVeryFar() {
    const base = ifvfBase();
    const tierAtStart = ifvfTier;
    try {
        const res = await fetch(base + "manifest.json?_=" + Date.now());
        if (!res.ok) throw new Error("manifest.json недоступен (" + res.status + ")");
        const m = await res.json();
        if (tierAtStart !== ifvfTier) return; // пользователь уже переключил вкладку
        ifvfManifest = m;
        if (!ifvfManifest.snapshots || !ifvfManifest.snapshots.length) {
            document.getElementById("ifvfMeta").textContent = "Пока нет ни одного снимка для этого тира — ждём первый прогон cron (раз в час, в :06).";
            return;
        }
        ifvfBuildSnapshotButtons();
        const lastIdx = ifvfManifest.snapshots.length - 1;
        if (ifvfSelectedIdx === -1) ifvfSelectedIdx = lastIdx;
        ifvfRenderSnapshot(Math.min(ifvfSelectedIdx, lastIdx));
    } catch (e) {
        if (tierAtStart === ifvfTier) {
            document.getElementById("ifvfMeta").textContent = "Ошибка загрузки: " + e.message;
        }
    }

    try {
        const logRes = await fetch(base + "latest_log.txt?_=" + Date.now());
        if (logRes.ok && tierAtStart === ifvfTier) {
            document.getElementById("ifvfLog").textContent = await logRes.text();
        }
    } catch (e) {
        // лог необязателен
    }
}
