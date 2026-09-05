/* untangle workspace — shared behaviours (theme, letter-reveal, scroll reveal, ⌘K).
   Every hook is optional: a screen only activates what its markup contains. */
(function () {
  "use strict";
  function init() {
    var root = document.documentElement;
    root.classList.add("js");
    var reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;

    /* theme (persisted, shared key with the landing) */
    try { var s = localStorage.getItem("untangle-theme"); if (s) root.setAttribute("data-theme", s); } catch (e) {}
    var themeBtn = document.getElementById("theme");
    if (themeBtn) themeBtn.onclick = function () {
      var c = root.getAttribute("data-theme"), d = matchMedia("(prefers-color-scheme: dark)").matches;
      var n = c ? (c === "dark" ? "light" : "dark") : (d ? "light" : "dark");
      root.setAttribute("data-theme", n);
      try { localStorage.setItem("untangle-theme", n); } catch (e) {}
    };

    /* animated headings — split into per-letter spans, reveal on scroll */
    if (!reduce) {
      document.querySelectorAll(".ah[data-ah]").forEach(function (h) {
        var full = h.textContent, frag = document.createDocumentFragment();
        (function walk(node, dest) {
          [].slice.call(node.childNodes).forEach(function (n) {
            if (n.nodeType === 3) {
              n.textContent.split("").forEach(function (ch) {
                if (ch === " ") { dest.appendChild(document.createTextNode(" ")); return; }
                var sp = document.createElement("span"); sp.className = "ln"; sp.textContent = ch; dest.appendChild(sp);
              });
            } else if (n.nodeType === 1) { var cl = n.cloneNode(false); cl.className = n.className; walk(n, cl); dest.appendChild(cl); }
          });
        })(h, frag);
        var sr = document.createElement("span"); sr.className = "sr"; sr.textContent = full;
        h.textContent = ""; h.appendChild(sr);
        var vis = document.createElement("span"); vis.setAttribute("aria-hidden", "true"); vis.appendChild(frag); h.appendChild(vis);
        var L = h.querySelectorAll(".ln"), st = Math.min(17, 700 / Math.max(1, L.length));
        L.forEach(function (el, i) { el.style.setProperty("--d", (i * st) + "ms"); });
        h.classList.add("arm");
      });
      if ("IntersectionObserver" in window) {
        var io1 = new IntersectionObserver(function (es) { es.forEach(function (e) { if (e.isIntersecting) { e.target.classList.add("play"); io1.unobserve(e.target); } }); }, { threshold: .25, rootMargin: "0px 0px -6% 0px" });
        document.querySelectorAll(".ah.arm").forEach(function (h) { var r = h.getBoundingClientRect(); if (r.top < innerHeight * 0.95) h.classList.add("play"); else io1.observe(h); });
      } else { document.querySelectorAll(".ah.arm").forEach(function (h) { h.classList.add("play"); }); }
    }

    /* scroll reveals */
    var rs = [].slice.call(document.querySelectorAll(".reveal"));
    if (reduce || !("IntersectionObserver" in window)) { rs.forEach(function (el) { el.classList.add("in"); }); }
    else {
      var io2 = new IntersectionObserver(function (es) { es.forEach(function (e) { if (e.isIntersecting) { e.target.classList.add("in"); io2.unobserve(e.target); } }); }, { rootMargin: "0px 0px -8% 0px", threshold: .05 });
      rs.forEach(function (el) { var r = el.getBoundingClientRect(); if (r.top < innerHeight * 0.96) el.classList.add("in"); else io2.observe(el); });
      setTimeout(function () { rs.forEach(function (el) { el.classList.add("in"); }); }, 1800);
    }

    /* command palette (⌘K) — workspace routes */
    var bg = document.getElementById("cmdk");
    if (bg) {
      var items = [
        { g: "Workspace", n: "Dashboard", k: "/dashboard", u: "/dashboard" },
        { g: "Workspace", n: "Investigate exceptions", k: "/investigate", u: "/investigate" },
        { g: "Workspace", n: "Reconcile your files", k: "/app", u: "/app" },
        { g: "Workspace", n: "See the sample run", k: "/try-sample", u: "/try-sample" },
        { g: "Evidence", n: "Close certificate", k: "/certificate", u: "/certificate" },
        { g: "Evidence", n: "Verify a certificate", k: "/verify", u: "/verify" },
        { g: "Export", n: "Download Tally XML", k: "journal", u: "/api/journal/current.tally.xml" },
        { g: "Navigation", n: "Home / landing", k: "/", u: "/" },
        { g: "External", n: "Source on GitHub", k: "github", u: "https://github.com/vinayaksonthalia/untangle" }
      ];
      var inp = document.getElementById("cmdk-input"), list = document.getElementById("cmdk-list"), sel = 0, fil = items.slice(), opener = null;
      var go = function (it) { close(); if (it.u.charAt(0) === "#") { location.hash = it.u; } else if (it.u.charAt(0) === "/") { location.href = it.u; } else { window.open(it.u, "_blank", "noopener"); } };
      var pt = function () { list.querySelectorAll(".row").forEach(function (r, i) { r.setAttribute("aria-selected", i === sel); }); };
      var draw = function () {
        list.innerHTML = "";
        if (!fil.length) { list.innerHTML = '<div class="empty">No match.</div>'; return; }
        var g = null;
        fil.forEach(function (it, i) {
          if (it.g !== g) { g = it.g; var hh = document.createElement("div"); hh.className = "grp"; hh.textContent = g; list.appendChild(hh); }
          var r = document.createElement("div"); r.className = "row"; r.setAttribute("aria-selected", i === sel);
          var nm = document.createElement("span"); nm.className = "nm"; nm.textContent = it.n;
          var kk = document.createElement("span"); kk.className = "k"; kk.textContent = it.k;
          r.appendChild(nm); r.appendChild(kk);
          r.onclick = function () { go(it); };
          r.onmousemove = function () { sel = i; pt(); };
          list.appendChild(r);
        });
      };
      var open = function () { opener = document.activeElement; bg.classList.add("open"); if (inp) { inp.value = ""; } fil = items.slice(); sel = 0; draw(); setTimeout(function () { if (inp) inp.focus(); }, 20); };
      var close = function () { bg.classList.remove("open"); if (opener && opener.focus) opener.focus(); opener = null; };
      var opener2 = document.getElementById("cmdk-open"); if (opener2) opener2.onclick = open;
      if (inp) inp.addEventListener("input", function () { var q = inp.value.trim().toLowerCase(); fil = items.filter(function (it) { return (it.n + " " + it.k + " " + it.g).toLowerCase().indexOf(q) > -1; }); sel = 0; draw(); });
      addEventListener("keydown", function (e) {
        if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); bg.classList.contains("open") ? close() : open(); return; }
        if (!bg.classList.contains("open")) return;
        if (e.key === "Escape") close();
        else if (e.key === "Tab") { e.preventDefault(); if (inp) inp.focus(); }
        else if (e.key === "ArrowDown") { e.preventDefault(); sel = Math.min(sel + 1, fil.length - 1); pt(); }
        else if (e.key === "ArrowUp") { e.preventDefault(); sel = Math.max(sel - 1, 0); pt(); }
        else if (e.key === "Enter") { e.preventDefault(); if (fil[sel]) go(fil[sel]); }
      });
      bg.addEventListener("click", function (e) { if (e.target === bg) close(); });
    }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
