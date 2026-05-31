function fcShowTooltip(e, idx, data, times, cfg, rangeData, gustData){
    let tip = document.getElementById("fcTooltip");
    if(!tip){
        tip = document.createElement("div");
        tip.id = "fcTooltip";
        tip.style.cssText = `
            position:fixed;z-index:999;pointer-events:none;
            background:rgba(20,20,20,0.97);border:1px solid #333;border-radius:10px;
            padding:10px 14px;font-size:12px;color:#eee;min-width:140px;
            box-shadow:0 4px 24px rgba(0,0,0,0.5);transition:opacity 0.1s;
        `;
        document.body.appendChild(tip);
    }
    const val = data[idx];
    const t = times[idx] ? new Date(times[idx]) : null;
    const timeStr = t && !isNaN(t)
        ? t.toLocaleString("ru-RU",{day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"})
        : "";
    const gustVal = gustData ? gustData[idx] : null;
    const gustLine = (gustVal != null)
        ? `<div style="color:#ff9f5c;font-size:11px;margin-top:4px;">⬆ порыв ${gustVal.toFixed(1)} м/с</div>`
        : "";
    tip.innerHTML = `
        <div style="color:#888;margin-bottom:6px;font-size:11px;">${timeStr}</div>
        <div style="font-size:16px;font-weight:800;color:${cfg.color};">${val != null ? val.toFixed(1) + cfg.unit : "—"}</div>
        <div style="color:#aaa;font-size:11px;">${cfg.label}</div>
        ${gustLine}
    `;
    tip.style.opacity = "1";
    const tipW = 160;
    const left = e.clientX + tipW + 20 > window.innerWidth ? e.clientX - tipW - 12 : e.clientX + 12;
    tip.style.left = left + "px";
    tip.style.top  = (e.clientY - 40) + "px";
}
function fcHideTooltip(){
    const tip = document.getElementById("fcTooltip");
    if(tip) tip.style.opacity = "0";
}

// =============================================
// CROSSHAIR helper — добавляет перекрестие в SVG
// =============================================
function addCrosshair(svgEl, pts, pad, iW, iH, W, color, data, times, cfg, extraY, rangeData, gustData){
    const ns = "http://www.w3.org/2000/svg";

    const crossV = document.createElementNS(ns, "line");
    crossV.setAttribute("stroke", "rgba(255,255,255,0.3)");
    crossV.setAttribute("stroke-width", "1");
    crossV.setAttribute("stroke-dasharray", "3 3");
    crossV.style.display = "none";
    svgEl.appendChild(crossV);

    let crossH = null;
    if(extraY !== false){
        crossH = document.createElementNS(ns, "line");
        crossH.setAttribute("stroke", "rgba(255,255,255,0.2)");
        crossH.setAttribute("stroke-width", "1");
        crossH.setAttribute("stroke-dasharray", "3 3");
        crossH.style.display = "none";
        svgEl.appendChild(crossH);
    }

    const dot = document.createElementNS(ns, "circle");
    dot.setAttribute("r", "4");
    dot.setAttribute("fill", color);
    dot.setAttribute("stroke", "#111");
    dot.setAttribute("stroke-width", "2");
    dot.style.display = "none";
    svgEl.appendChild(dot);

    function move(mx){
        let best = 0, bestDist = Infinity;
        pts.forEach((p, i) => {
            const dist = Math.abs(p.x - mx);
            if(dist < bestDist){ bestDist = dist; best = i; }
        });
        const p = pts[best];
        crossV.setAttribute("x1", p.x); crossV.setAttribute("y1", pad.t);
        crossV.setAttribute("x2", p.x); crossV.setAttribute("y2", pad.t + iH);
        crossV.style.display = "";
        if(crossH){
            crossH.setAttribute("x1", pad.l); crossH.setAttribute("y1", p.y);
            crossH.setAttribute("x2", pad.l + iW); crossH.setAttribute("y2", p.y);
            crossH.style.display = "";
        }
        dot.setAttribute("cx", p.x);
        dot.setAttribute("cy", p.y);
        dot.style.display = "";
        return best;
    }

    function hide(){
        crossV.style.display = "none";
        if(crossH) crossH.style.display = "none";
        dot.style.display = "none";
        fcHideTooltip();
    }

    svgEl.addEventListener("mousemove", e => {
        const rect = svgEl.getBoundingClientRect();
        const mx = (e.clientX - rect.left) * W / rect.width;
        const best = move(mx);
        fcShowTooltip(e, best, data, times, cfg, rangeData, gustData);
    });
    svgEl.addEventListener("mouseleave", hide);
    svgEl.addEventListener("touchmove", e => {
        const touch = e.touches[0];
        const rect = svgEl.getBoundingClientRect();
        const mx = (touch.clientX - rect.left) * W / rect.width;
        const best = move(mx);
        fcShowTooltip(touch, best, data, times, cfg, rangeData, gustData);
        e.preventDefault();
    }, { passive: false });
    svgEl.addEventListener("touchend", hide);
}

// =============================================
// CROSSHAIR ДЛЯ МНОГОЛИНЕЙНЫХ ГРАФИКОВ
// =============================================
