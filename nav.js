/* nav.js — единая нижняя навигация */
(function() {

var TABS = [
    { label: "Прогноз",  icon: "📅", href: "forecast.html", match: ["forecast.html"] },
    { label: "По городу",icon: "🌆", href: "pws.html",      match: ["pws.html"] },
    { label: "Одесса",   icon: "🏙", href: "index.html",    match: ["index.html"] },
    { label: "Точность", icon: "📊", href: null, match: ["ensemble_pws.html", "ensemble_score.html", "verify.html", "verify_pws.html"],
      submenu: [
          { label: "Ensemble vs PWS",   href: "ensemble_pws.html" },
          { label: "Ensemble vs SYNOP", href: "ensemble_score.html" },
          { label: "Verify PWS",        href: "verify_pws.html" },
          { label: "Verify SYNOP",      href: "verify.html" },
      ]
    },
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
    "#app-nav a, #app-nav button.nav-btn {",
    "  flex: 1; display: flex; flex-direction: column;",
    "  align-items: center; justify-content: center;",
    "  align-self: stretch;",
    "  text-decoration: none; color: #555;",
    "  font-size: 10px; gap: 2px; transition: color 0.15s;",
    "  -webkit-tap-highlight-color: transparent;",
    "  background: none; border: none; padding: 0; cursor: pointer; font-family: inherit;",
    "}",
    "#app-nav a .nav-icon, #app-nav button.nav-btn .nav-icon { font-size: 20px; line-height: 1; }",
    "#app-nav a.active, #app-nav button.nav-btn.active { color: #ffd166; }",
    "#app-nav a:active, #app-nav button.nav-btn:active { color: #fff; }",
    ".header { display: none !important; }",
    /* Bottom sheet */
    "#nav-sheet-backdrop {",
    "  display: none; position: fixed; inset: 0; z-index: 1100;",
    "  background: rgba(0,0,0,0.5);",
    "}",
    "#nav-sheet-backdrop.open { display: block; }",
    "#nav-sheet {",
    "  position: absolute; bottom: 0; left: 0; right: 0;",
    "  background: #1a1a1a; border-radius: 16px 16px 0 0;",
    "  padding: 12px 0 calc(16px + env(safe-area-inset-bottom));",
    "}",
    "#nav-sheet-title {",
    "  text-align: center; color: #888; font-size: 12px;",
    "  padding: 0 0 12px; letter-spacing: 0.05em; text-transform: uppercase;",
    "}",
    "#nav-sheet a {",
    "  display: block; padding: 14px 24px;",
    "  color: #ccc; text-decoration: none; font-size: 15px;",
    "  border-bottom: 1px solid #262626;",
    "  -webkit-tap-highlight-color: transparent;",
    "}",
    "#nav-sheet a:last-child { border-bottom: none; }",
    "#nav-sheet a.active { color: #ffd166; }",
    "#nav-sheet a:active { background: #222; }",
].join("\n");
document.head.appendChild(style);

/* Bottom sheet DOM */
var backdrop = document.createElement("div");
backdrop.id = "nav-sheet-backdrop";
backdrop.innerHTML =
    '<div id="nav-sheet">' +
    '  <div id="nav-sheet-title">Точность</div>' +
    '</div>';

var sheet = backdrop.querySelector("#nav-sheet");

/* Подпункты */
var accuracyTab = TABS[3];
accuracyTab.submenu.forEach(function(item) {
    var a = document.createElement("a");
    a.href = item.href;
    a.textContent = item.label;
    if (item.href === page) a.className = "active";
    sheet.appendChild(a);
});

backdrop.addEventListener("click", function(e) {
    if (e.target === backdrop) closeSheet();
});

function openSheet() { backdrop.classList.add("open"); }
function closeSheet() { backdrop.classList.remove("open"); }

/* Nav */
var nav = document.createElement("nav");
nav.id = "app-nav";
nav.innerHTML = TABS.map(function(t) {
    var active = t.match.indexOf(page) !== -1 ? " active" : "";
    if (t.submenu) {
        return '<button class="nav-btn' + active + '" id="nav-accuracy-btn">' +
               '<span class="nav-icon">' + t.icon + '</span>' +
               '<span>' + t.label + '</span>' +
               '</button>';
    }
    return '<a href="' + t.href + '" class="' + active + '">' +
           '<span class="nav-icon">' + t.icon + '</span>' +
           '<span>' + t.label + '</span>' +
           '</a>';
}).join("");

/* Вставляем после загрузки DOM */
function mount() {
    document.body.appendChild(backdrop);
    document.body.appendChild(nav);
    document.getElementById("nav-accuracy-btn").addEventListener("click", openSheet);
}

if (document.body) {
    mount();
} else {
    document.addEventListener("DOMContentLoaded", mount);
}

})();