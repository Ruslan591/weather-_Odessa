/* =========================================================
   UTILS.JS — вспомогательные функции
   Используется: synop.js, districts.js, indicators.js
========================================================= */

/* -------------------------
   Общие утилиты
------------------------- */
function escapeHtml(str){
    if(str == null) return "";
    return String(str)
        .replaceAll("&","&amp;")
        .replaceAll("<","&lt;")
        .replaceAll(">","&gt;");
}

function fmt1(v, unit=""){
    if(v == null || Number.isNaN(v)) return "-";
    return `${Number(v).toFixed(1)}${unit}`;
}

function fmt0(v, unit=""){
    if(v == null || Number.isNaN(v)) return "-";
    return `${Math.round(Number(v))}${unit}`;
}

function safeNum(v){
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
}

function tempClass(t){
    if(t == null) return "";
    if(t < 0)  return "tempCold";
    if(t < 10) return "tempCool";
    if(t < 20) return "tempMild";
    if(t < 30) return "tempWarm";
    return "tempHot";
}

function degToText(d){
    if(d == null || Number.isNaN(d)) return "-";
    if(d === 0) return "Штиль";
    // 16 румбов, 0/360 = С, по часовой стрелке
    const dirs = ["С","ССВ","СВ","ВСВ","В","ВЮВ","ЮВ","ЮЮВ","Ю","ЮЮЗ","ЮЗ","ЗЮЗ","З","ЗСЗ","СЗ","ССЗ"];
    const idx = Math.round(((d % 360) + 360) % 360 / 22.5) % 16;
    return dirs[idx];
}

function windArrow(deg){
    if(deg == null || Number.isNaN(deg)) return "";
    return `<span style="display:inline-block;transform:rotate(${deg}deg)">↑</span>`;
}

/* -------------------------
   Расчёт восхода / захода
------------------------- */
function isDayNow(lat, lon, date = new Date()){
    const rad = Math.PI / 180;

    const start = new Date(Date.UTC(date.getUTCFullYear(), 0, 0));
    const dayOfYear = Math.floor((date - start) / 86400000);

    const decl = 23.44 * Math.sin(rad * (360 / 365 * (dayOfYear - 81)));
    const latRad  = lat * rad;
    const declRad = decl * rad;
    const cosH = -Math.tan(latRad) * Math.tan(declRad);

    if(cosH < -1) return true;
    if(cosH > 1)  return false;

    const lngHour   = lon / 15;
    const utcHours  = date.getUTCHours() + date.getUTCMinutes() / 60;
    const solarNoon = 12 + lngHour - (lon / 15);
    const hourAngle = 15 * (utcHours - solarNoon);

    return hourAngle > -90 && hourAngle < 90;
}

/* -------------------------
   Физика атмосферы
------------------------- */
function calcRelativeHumidity(tempC, dewC){
    const t  = Number(tempC);
    const td = Number(dewC);
    if(!Number.isFinite(t) || !Number.isFinite(td)) return null;

    const es = 6.112 * Math.exp((17.62 * t)  / (243.12 + t));
    const e  = 6.112 * Math.exp((17.62 * td) / (243.12 + td));
    const rh = (e / es) * 100;

    if(!Number.isFinite(rh)) return null;
    return Math.max(0, Math.min(100, rh));
}

function calcFeelsLike(tempC, windMs, dewC){
    const t   = Number(tempC);
    const vMs = Number(windMs);
    const td  = Number(dewC);

    if(!Number.isFinite(t)) return null;

    const rh = calcRelativeHumidity(t, td);

    // Жара: heat index
    if(Number.isFinite(rh) && t >= 27){
        const tf = t * 9/5 + 32;
        const hiF =
            -42.379 +
            2.04901523  * tf +
            10.14333127 * rh -
            0.22475541  * tf * rh -
            0.00683783  * tf * tf -
            0.05481717  * rh * rh +
            0.00122874  * tf * tf * rh +
            0.00085282  * tf * rh * rh -
            0.00000199  * tf * tf * rh * rh;
        const hiC = (hiF - 32) * 5/9;
        if(Number.isFinite(hiC)) return hiC;
    }

    // Холод: wind chill
    if(Number.isFinite(vMs)){
        const vKmh = vMs * 3.6;
        if(t <= 10 && vKmh > 4.8){
            const wc =
                13.12 +
                0.6215 * t -
                11.37  * Math.pow(vKmh, 0.16) +
                0.3965 * t * Math.pow(vKmh, 0.16);
            if(Number.isFinite(wc)) return wc;
        }
    }

    return t;
}

/* -------------------------
   Форматирование времени
------------------------- */
function localTimeFromSynopYYGGi(yyggi){
    if(!yyggi || yyggi.length < 4) return "-";
    const day  = parseInt(yyggi.slice(0,2), 10);
    const hour = parseInt(yyggi.slice(2,4), 10);
    if(Number.isNaN(day) || Number.isNaN(hour)) return "-";

    const now = new Date();
    const utcDate = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), day, hour, 0, 0));
    const local   = new Date(utcDate.getTime() + 3 * 3600 * 1000); // UTC+3 (летнее время)

    const dd = String(local.getUTCDate()).padStart(2,"0");
    const mm = String(local.getUTCMonth() + 1).padStart(2,"0");
    const hh = String(local.getUTCHours()).padStart(2,"0");

    return `${dd}.${mm} ${hh}:00 местное`;
}

function formatAutoTime(isoString){
    if(!isoString) return "-";
    const d = new Date(isoString);
    if(Number.isNaN(d.getTime())) return "-";
    return d.toLocaleString("ru-RU",{
        day:"2-digit", month:"2-digit",
        hour:"2-digit", minute:"2-digit"
    });
}

/* -------------------------
   Расшифровки SYNOP
------------------------- */
function visibilityText(code){
    if(code == null) return "-";
    const n = Number(code);
    if(Number.isNaN(n)) return "-";

    if(n === 0)              return "< 100 м";
    if(n >= 1  && n <= 50)  return `${n * 100} м`;
    if(n >= 51 && n <= 55)  return `${(n - 50) * 100 + 5000} м`;   // 5100–5500 м
    if(n >= 56 && n <= 80)  return `${((n - 50) * 0.5).toFixed(1)} км`; // 3.0–15.0 км
    if(n >= 81 && n <= 88)  return `${(n - 80) * 5 + 25} км`;      // 30–65 км
    if(n === 89)             return "> 70 км";
    if(n === 90)             return "< 50 м";
    if(n === 91)             return "50 м";
    if(n === 92)             return "200 м";
    if(n === 93)             return "500 м";
    if(n === 94)             return "1 км";
    if(n === 95)             return "2 км";
    if(n === 96)             return "4 км";
    if(n === 97)             return "10 км";
    if(n === 98)             return "20 км";
    if(n === 99)             return "≥ 50 км";
    return "код " + code;
}

function cloudAmountText(n){
    if(n == null) return "-";
    const map = {
        0:"0/8 ясно", 1:"1/8", 2:"2/8", 3:"3/8", 4:"4/8",
        5:"5/8", 6:"6/8", 7:"7/8", 8:"8/8 сплошная"
    };
    return map[n] || `${n}/8`;
}

function tendencyText(code){
    const map = {
        "0":"Рост, затем падение; давление выше, чем 3 часа назад",
        "1":"Рост, затем без изменений; давление выше",
        "2":"Непрерывный рост",
        "3":"Падение или без изменений, затем рост; давление выше",
        "4":"Без изменений",
        "5":"Падение, затем рост; давление ниже, чем 3 часа назад",
        "6":"Падение, затем без изменений; давление ниже",
        "7":"Непрерывное падение",
        "8":"Рост или без изменений, затем падение; давление ниже"
    };
    return map[code] || "-";
}

function precipitationText(_, group6){
    if(!group6) return "Нет отдельной группы осадков";

    const amountCode = group6.slice(1, 4);
    const timeCode   = group6[4];
    const amountNum  = Number(amountCode);

    let amountText;
    if(!Number.isNaN(amountNum)){
        if(amountNum <= 988)       amountText = amountNum + " мм";
        else if(amountNum === 989) amountText = "≥ 989 мм";
        else if(amountNum === 990) amountText = "следы (< 0.1 мм)";
        else if(amountNum <= 999)  amountText = `${((amountNum - 990) * 0.1).toFixed(1)} мм`;
        else                       amountText = amountCode + " мм";
    } else {
        amountText = amountCode + " мм";
    }

    const tMap = {
        "0":"6 ч (срок)","1":"6 ч","2":"12 ч","3":"18 ч","4":"24 ч",
        "5":"1 ч","6":"2 ч","7":"3 ч","8":"9 ч","9":"15 ч"
    };
    const tText = tMap[timeCode] || `период ${timeCode}`;
    return `${amountText}, за ${tText}`;
}

/* Расшифровка W1/W2 — прошедшая погода (таблица 4561 WMO, коды 0–9) */
function synopPastWeatherText(code){
    if(code == null) return "-";
    const map = {
        "0": "Ясно или малооблачно",
        "1": "Облачно (переменная облачность)",
        "2": "Пасмурно (сплошная облачность)",
        "3": "Метель, пыльная буря или песчаная буря",
        "4": "Туман или ледяной туман",
        "5": "Морось",
        "6": "Дождь",
        "7": "Снег или дождь со снегом",
        "8": "Ливень",
        "9": "Гроза (с осадками или без)"
    };
    return map[String(code)] || `Код ${code}`;
}

function synopWeatherText(code){
    if(code == null) return " ";
    const map = {
        "00":"Ясно",
        "01":"Облака рассеиваются",
        "02":"Состояние неба без изменений",
        "03":"Облачность развивается",
        "04":"Дымка или дым",
        "05":"Мгла",
        "06":"Пыль или песок в воздухе",
        "07":"Поземная пыль или песок",
        "08":"Хорошо развитые вихри пыли",
        "09":"Смерч",
        "10":"Дымка",
        "11":"Поземный туман",
        "12":"Сплошной туман",
        "13":"Молния (грозы нет)",
        "17":"Гроза без осадков",
        "18":"Шквал",
        "19":"Смерч (воронкообразное облако)",
        "20":"Морось или снежные зёрна",
        "21":"Дождь",
        "22":"Снег",
        "24":"Гололёд",
        "25":"Ливень",
        "26":"Снегопад",
        "27":"Град",
        "28":"Туман",
        "29":"Гроза",
        "31":"Слабая поземная метель",
        "32":"Умеренная или сильная поземная метель",
        "33":"Слабая метель",
        "34":"Умеренная или сильная метель",
        "35":"Метель с поземком",
        "36":"Слабый поземный снег",
        "37":"Сильный поземный снег",
        "38":"Слабая поземная метель",
        "39":"Сильная поземная метель",
        "40":"Туман на расстоянии",
        "41":"Клочья тумана",
        "42":"Туман, небо видно (редеет)",
        "43":"Туман, небо не видно (редеет)",
        "44":"Туман, небо видно (без изменений)",
        "45":"Туман",
        "46":"Туман, небо видно (густеет)",
        "47":"Туман, небо не видно (густеет)",
        "48":"Туман с отложением изморози",
        "50":"Прерывистая слабая морось",
        "51":"Слабая морось",
        "52":"Прерывистая умеренная морось",
        "53":"Умеренная морось",
        "54":"Прерывистая сильная морось",
        "55":"Сильная морось",
        "56":"Переохлаждённая слабая морось",
        "57":"Переохлаждённая сильная морось",
        "58":"Морось с дождём",
        "59":"Сильная морось с дождём",
        "60":"Слабый прерывистый дождь",
        "61":"Слабый дождь",
        "62":"Умеренный прерывистый дождь",
        "63":"Умеренный дождь",
        "64":"Сильный прерывистый дождь",
        "65":"Сильный дождь",
        "66":"Слабый переохлаждённый дождь",
        "67":"Сильный переохлаждённый дождь",
        "68":"Слабый дождь со снегом",
        "69":"Умеренный или сильный дождь со снегом",
        "70":"Прерывистый слабый снег",
        "71":"Слабый снег",
        "72":"Прерывистый умеренный снег",
        "73":"Умеренный снег",
        "74":"Прерывистый сильный снег",
        "75":"Сильный снег",
        "76":"Ледяные иглы",
        "77":"Снежные зёрна",
        "78":"Отдельные снежные звёздочки",
        "79":"Ледяная крупа",
        "80":"Слабый ливень",
        "81":"Умеренный ливень",
        "82":"Сильный ливень",
        "83":"Слабый ливень с дождём и снегом",
        "84":"Сильный ливень с дождём и снегом",
        "85":"Слабый снежный ливень",
        "86":"Сильный снежный ливень",
        "87":"Слабый ливень с ледяной крупой",
        "88":"Сильный ливень с ледяной крупой",
        "89":"Слабый ливень с градом",
        "90":"Сильный ливень с градом",
        "91":"Слабый дождь (гроза недавно была)",
        "92":"Умеренный или сильный дождь (гроза недавно)",
        "93":"Слабый снег или дождь со снегом (гроза недавно)",
        "94":"Умеренный или сильный снег (гроза недавно)",
        "95":"Гроза",
        "96":"Гроза с мелким градом",
        "97":"Гроза с дождём или снегом",
        "98":"Гроза с пыльной бурей",
        "99":"Гроза с сильным градом"
    };
    return map[String(code).padStart(2,"0")] || `Код ${code}`;
}

function synopWeatherIcon(code, isDay){
    if(code == null) return isDay ? "⛅" : "🌙";
    code = String(code).padStart(2,"0");
    const day = isDay === true;

    if(code === "00") return day ? "☀️" : "🌙";
    if(["01","02","03"].includes(code)) return day ? "⛅" : "🌙☁️";
    if(["04","05","10","11","12","28","45","48"].includes(code)) return "🌫️";
    if(["20","21","24","25","51","53","55","56","57","61","63","65","66","67","80","81","82"].includes(code)) return "🌧️";
    if(["22","26","71","73","75","77","85","86"].includes(code)) return "🌨️";
    if(["17","29","95","96","99"].includes(code)) return "⛈️";
    if(code === "27") return "🧊";
    return day ? "⛅" : "🌙☁️";
}

function openMeteoWeatherText(code){
    const map = {
        0:"Ясно", 1:"Преимущественно ясно", 2:"Переменная облачность", 3:"Пасмурно",
        45:"Туман", 48:"Туман с инеем",
        51:"Слабая морось", 53:"Умеренная морось", 55:"Сильная морось",
        56:"Слабая ледяная морось", 57:"Сильная ледяная морось",
        61:"Слабый дождь", 63:"Умеренный дождь", 65:"Сильный дождь",
        66:"Слабый ледяной дождь", 67:"Сильный ледяной дождь",
        71:"Слабый снег", 73:"Умеренный снег", 75:"Сильный снег", 77:"Снежные зёрна",
        80:"Слабый ливень", 81:"Умеренный ливень", 82:"Сильный ливень",
        85:"Слабый снежный ливень", 86:"Сильный снежный ливень",
        95:"Гроза", 96:"Гроза с мелким градом", 99:"Гроза с сильным градом"
    };
    return map[code] ?? `Код ${code}`;
}

function openMeteoWeatherIcon(code, isDay){
    const day = Number(isDay) === 1;
    if(code === 0)  return day ? "☀️" : "🌙";
    if(code === 1)  return day ? "🌤️" : "🌙☁️";
    if(code === 2)  return day ? "⛅" : "🌙☁️";
    if(code === 3)  return "☁️";
    if(code === 45 || code === 48) return "🌫️";
    if([51,53,55,56,57].includes(code)) return "🌦️";
    if([61,63,65,66,67].includes(code)) return "🌧️";
    if([71,73,75,77,85,86].includes(code)) return "🌨️";
    if([80,81,82].includes(code)) return "🌦️";
    if([95,96,99].includes(code)) return "⛈️";
    return day ? "🌤️" : "🌙";
}

/* -------------------------
   Облака
------------------------- */
function cloudGenusLow(code){
    if(code == null) return "-";
    const map = {
        "0":"Нет облаков нижнего яруса",
        "1":"☁️ Кучевые плоские или разорванные",
        "2":"☁️ Кучевые средние или мощные",
        "3":"🌩️ Кучево-дождевые без волокнистой вершины",
        "4":"☁️ Слоисто-кучевые, образованные из кучевых",
        "5":"☁️ Слоисто-кучевые",
        "6":"🌫️ Слоистые или разорванно-слоистые",
        "7":"🌧️ Разорванно-слоистые / облака плохой погоды",
        "8":"☁️ Кучевые и слоисто-кучевые",
        "9":"⛈️ Кучево-дождевые с волокнистой вершиной",
        "/":"Не видно"
    };
    return code in map ? map[code] : "-";
}

function cloudGenusMid(code){
    if(code == null) return "-";
    const map = {
        "0":"Нет облаков среднего яруса",
        "1":" Высокослоистые просвечивающие",
        "2":"️ Высокослоистые плотные или слоисто-дождевые",
        "3":" Высококучевые просвечивающие",
        "4":" Высококучевые пятнами",
        "5":" Высококучевые полосами",
        "6":" Высококучевые, распространяющиеся по небу",
        "7":" Высококучевые в двух слоях",
        "8":" Высококучевые башенкообразные",
        "9":" Высококучевые хаотичные",
        "/":"Не видно"
    };
    return code in map ? map[code] : "-";
}

function cloudGenusHigh(code){
    if(code == null) return "-";
    const map = {
        "0":"Нет облаков верхнего яруса",
        "1":" Перистые нитевидные",
        "2":" Перистые плотные",
        "3":" Перистые плотные от кучево-дождевых",
        "4":" Перистые крючковидные или нитевидные",
        "5":" Перистые и перисто-слоистые у горизонта",
        "6":" Перистые и перисто-слоистые выше 45°",
        "7":"️ Перисто-слоистые покрывают небо",
        "8":"️ Перисто-слоистые не покрывают всё небо",
        "9":" Перисто-кучевые",
        "/":"Не видно"
    };
    return code in map ? map[code] : "-";
}

function cloudSvg(kind, code){
    const k = String(code ?? "");
    const icons = {
        low: {
            "1": `<svg viewBox="0 0 64 36" width="44" height="24" aria-hidden="true"><ellipse cx="22" cy="22" rx="14" ry="8" fill="none" stroke="currentColor" stroke-width="2"/><ellipse cx="36" cy="18" rx="15" ry="9" fill="none" stroke="currentColor" stroke-width="2"/></svg>`,
            "2": `<svg viewBox="0 0 64 36" width="44" height="24" aria-hidden="true"><ellipse cx="18" cy="23" rx="10" ry="6" fill="none" stroke="currentColor" stroke-width="2"/><ellipse cx="32" cy="18" rx="12" ry="8" fill="none" stroke="currentColor" stroke-width="2"/><ellipse cx="46" cy="22" rx="10" ry="6" fill="none" stroke="currentColor" stroke-width="2"/></svg>`,
            "3": `<svg viewBox="0 0 64 36" width="44" height="24" aria-hidden="true"><path d="M12 28 C14 18,20 12,28 10 C32 4,40 4,44 10 C52 12,56 18,54 28 Z" fill="none" stroke="currentColor" stroke-width="2"/><path d="M40 22 l-4 7 h4 l-3 6" fill="none" stroke="currentColor" stroke-width="2"/></svg>`,
            "4": `<svg viewBox="0 0 64 36" width="44" height="24" aria-hidden="true"><path d="M6 22 Q16 14 26 22 T46 22 T58 22" fill="none" stroke="currentColor" stroke-width="2"/></svg>`,
            "5": `<svg viewBox="0 0 64 36" width="44" height="24" aria-hidden="true"><path d="M6 18 Q12 14 18 18 T30 18 T42 18 T54 18" fill="none" stroke="currentColor" stroke-width="2"/><path d="M6 24 Q12 20 18 24 T30 24 T42 24 T54 24" fill="none" stroke="currentColor" stroke-width="2"/></svg>`,
            "6": `<svg viewBox="0 0 64 36" width="44" height="24" aria-hidden="true"><rect x="8" y="14" width="48" height="10" rx="5" fill="none" stroke="currentColor" stroke-width="2"/></svg>`,
            "7": `<svg viewBox="0 0 64 36" width="44" height="24" aria-hidden="true"><rect x="8" y="14" width="48" height="10" rx="5" fill="none" stroke="currentColor" stroke-width="2"/><path d="M18 26 l-2 5 M30 26 l-2 5 M42 26 l-2 5" stroke="currentColor" stroke-width="2"/></svg>`,
            "8": `<svg viewBox="0 0 64 36" width="44" height="24" aria-hidden="true"><ellipse cx="18" cy="22" rx="10" ry="6" fill="none" stroke="currentColor" stroke-width="2"/><path d="M28 18 Q34 14 40 18 T52 18" fill="none" stroke="currentColor" stroke-width="2"/></svg>`,
            "9": `<svg viewBox="0 0 64 36" width="44" height="24" aria-hidden="true"><path d="M12 28 C14 18,20 12,28 10 C32 3,40 3,44 10 C52 12,56 18,54 28 Z" fill="none" stroke="currentColor" stroke-width="2"/><path d="M46 11 C48 7,51 5,54 4" fill="none" stroke="currentColor" stroke-width="2"/></svg>`
        },
        mid: {
            "1": `<svg viewBox="0 0 64 36" width="44" height="24"><path d="M8 20 L56 20" stroke="currentColor" stroke-width="2"/><path d="M12 14 L52 14" stroke="currentColor" stroke-width="1.5" opacity="0.65"/></svg>`,
            "2": `<svg viewBox="0 0 64 36" width="44" height="24"><path d="M8 18 L56 18" stroke="currentColor" stroke-width="3"/><path d="M8 23 L56 23" stroke="currentColor" stroke-width="3"/></svg>`,
            "3": `<svg viewBox="0 0 64 36" width="44" height="24"><ellipse cx="16" cy="18" rx="7" ry="4" fill="none" stroke="currentColor" stroke-width="2"/><ellipse cx="30" cy="18" rx="7" ry="4" fill="none" stroke="currentColor" stroke-width="2"/><ellipse cx="44" cy="18" rx="7" ry="4" fill="none" stroke="currentColor" stroke-width="2"/></svg>`,
            "4": `<svg viewBox="0 0 64 36" width="44" height="24"><ellipse cx="18" cy="18" rx="8" ry="4" fill="none" stroke="currentColor" stroke-width="2"/><ellipse cx="38" cy="20" rx="10" ry="5" fill="none" stroke="currentColor" stroke-width="2"/></svg>`,
            "5": `<svg viewBox="0 0 64 36" width="44" height="24"><path d="M8 14 Q14 10 20 14 T32 14 T44 14 T56 14" fill="none" stroke="currentColor" stroke-width="2"/><path d="M8 22 Q14 18 20 22 T32 22 T44 22 T56 22" fill="none" stroke="currentColor" stroke-width="2"/></svg>`,
            "6": `<svg viewBox="0 0 64 36" width="44" height="24"><path d="M10 22 C20 12,44 12,54 22" fill="none" stroke="currentColor" stroke-width="2"/></svg>`,
            "7": `<svg viewBox="0 0 64 36" width="44" height="24"><path d="M8 14 Q14 10 20 14 T32 14 T44 14 T56 14" fill="none" stroke="currentColor" stroke-width="2"/><path d="M8 24 Q14 20 20 24 T32 24 T44 24 T56 24" fill="none" stroke="currentColor" stroke-width="2"/></svg>`,
            "8": `<svg viewBox="0 0 64 36" width="44" height="24"><path d="M10 24 L18 12 L26 24 Z M28 24 L36 10 L44 24 Z" fill="none" stroke="currentColor" stroke-width="2"/></svg>`,
            "9": `<svg viewBox="0 0 64 36" width="44" height="24"><ellipse cx="14" cy="18" rx="6" ry="3.5" fill="none" stroke="currentColor" stroke-width="2"/><ellipse cx="26" cy="22" rx="6" ry="3.5" fill="none" stroke="currentColor" stroke-width="2"/><ellipse cx="38" cy="16" rx="6" ry="3.5" fill="none" stroke="currentColor" stroke-width="2"/><ellipse cx="50" cy="21" rx="6" ry="3.5" fill="none" stroke="currentColor" stroke-width="2"/></svg>`
        },
        high: {
            "1": `<svg viewBox="0 0 64 36" width="44" height="24"><path d="M10 22 C18 18,22 10,30 14 C38 18,42 10,52 14" fill="none" stroke="currentColor" stroke-width="2"/></svg>`,
            "2": `<svg viewBox="0 0 64 36" width="44" height="24"><path d="M10 20 C18 16,22 12,30 14 C38 16,44 12,54 16" fill="none" stroke="currentColor" stroke-width="2.5"/></svg>`,
            "3": `<svg viewBox="0 0 64 36" width="44" height="24"><path d="M10 20 C18 16,22 12,30 14 C38 16,44 12,54 16" fill="none" stroke="currentColor" stroke-width="2.5"/><path d="M44 10 C46 7,49 5,53 4" fill="none" stroke="currentColor" stroke-width="1.8"/></svg>`,
            "4": `<svg viewBox="0 0 64 36" width="44" height="24"><path d="M10 22 C18 12,24 12,30 20 C36 28,42 12,54 16" fill="none" stroke="currentColor" stroke-width="2"/></svg>`,
            "5": `<svg viewBox="0 0 64 36" width="44" height="24"><path d="M8 20 C14 16,20 16,26 20" fill="none" stroke="currentColor" stroke-width="2"/><path d="M30 18 L56 18" stroke="currentColor" stroke-width="1.8"/></svg>`,
            "6": `<svg viewBox="0 0 64 36" width="44" height="24"><path d="M8 14 C14 10,20 10,26 14" fill="none" stroke="currentColor" stroke-width="2"/><path d="M30 12 L56 12" stroke="currentColor" stroke-width="1.8"/></svg>`,
            "7": `<svg viewBox="0 0 64 36" width="44" height="24"><path d="M8 14 L56 14" stroke="currentColor" stroke-width="1.8"/><path d="M8 20 L56 20" stroke="currentColor" stroke-width="1.8"/></svg>`,
            "8": `<svg viewBox="0 0 64 36" width="44" height="24"><path d="M8 18 L56 18" stroke="currentColor" stroke-width="1.6"/><path d="M14 12 L50 24" stroke="currentColor" stroke-width="1.2" opacity="0.6"/></svg>`,
            "9": `<svg viewBox="0 0 64 36" width="44" height="24"><ellipse cx="16" cy="16" rx="6" ry="3" fill="none" stroke="currentColor" stroke-width="2"/><ellipse cx="30" cy="18" rx="6" ry="3" fill="none" stroke="currentColor" stroke-width="2"/><ellipse cx="44" cy="15" rx="6" ry="3" fill="none" stroke="currentColor" stroke-width="2"/></svg>`
        }
    };
    return icons[kind]?.[k] || `<svg viewBox="0 0 64 36" width="44" height="24" aria-hidden="true"><path d="M8 18 L56 18" stroke="currentColor" stroke-width="2"/></svg>`;
}

function cloudRow(label, kind, code, text){
    return `
        <div class="row">
            <div class="label">${escapeHtml(label)}</div>
            <div class="value" style="display:flex;align-items:center;justify-content:flex-end;gap:10px;text-align:right">
                <span style="display:inline-flex;opacity:.9">${cloudSvg(kind, code)}</span>
                <span>${escapeHtml(text)}</span>
            </div>
        </div>`;
}

/* -------------------------
   Логи
------------------------- */
function showLogBox(boxId){
    const box = document.getElementById(boxId);
    if(box) box.classList.remove("hidden");
}

function hideLogBoxLater(boxId, delay=2600){
    const box = document.getElementById(boxId);
    if(!box) return;
    setTimeout(() => box.classList.add("hidden"), delay);
}

function clearLog(logId){
    const el = document.getElementById(logId);
    if(el) el.innerHTML = "";
}

function logTo(logId, msg){
    const el = document.getElementById(logId);
    if(!el) return;
    const line = document.createElement("div");
    line.className = "logLine";
    line.textContent = msg;
    el.appendChild(line);
}

/* -------------------------
   PWS парсинг
------------------------- */
function parsePWSOne(obs){
    const m = obs.metric||{}, km=v=>v!=null?Math.round(v/3.6*10)/10:null;
    return {
        stationID:obs.stationID||null, softwareType:obs.softwareType||null,
        obsTimeLocal:obs.obsTimeLocal||null, lat:obs.lat??null, lon:obs.lon??null, elev:m.elev??null,
        temp:m.temp??null, dewpt:m.dewpt??null, heatIndex:m.heatIndex??null, windChill:m.windChill??null,
        pressure:m.pressure??null, precipRate:m.precipRate??null, precipTotal:m.precipTotal??null,
        windDir:obs.winddir??null, humidity:obs.humidity??null, uv:obs.uv??null,
        solarRad:obs.solarRadiation??null, windSpeedMs:km(m.windSpeed), windGustMs:km(m.windGust),
    };
}