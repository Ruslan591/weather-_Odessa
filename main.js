/* main.js — index.html (SYNOP only) */
const STATION_LAT  = 46.482;
const STATION_LON  = 30.723;
const STATION_CODE = "33837";
const isDay = isDayNow(STATION_LAT, STATION_LON, new Date());

(function() {
    var last = localStorage.getItem("lastSynopUpdate");
    var el = document.getElementById("lastUpdate");
    if (el) el.textContent = last ? ("✅ Обновлено: " + last) : "Обновить";

    // Показываем кеш мгновенно
    var cached = localStorage.getItem("synopCachedHTML");
    if (cached) {
        document.getElementById("main").innerHTML = cached;
    }
})();

loadSynopUI();