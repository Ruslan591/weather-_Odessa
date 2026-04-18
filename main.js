/* main.js — index.html (SYNOP only) */
const STATION_LAT  = 46.482;
const STATION_LON  = 30.723;
const STATION_CODE = "33837";
const isDay = isDayNow(STATION_LAT, STATION_LON, new Date());

loadSynopUI();
setInterval(loadSynopUI, 30 * 60 * 1000);
