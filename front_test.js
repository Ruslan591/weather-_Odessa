// front_test.js — тестовая страница ICON-EU изобары + P_front (very_far)
// Читает только data/icon_front_very_far/manifest.json и latest_log.txt.
// Ничего не пишет, ничего не триггерит — генерация идёт по cron на VPS.

const IFVF_BASE = "data/icon_front_very_far/";

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

let ifvfManifest = null;
let ifvfSelectedIdx = -1;

function ifvfRenderSnapshot(idx) {
    if (!ifvfManifest || !ifvfManifest.snapshots || !ifvfManifest.snapshots.length) return;
    const snaps = ifvfManifest.snapshots;
    idx = Math.max(0, Math.min(idx, snaps.length - 1));
    ifvfSelectedIdx = idx;
    const snap = snaps[idx];

    const bust = "?v=" + encodeURIComponent(snap.generated_at_utc);
    document.getElementById("ifvfGeocolour").src = IFVF_BASE + snap.files.geocolour + bust;
    document.getElementById("ifvfIsobars").src = IFVF_BASE + snap.files.isobars + bust;
    document.getElementById("ifvfPfront").src = IFVF_BASE + snap.files.pfront + bust;

    let eumetsatNote = "";
    if (snap.eumetsat_actual_time && snap.eumetsat_actual_time !== snap.valid_time) {
        eumetsatNote = `<br><span style="color:#f0ad4e;">⚠ EUMETSAT: точного кадра на ${ifvfFormatTime(snap.valid_time)} не было, показан ближайший (${ifvfFormatTime(snap.eumetsat_actual_time)})</span>`;
    }
    document.getElementById("ifvfMeta").innerHTML =
        `<b>Valid time:</b> ${ifvfFormatTime(snap.valid_time)} &nbsp;` +
        `<b>Сгенерировано:</b> ${ifvfFormatTime(snap.generated_at_utc)} (${ifvfAgoMinutes(snap.generated_at_utc)} мин назад)<br>` +
        `<b>Run:</b> ICON-EU ${snap.run}, lead +${snap.lead_hours}ч &nbsp; ` +
        `<b>Скачано:</b> ${snap.downloaded_mb} МБ &nbsp; ` +
        `<b>P_front mean/max:</b> ${snap.pfront_mean.toFixed(3)} / ${snap.pfront_max.toFixed(3)}` +
        eumetsatNote;

    // подсветить активную кнопку выбора снимка
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
    try {
        const res = await fetch("data/icon_front_very_far/manifest.json?_=" + Date.now());
        if (!res.ok) throw new Error("manifest.json недоступен (" + res.status + ")");
        ifvfManifest = await res.json();
        if (!ifvfManifest.snapshots || !ifvfManifest.snapshots.length) {
            document.getElementById("ifvfMeta").textContent = "Пока нет ни одного снимка — ждём первый прогон cron (каждые 15 минут).";
            return;
        }
        ifvfBuildSnapshotButtons();
        // при первой загрузке или если выбранный индекс уже не последний — показываем последний
        const lastIdx = ifvfManifest.snapshots.length - 1;
        if (ifvfSelectedIdx === -1) ifvfSelectedIdx = lastIdx;
        ifvfRenderSnapshot(Math.min(ifvfSelectedIdx, lastIdx));
    } catch (e) {
        document.getElementById("ifvfMeta").textContent = "Ошибка загрузки: " + e.message;
    }

    try {
        const logRes = await fetch("data/icon_front_very_far/latest_log.txt?_=" + Date.now());
        if (logRes.ok) {
            const logText = await logRes.text();
            document.getElementById("ifvfLog").textContent = logText;
        }
    } catch (e) {
        // лог необязателен, молча пропускаем
    }
}
