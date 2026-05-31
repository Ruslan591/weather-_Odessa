function hoursLabel(h){
    if(h === 24) return "24 часа";
    if(h === 48) return "48 часов";
    const r = h % 10;
    if(r === 1 && h % 100 !== 11) return h + " час";
    if(r >= 2 && r <= 4 && !(h % 100 >= 12 && h % 100 <= 14)) return h + " часа";
    return h + " часов";
}
let forecastHours = parseInt(localStorage.getItem("forecastHours")) || 24;
document.getElementById("forecastDays").innerText = hoursLabel(forecastHours);
function toggleForecastMenu(e){ if(e) e.stopPropagation(); openSheet('forecastSheet'); }
function setForecastHours(hours){
    forecastHours = hours;
    localStorage.setItem("forecastHours", hours);
    document.getElementById("forecastDays").innerText = hoursLabel(hours);
    closeSheet('forecastSheet');
    load();
}

function modelLabel(model){ return model === "ensemble" ? "Ансамбль ⚡" : (modelLong(model) || "ECMWF IFS"); }

let weatherModel = localStorage.getItem("weatherModel") || "ecmwf_ifs";
document.getElementById("modelName").innerText = modelLabel(weatherModel);

function toggleModelMenu(e){ if(e) e.stopPropagation(); openSheet('modelSheet'); }

function setModel(model) {
    weatherModel = model;
    localStorage.setItem("weatherModel", model);
    document.getElementById("modelName").innerText = modelLabel(model);
    closeSheet('modelSheet');
    if (model === "ensemble") loadEnsemble();
    else load();
}

function toggle(el){ el.parentElement.classList.toggle("active"); }

function windDir(d){
    const dirs=["С","ССВ","СВ","ВСВ","В","ВЮВ","ЮВ","ЮЮВ","Ю","ЮЮЗ","ЮЗ","ЗЮЗ","З","ЗСЗ","СЗ","ССЗ"];
    return dirs[Math.round(d/22.5)%16];
}


function smooth(points){
    if(!points.length) return "";
    let d = `M ${points[0].x} ${points[0].y}`;
    for(let i = 1; i < points.length - 1; i++){
        const xc = (points[i].x + points[i+1].x) / 2;
        const yc = (points[i].y + points[i+1].y) / 2;
        d += ` Q ${points[i].x} ${points[i].y} ${xc} ${yc}`;
    }
    const last = points[points.length - 1];
    d += ` T ${last.x} ${last.y}`;
    return d;
}
