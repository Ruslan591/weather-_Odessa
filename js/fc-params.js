const FC_PARAMS = [
    { key:"temp",     label:"Температура", color:"#ff8f00", unit:"°",    field: h => h.temperature_2m        },
    { key:"pressure", label:"Давление",    color:"#4aa3ff", unit:" гПа", field: h => h.pressure_msl          },
    { key:"humidity", label:"Влажность",   color:"#00bcd4", unit:"%",    field: h => h.relative_humidity_2m  },
    { key:"wind",     label:"Ветер",       color:"#8bc34a", unit:" м/с", field: h => h.wind_speed_10m        },
    { key:"winddir",  label:"Направление", color:"#74b9ff", unit:"°",    field: h => h.wind_direction_10m    },
    { key:"rain",     label:"Осадки",      color:"#448aff", unit:" мм",  field: h => h.rain                  },
    { key:"prob",     label:"Вер-ть осадков", color:"#5b8fc9", unit:"%", field: h => h.precip_prob ?? 0      },
    { key:"cloud",    label:"Облачность",  color:"#b0bec5", unit:"%",    field: h => h.cloud_cover           },
    { key:"cape",     label:"CAPE",         color:"#ff6b6b", unit:" Дж/кг", field: h => h.cape ?? null              },
    { key:"li",       label:"Lifted Index", color:"#a29bfe", unit:"",       field: h => h.lifted_index ?? null     },
    { key:"cin",      label:"CIN",          color:"#fd79a8", unit:" Дж/кг", field: h => h.convective_inhibition ?? null },
    // Атмосферный профиль
    { key:"temp_profile", label:"T ↑ уровни",   color:"#ff8f00", unit:"°",    field: h => h.temperature_2m },
    { key:"wind_profile", label:"Ветер ↑",       color:"#8bc34a", unit:" м/с", field: h => h.wind_speed_10m },
    { key:"freeze",       label:"0°C высота",    color:"#74b9ff", unit:" м",   field: h => null },
    { key:"wind_barbs",   label:"Разрез ветра",  color:"#fd79a8", unit:" м/с", field: h => h.wind_speed_10m },
    // Синоптика
    { key:"geo_height",   label:"Геопотенциал",  color:"#00cec9", unit:" м",   field: h => null },
    { key:"vert_vel",     label:"Омега ω",        color:"#ff6b6b", unit:" Па/с",field: h => null },
    { key:"polar_vortex", label:"Полярный вихрь", color:"#a29bfe", unit:" м",   field: h => null },
    // Морской прогноз
    { key:"wave",     label:"Волна",         color:"#00cec9", unit:" м",  field: h => h.wave_height       ?? null, marine:true },
    { key:"swell",    label:"Зыбь",          color:"#0984e3", unit:" м",  field: h => h.swell_wave_height ?? null, marine:true },
    { key:"wave_per", label:"Период волны",  color:"#6c5ce7", unit:" с",  field: h => h.wave_period       ?? null, marine:true },
    { key:"sst",      label:"Т воды",        color:"#fd79a8", unit:"°",   field: h => h.sea_surface_temperature ?? null, marine:true },
];

let _fcParam = "temp";
let _fcHours = null;
let _fcTimes = null;


const FC_GROUPS = [
    { label: null,         keys: ["temp","pressure","humidity","wind","winddir","rain","prob","cloud"] },
    { label: "Конвекция",  keys: ["cape","li","cin"] },
    { label: "Атмосфера",  keys: ["temp_profile","wind_profile","freeze","wind_barbs"] },
    { label: "Синоптика",    keys: ["geo_height","vert_vel","polar_vortex"] },
    { label: "Море",       keys: ["wave","swell","wave_per","sst"] },
];

function buildFcParamRow(){
    const row = document.getElementById("fcParamRow");
    if(!row) return;

    // Основные параметры — горизонтальный скролл
    const mainGroup = FC_GROUPS[0];
    let html = `<div class="fc-main-params">`;
    mainGroup.keys.forEach(key => {
        const p = FC_PARAMS.find(p => p.key === key);
        if(!p) return;
        html += `<button class="fc-param-btn${p.key === _fcParam ? " active" : ""}" data-key="${p.key}" style="--c:${p.color}" onclick="fcSwitchParam('${p.key}')">${p.label}</button>`;
    });
    html += `</div>`;

    // Аккордеоны для остальных групп
    FC_GROUPS.slice(1).forEach((g, gi) => {
        const gid = `fcGroup_${gi}`;
        const hasActive = g.keys.includes(_fcParam);
        html += `<div class="fc-group-accord${hasActive ? ' open' : ''}" id="${gid}">`;
        html += `<div class="fc-group-header" onclick="toggleFcGroup('${gid}')">`;
        html += `<span class="fc-group-label">${g.label}</span><span class="fc-group-arrow">▾</span></div>`;
        html += `<div class="fc-group-body"><div style="display:flex;flex-wrap:wrap;gap:6px;padding-bottom:8px;">`;
        g.keys.forEach(key => {
            const p = FC_PARAMS.find(p => p.key === key);
            if(!p) return;
            html += `<button class="fc-param-btn${p.key === _fcParam ? " active" : ""}" data-key="${p.key}" style="--c:${p.color}" onclick="fcSwitchParam('${p.key}')">${p.label}</button>`;
        });
        html += `</div></div></div>`;
    });

    row.innerHTML = html;
}

function toggleFcGroup(gid){
    const el = document.getElementById(gid);
    if(el) el.classList.toggle('open');
}

function fcSwitchParam(key){
    _fcParam = key;
    document.querySelectorAll(".fc-param-btn").forEach(b =>
        b.classList.toggle("active", b.dataset.key === key)
    );
    if(_fcHours) renderForecastChart(_fcHours, _fcTimes);
}
