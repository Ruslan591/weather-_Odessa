/* nav.js — единая нижняя навигация */
(function() {

var TABS = [
    { label: "Прогноз",  icon: "📅", href: "forecast.html", match: ["forecast.html", "ensemble_pws.html"] },
    { label: "По городу",icon: "🌆", href: "pws.html",      match: ["pws.html"] },
    { label: "Одесса",   icon: "🏙", href: "index.html",    match: ["index.html"] },
    { label: "Точность", icon: "📊", href: "verify.html",   match: ["verify.html", "verify_pws.html", "ensemble_score.html"] },
];

var page = location.pathname.split("/").pop() || "index.html";

/* Стили */
var style = document.createElement("style");
style.textContent = [
    "body { padding-bottom: 64px; }",
    "#app-nav {",
    "  position: fixed; bottom: 0; left: 0; right: 0; z-index: 1000;",
    "  background: #111; border-top: 1px solid #222;",
    "  display: flex; height: 56px;",
    "  padding-bottom: env(safe-area-inset-bottom);",
    "}",
    "#app-nav a {",
    "  flex: 1; display: flex; flex-direction: column;",
    "  align-items: center; justify-content: center;",
    "  text-decoration: none; color: #555;",
    "  font-size: 10px; gap: 2px; transition: color 0.15s;",
    "  -webkit-tap-highlight-color: transparent;",
    "}",
    "#app-nav a .nav-icon { font-size: 20px; line-height: 1; }",
    "#app-nav a.active { color: #ffd166; }",
    "#app-nav a:active { color: #fff; }",
    /* Убираем старый хедер если есть */
    ".header { display: none !important; }",
].join("\n");
document.head.appendChild(style);

/* HTML */
var nav = document.createElement("nav");
nav.id = "app-nav";
nav.innerHTML = TABS.map(function(t) {
    var active = t.match.indexOf(page) !== -1 ? " active" : "";
    return '<a href="' + t.href + '" class="' + active + '">' +
           '<span class="nav-icon">' + t.icon + '</span>' +
           '<span>' + t.label + '</span>' +
           '</a>';
}).join("");

/* Вставляем после загрузки DOM */
if (document.body) {
    document.body.appendChild(nav);
} else {
    document.addEventListener("DOMContentLoaded", function() {
        document.body.appendChild(nav);
    });
}

})();
