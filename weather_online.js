async function fetchSynop() {
    const ogimet = "https://www.ogimet.com/display_synops2.php?lang=en&lugar=33837&tipo=ALL&ord=REV&nil=SI&fmt=txt";

    const proxies = [
        "https://api.allorigins.win/raw?url=",
        "https://corsproxy.io/?",
    ];

    let text = null;

    for (const p of proxies) {
        try {
            const url = p + encodeURIComponent(ogimet);
            const r = await fetch(url, { cache: "no-store" });
            text = await r.text();
            break;
        } catch (e) {
            console.log("Proxy fail:", p);
        }
    }

    if (!text) {
        document.getElementById("weather").innerText = "Не удалось загрузить данные SYNOP";
        return;
    }

    const line = text.split("\n").find(l => l.includes("AAXX"));
    if (!line) {
        document.getElementById("weather").innerText = "SYNOP не найден";
        return;
    }

    const synop = parseSynop(line);
    showWeather(synop);
}

function parseSynop(line) {
    const parts = line.trim().split(" ");
    const synopTime = parts[0];
    let temp = null, pressure = null, wind = null, windDir = null;

    parts.forEach((g, i) => {
        if (g.startsWith("1")) temp = (g[1]==="1"?-1:1)*parseInt(g.slice(2))/10;
        if (g.startsWith("4")) pressure = 1000 + parseInt(g.slice(1))/10;
    });

    const aaxxi = parts.indexOf("AAXX");
    if(aaxxi >=0 && parts.length > aaxxi+4){
        const windGroup = parts[aaxxi+4];
        windDir = parseInt(windGroup.slice(1,3))*10;
        wind = parseInt(windGroup.slice(3,5));
    }

    return { synopTime, temp, pressure, wind, windDir, synop: line };
}

function showWeather(s) {
    document.getElementById("weather").innerHTML = `
<b>Время наблюдения:</b> ${s.synopTime}<br>
<b>Температура:</b> ${s.temp} °C<br>
<b>Давление:</b> ${s.pressure} hPa<br>
<b>Ветер:</b> ${s.wind} м/с, ${s.windDir}°<br>
<pre>${s.synop}</pre>
`;
}

// автообновление каждые 10 минут
fetchSynop();
setInterval(fetchSynop, 600000);