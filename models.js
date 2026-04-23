// models.js  — единый реестр моделей проекта
// Добавь/удали модель только здесь, всё остальное подхватится автоматически

var MODEL_REGISTRY = [
  { id: "ecmwf_ifs",                      short: "ECMWF",   long: "ECMWF IFS HRES", ensemble: true },
  { id: "icon_eu",                        short: "ICON-EU", long: "ICON EU",         ensemble: true },
  { id: "icon_global",                    short: "ICON-G",  long: "ICON Global",     ensemble: true },
  { id: "ukmo_global_deterministic_10km", short: "UKMO",    long: "UKMO Global",     ensemble: true },
  { id: "meteofrance_arpege_europe",      short: "ARPEGE",  long: "ARPEGE Europe",   ensemble: true },
  { id: "gfs_global",                     short: "GFS",     long: "GFS Global",      ensemble: true },
  { id: "gem_global",                     short: "GEM",     long: "GEM Global",      ensemble: true },
  { id: "cma_grapes_global",              short: "CMA",     long: "CMA GRAPES",      ensemble: true }
];

function modelIds() {
    return MODEL_REGISTRY.map(function(m) { return m.id; });
}
function modelShort(id) {
    var m = MODEL_REGISTRY.filter(function(x) { return x.id === id; })[0];
    return m ? m.short : id;
}
function modelLong(id) {
    var m = MODEL_REGISTRY.filter(function(x) { return x.id === id; })[0];
    return m ? m.long : id;
}