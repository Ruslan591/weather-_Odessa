// modelCheck.js — проверка соответствия моделей в JSON-файлах
// Подключается в forecast.html и verify.html после models.js

(async function checkModelMismatch() {
    var files = [
        "modelData_2023.json",
        "modelData_2024.json",
        "modelData_2025.json",
        "modelData_2026.json"
    ];

    var foundModels = {};
    var checkedFile = null;

    for (var i = 0; i < files.length; i++) {
        try {
            var r = await fetch(files[i]);
            if (!r.ok) continue;
            var data = await r.json();
            var sample = data.slice ? data.slice(0, 10) : [];
            for (var j = 0; j < sample.length; j++) {
                if (sample[j].models) {
                    var keys = Object.keys(sample[j].models);
                    for (var k = 0; k < keys.length; k++) {
                        foundModels[keys[k]] = true;
                    }
                }
            }
            if (Object.keys(foundModels).length > 0) {
                checkedFile = files[i];
                break;
            }
        } catch(e) { continue; }
    }

    if (!checkedFile) return; // JSON-файлов нет — молчим

    var inJson     = Object.keys(foundModels).sort();
    var inRegistry = modelIds().slice().sort();

    var added   = inRegistry.filter(function(m) { return inJson.indexOf(m) === -1; });
    var removed = inJson.filter(function(m)     { return inRegistry.indexOf(m) === -1; });

    if (added.length === 0 && removed.length === 0) return;

    // Строим алерт
    var lines = [];
    if (added.length > 0) {
        lines.push("Добавлены в реестр, нет в данных: <b style='color:#2a6'>"
            + added.map(function(m){ return modelShort(m); }).join(", ") + "</b>");
    }
    if (removed.length > 0) {
        lines.push("Удалены из реестра, есть в данных: <b style='color:#a33'>"
            + removed.map(function(m){ return m; }).join(", ") + "</b>");
    }

    var box = document.createElement("div");
    box.style.cssText = [
        "position:fixed", "top:0", "left:0", "right:0", "z-index:9999",
        "background:#1a0e00", "border-bottom:2px solid #a83",
        "padding:14px 16px", "font-size:0.84em", "line-height:1.8",
        "font-family:monospace"
    ].join(";");

    box.innerHTML = [
        "<div style='color:#a83;font-weight:bold;margin-bottom:6px;'>",
            "⚠ Реестр моделей изменился — нужна пересборка JSON",
        "</div>",
        "<div style='color:#ccc;'>", lines.join("<br>"), "</div>",
        "<div style='margin-top:10px;'>",
            "<a href='buildHistory.html' style='",
                "display:inline-block;padding:7px 18px;",
                "border:1px solid #2a6;color:#2a6;text-decoration:none;",
                "font-family:monospace;margin-right:10px;'>",
                "▶ Перейти к пересборке",
            "</a>",
            "<span onclick='this.parentElement.parentElement.remove()' style='",
                "cursor:pointer;color:#555;padding:7px 12px;",
                "border:1px solid #333;'>",
                "✕ Закрыть",
            "</span>",
        "</div>"
    ].join("");

    document.body.appendChild(box);
})();