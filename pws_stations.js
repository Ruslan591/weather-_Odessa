/* =========================================================
   PWS_STATIONS.JS — конфигурация верификационных станций
   pressureOffset — поправка к давлению станции (гПа),
   прибавляется к pressureMin перед сравнением с моделью.
   Знак: если станция показывает на 1.5 меньше реального,
   offset = +1.5
========================================================= */
var PWS_SYNC_STATIONS = [
    { id: "IODESA137", name: "пос. Котовского",  pressureOffset: -4.9 },
    { id: "IODESA138", name: "Центр",  pressureOffset: 10.2 },
    { id: "IODESA139", name: "Чудо Город",  pressureOffset: 0.4 },
    { id: "IODESS41", name: "Судостроительная",  pressureOffset: 4.2 },
    { id: "IODESS44", name: "Аркадия",  pressureOffset: -1.5 },
    { id: "IODESS16", name: "Таирова",  pressureOffset: 0.8 },
    { id: "IODESS31", name: "Савиньон",  pressureOffset: 19.1 },
    { id: "IODESS37", name: "Застава",  pressureOffset: 2.5 },
    { id: "IKRASN91", name: "пос. Степовое",  pressureOffset: -0.7 },
];
/* Публичные API ключи Weather Underground */
var PWS_WU_KEYS = [
    "6532d6454b8aa370768e63d6ba5a832e",
    "e1f10a1e78da46f5b10a1e78da96f525"
];

var _pwsSyncKeyIndex = 0;

function pwsNextKey() {
    return PWS_WU_KEYS[_pwsSyncKeyIndex % PWS_WU_KEYS.length];
}

function pwsBumpKey() {
    _pwsSyncKeyIndex++;
}
