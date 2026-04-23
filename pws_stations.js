/* =========================================================
   PWS_STATIONS.JS — конфигурация верификационных станций
   pressureOffset — поправка к давлению станции (гПа),
   прибавляется к pressureMin перед сравнением с моделью.
   Знак: если станция показывает на 1.5 меньше реального,
   offset = +1.5
========================================================= */
var PWS_STATIONS = [
    { id: "IODESS44",  name: "Одесса 44",  pressureOffset: -1.8 },
    { id: "IODESS16",  name: "Одесса 16",  pressureOffset: 1.2 },
    { id: "IODESS37",  name: "Одесса 37",  pressureOffset: 8.2 },
    { id: "IODESA138", name: "Одесса 138", pressureOffset: 10.3 }
];

/* Публичные API ключи Weather Underground */
var PWS_WU_KEYS = [
    "6532d6454b8aa370768e63d6ba5a832e",
    "e1f10a1e78da46f5b10a1e78da96f525"
];

var _pwsKeyIndex = 0;

function pwsNextKey() {
    return PWS_WU_KEYS[_pwsKeyIndex % PWS_WU_KEYS.length];
}

function pwsBumpKey() {
    _pwsKeyIndex++;
}
