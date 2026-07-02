(function () {
  const data = window.portfolioData || { updatedAt: null, cards: [], summary: {} };
  const cards = Array.isArray(data.cards) ? data.cards : [];
  const state = {
    query: "",
    set: "",
    language: "",
    status: "",
    condition: "",
    tab: "all",
    renderLimit: 240,
    lastVisibleCards: [],
    lookupRunning: false
  };

  const CACHE_KEY = "coleccion-scryfall-runtime-cache-v1";
  const NON_MTG_SET_HINTS = new Set([
    "unleashed", "origins", "spiritforged", "pillars of strength", "awakening of the new era",
    "kingdoms of intrigue", "proving grounds", "romance dawn", "op01", "op02", "op03", "op04",
    "op05", "op06", "op07", "op08", "op09", "op10", "op11", "wings of the captain"
  ]);

  const el = (id) => document.getElementById(id);

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function normalizeText(value) {
    return String(value || "")
      .normalize("NFD").replace(/[\u0300-\u036f]/g, "")
      .toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  }

  function cleanLookupName(value) {
    return String(value || "")
      .replace(/\s*\[(playset|set|lot)\]\s*$/i, "")
      .trim();
  }

  function cacheKeyFor(card) {
    return [cleanLookupName(card.lookupName || card.name), card.set || "", card.language || ""].map(normalizeText).join("|");
  }

  function loadRuntimeCache() {
    try { return JSON.parse(localStorage.getItem(CACHE_KEY) || "{}"); }
    catch (_) { return {}; }
  }

  function saveRuntimeCache(cache) {
    try { localStorage.setItem(CACHE_KEY, JSON.stringify(cache)); }
    catch (_) { /* cache may be full or unavailable */ }
  }

  function formatDate(value) {
    if (!value) return "Pendiente";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return new Intl.DateTimeFormat("es-ES", {
      year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit"
    }).format(date);
  }

  function money(value) {
    if (value === null || value === undefined || value === "") return "Pendiente";
    const number = Number(value);
    if (!Number.isFinite(number)) return "Pendiente";
    return new Intl.NumberFormat("es-ES", { style: "currency", currency: "EUR" }).format(number);
  }

  function safe(value, fallback = "-") {
    return value === null || value === undefined || value === "" ? fallback : String(value);
  }

  function isActive(card) {
    return !["Cancelado", "Sold"].includes(card.status);
  }

  function activeCards() {
    return cards.filter(isActive);
  }

  function computedSummary() {
    const active = activeCards();
    const invested = active.reduce((sum, card) => sum + Number(card.totalBuyPrice || 0), 0);
    const marketCards = active.filter(card => card.currentPrice !== null && card.currentPrice !== undefined);
    const marketValue = marketCards.reduce((sum, card) => sum + Number(card.currentPrice || 0) * Number(card.qty || 0), 0);
    return {
      cardsTotal: active.reduce((sum, card) => sum + Number(card.qty || 0), 0),
      invested,
      marketValue: marketCards.length ? marketValue : null,
      needsReview: cards.filter(card => card.needsReview || !card.image).length,
      missingImages: cards.filter(card => !card.image).length,
      withMarketPrice: marketCards.length,
      rowsTotal: cards.length,
      activeRows: active.length
    };
  }

  function populateSelect(selectEl, values, label) {
    const current = selectEl.value;
    selectEl.innerHTML = `<option value="">${escapeHtml(label)}</option>`;
    [...new Set(values.filter(Boolean).map(String))].sort((a, b) => a.localeCompare(b)).forEach(value => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = value;
      selectEl.appendChild(option);
    });
    selectEl.value = current;
  }

  function renderKpis() {
    const summary = Object.assign(computedSummary(), data.summary || {}, computedSummary());
    el("updatedAt").textContent = formatDate(data.updatedAt);
    el("kpiCards").textContent = Number(summary.cardsTotal || 0).toLocaleString("es-ES");
    el("kpiInvested").textContent = money(summary.invested || 0);
    el("kpiMarket").textContent = summary.marketValue === null || summary.marketValue === undefined ? "Pendiente" : money(summary.marketValue);
    el("kpiReview").textContent = Number(summary.needsReview || 0).toLocaleString("es-ES");

    const health = [
      ["Filas importadas", summary.rowsTotal || cards.length],
      ["Filas activas", summary.activeRows || activeCards().length],
      ["Con precio mercado", summary.withMarketPrice || 0],
      ["Sin imagen", summary.missingImages || 0]
    ];
    el("dataHealth").innerHTML = health.map(([label, value]) => `
      <div class="health-item"><strong>${Number(value || 0).toLocaleString("es-ES")}</strong><span>${escapeHtml(label)}</span></div>
    `).join("");
  }

  function renderSetBreakdown() {
    const counts = new Map();
    activeCards().forEach(card => counts.set(card.set || "Sin edicion", (counts.get(card.set || "Sin edicion") || 0) + Number(card.qty || 0)));
    const entries = [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8);
    const max = entries.length ? Math.max(...entries.map(entry => entry[1])) : 0;
    el("setCount").textContent = counts.size;
    el("setBreakdown").innerHTML = entries.length ? entries.map(([name, count]) => {
      const width = max ? Math.round((count / max) * 100) : 0;
      return `<div class="bar-row"><div class="bar-name" title="${escapeHtml(name)}">${escapeHtml(name)}</div><div class="bar-track"><div class="bar-fill" style="--width:${width}%"></div></div><strong>${count}</strong></div>`;
    }).join("") : `<p class="muted">Sin datos todavia.</p>`;
  }

  function resetAndRender() {
    state.renderLimit = 240;
    renderCards();
  }

  function setupFilters() {
    populateSelect(el("setFilter"), cards.map(card => card.set), "Todas las ediciones");
    populateSelect(el("languageFilter"), cards.map(card => card.language), "Todos los idiomas");
    populateSelect(el("statusFilter"), cards.map(card => card.status), "Todos los estados");
    populateSelect(el("conditionFilter"), cards.map(card => card.condition), "Todas las condiciones");

    el("searchInput").addEventListener("input", event => { state.query = event.target.value.trim().toLowerCase(); resetAndRender(); });
    el("setFilter").addEventListener("change", event => { state.set = event.target.value; resetAndRender(); });
    el("languageFilter").addEventListener("change", event => { state.language = event.target.value; resetAndRender(); });
    el("statusFilter").addEventListener("change", event => { state.status = event.target.value; resetAndRender(); });
    el("conditionFilter").addEventListener("change", event => { state.condition = event.target.value; resetAndRender(); });

    document.querySelectorAll(".tab").forEach(button => {
      button.addEventListener("click", () => {
        document.querySelectorAll(".tab").forEach(tab => tab.classList.remove("active"));
        button.classList.add("active");
        state.tab = button.dataset.tab || "all";
        resetAndRender();
      });
    });

    const lookupButton = el("imageLookupButton");
    if (lookupButton) lookupButton.addEventListener("click", () => queueVisibleScryfallLookups({ manual: true, limit: 120 }));
  }

  function matches(card) {
    const haystack = [card.name, card.lookupName, card.set, card.setCode, card.cardNumber, card.language, card.condition, card.status, card.tcg]
      .filter(Boolean).join(" ").toLowerCase();
    if (state.query && !haystack.includes(state.query)) return false;
    if (state.set && card.set !== state.set) return false;
    if (state.language && card.language !== state.language) return false;
    if (state.status && card.status !== state.status) return false;
    if (state.condition && card.condition !== state.condition) return false;
    if (state.tab !== "all") {
      if (state.tab === "review") return Boolean(card.needsReview || !card.image);
      return card.status === state.tab;
    }
    return true;
  }

  function cardHtml(card, realIndex) {
    const review = card.needsReview || !card.image;
    const img = card.image ? `<img class="card-image" loading="lazy" src="${escapeHtml(card.image)}" alt="${escapeHtml(card.name || "Carta")}">` : `<div class="card-placeholder">Sin imagen<br><small>Resolver Scryfall</small></div>`;
    const current = card.currentPrice === null || card.currentPrice === undefined ? "Pendiente" : money(card.currentPrice);
    const tcgChip = card.tcg ? `<span class="meta-chip">${escapeHtml(card.tcg)}</span>` : "";
    return `
      <article class="card ${review ? "needs-review" : ""}" data-index="${realIndex}">
        <div class="card-image-wrap">${img}</div>
        <div class="card-body">
          <h3 class="card-title">${escapeHtml(safe(card.name))}</h3>
          <div class="card-meta">
            <span class="meta-chip">${escapeHtml(safe(card.set))}</span>
            <span class="meta-chip">${escapeHtml(safe(card.language))}</span>
            <span class="meta-chip">${escapeHtml(safe(card.condition))}</span>
            <span class="meta-chip">x${escapeHtml(safe(card.qty, 1))}</span>
            ${tcgChip}
          </div>
          <div class="price-line">
            <div class="price-box"><span>Compra</span><strong>${money(card.buyPrice)}</strong></div>
            <div class="price-box"><span>Mercado</span><strong>${current}</strong></div>
          </div>
          <div class="card-footer">
            ${review ? `<span class="review-dot" title="Necesita revision"></span>` : `<span class="meta-chip">${escapeHtml(safe(card.status))}</span>`}
            <button class="open-card" type="button" data-index="${realIndex}">Detalle</button>
          </div>
        </div>
      </article>
    `;
  }

  function renderCards() {
    const filtered = cards.filter(matches);
    const shown = filtered.slice(0, state.renderLimit);
    state.lastVisibleCards = shown;
    el("resultCount").textContent = `${shown.length.toLocaleString("es-ES")} de ${filtered.length.toLocaleString("es-ES")} resultados`;
    el("cardsGrid").innerHTML = shown.map(card => cardHtml(card, cards.indexOf(card))).join("") +
      (filtered.length > shown.length ? `<div class="load-more-card"><button id="loadMoreButton" class="primary-button" type="button">Mostrar mas</button></div>` : "");
    el("emptyState").classList.toggle("hidden", filtered.length > 0);
    document.querySelectorAll(".open-card").forEach(button => {
      button.addEventListener("click", () => openModal(cards[Number(button.dataset.index)]));
    });
    const loadMore = el("loadMoreButton");
    if (loadMore) loadMore.addEventListener("click", () => { state.renderLimit += 240; renderCards(); });
    queueVisibleScryfallLookups({ manual: false, limit: 18 });
  }

  function renderReview() {
    const rows = cards.filter(card => card.needsReview || !card.image).slice(0, 250);
    const total = cards.filter(card => card.needsReview || !card.image).length;
    el("reviewTableBody").innerHTML = rows.length ? rows.map(card => {
      const reasons = [];
      if (!card.image) reasons.push("Sin imagen");
      if (card.needsReview) reasons.push("Matching pendiente/manual");
      if (card.scryfall && card.scryfall.matched === false) reasons.push(card.scryfall.matchedBy || "No encontrado en Scryfall");
      return `<tr><td>${escapeHtml(safe(card.name))}</td><td>${escapeHtml(safe(card.set))}</td><td>${escapeHtml(safe(card.language))}</td><td>${escapeHtml(reasons.join(", ") || "Revision")}</td><td>${escapeHtml(safe(card.source && card.source.row))}</td></tr>`;
    }).join("") + (total > rows.length ? `<tr><td colspan="5">Mostrando ${rows.length} de ${total}. Usa filtros o busqueda para acotar.</td></tr>` : "") : `<tr><td colspan="5">No hay elementos pendientes de revision.</td></tr>`;
  }

  function openModal(card) {
    const modal = el("cardModal");
    const img = card.image ? `<img src="${escapeHtml(card.image)}" alt="${escapeHtml(card.name || "Carta")}">` : `<div class="card-placeholder">Sin imagen</div>`;
    const links = [
      card.scryfallUrl ? `<a href="${escapeHtml(card.scryfallUrl)}" target="_blank" rel="noreferrer">Scryfall</a>` : "",
      card.cardmarketUrl ? `<a href="${escapeHtml(card.cardmarketUrl)}" target="_blank" rel="noreferrer">Cardmarket</a>` : ""
    ].filter(Boolean).join("");
    el("modalBody").innerHTML = `
      <div class="modal-grid">
        <div>${img}</div>
        <div>
          <h3>${escapeHtml(safe(card.name))}</h3>
          <p class="muted">${escapeHtml(safe(card.set))} ${card.cardNumber ? "- #" + escapeHtml(card.cardNumber) : ""}</p>
          <div class="modal-list">
            <div><span>Estado</span><strong>${escapeHtml(safe(card.status))}</strong></div>
            <div><span>TCG</span><strong>${escapeHtml(safe(card.tcg, "No informado"))}</strong></div>
            <div><span>Idioma</span><strong>${escapeHtml(safe(card.language))}</strong></div>
            <div><span>Condicion</span><strong>${escapeHtml(safe(card.condition))}</strong></div>
            <div><span>Cantidad</span><strong>${escapeHtml(safe(card.qty))}</strong></div>
            <div><span>Compra unidad</span><strong>${money(card.buyPrice)}</strong></div>
            <div><span>Compra total</span><strong>${money(card.totalBuyPrice)}</strong></div>
            <div><span>Mercado</span><strong>${money(card.currentPrice)}</strong></div>
            <div><span>Scryfall match</span><strong>${card.scryfall && card.scryfall.matched ? "OK" : "Pendiente"} ${card.scryfall && card.scryfall.score ? "(" + card.scryfall.score + ")" : ""}</strong></div>
            <div><span>Fila Excel</span><strong>${escapeHtml(safe(card.source && card.source.row))}</strong></div>
          </div>
          <div class="modal-links">${links || "<span class='muted'>Sin enlaces externos.</span>"}</div>
        </div>
      </div>
    `;
    if (typeof modal.showModal === "function") modal.showModal();
  }

  function setupModal() {
    el("closeModal").addEventListener("click", () => el("cardModal").close());
    el("cardModal").addEventListener("click", event => {
      const rect = el("cardModal").getBoundingClientRect();
      const inDialog = rect.top <= event.clientY && event.clientY <= rect.bottom && rect.left <= event.clientX && event.clientX <= rect.right;
      if (!inDialog) el("cardModal").close();
    });
  }

  function setupTheme() {
    const stored = localStorage.getItem("portfolio-theme");
    if (stored === "light") document.documentElement.classList.add("light");
    el("themeToggle").addEventListener("click", () => {
      document.documentElement.classList.toggle("light");
      localStorage.setItem("portfolio-theme", document.documentElement.classList.contains("light") ? "light" : "dark");
    });
  }

  function setupNav() {
    document.querySelectorAll(".nav-link").forEach(link => {
      link.addEventListener("click", () => {
        document.querySelectorAll(".nav-link").forEach(item => item.classList.remove("active"));
        link.classList.add("active");
      });
    });
  }

  function isLikelyNonMtg(card) {
    const tcg = normalizeText(card.tcg);
    if (tcg && !tcg.includes("magic")) return true;
    const set = normalizeText(card.set);
    return NON_MTG_SET_HINTS.has(set);
  }

  function setLookupStatus(text) {
    const status = el("imageLookupStatus");
    if (status) status.textContent = text || "";
  }

  async function fetchJsonWithTimeout(url, timeoutMs = 12000) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(url, { signal: controller.signal, headers: { "Accept": "application/json" } });
      if (!response.ok) return null;
      return await response.json();
    } catch (_) {
      return null;
    } finally {
      clearTimeout(timeout);
    }
  }

  function imageFromScryfallPayload(payload) {
    if (!payload) return null;
    const images = payload.image_uris || (payload.card_faces && payload.card_faces[0] && payload.card_faces[0].image_uris) || {};
    const image = images.normal || images.large || images.small || images.png;
    if (!image) return null;
    return {
      image,
      imageUrls: images,
      scryfallUrl: payload.scryfall_uri,
      scryfall: {
        matched: true,
        matchedBy: "browser-runtime",
        score: 60,
        id: payload.id,
        name: payload.name,
        lang: payload.lang,
        set: payload.set,
        setName: payload.set_name,
        collectorNumber: payload.collector_number,
        uri: payload.scryfall_uri
      }
    };
  }

  async function lookupScryfall(card) {
    const name = cleanLookupName(card.lookupName || card.name);
    if (!name || isLikelyNonMtg(card)) return { notFound: true, reason: "skip-non-mtg" };
    const exactUrl = `https://api.scryfall.com/cards/named?exact=${encodeURIComponent(name)}`;
    let payload = await fetchJsonWithTimeout(exactUrl);
    let result = imageFromScryfallPayload(payload);
    if (result) return result;
    const fuzzyUrl = `https://api.scryfall.com/cards/named?fuzzy=${encodeURIComponent(name)}`;
    payload = await fetchJsonWithTimeout(fuzzyUrl);
    result = imageFromScryfallPayload(payload);
    return result || { notFound: true, reason: "not-found" };
  }

  function applyRuntimeImage(card, result) {
    if (!result || !result.image) return;
    card.image = result.image;
    card.imageUrls = result.imageUrls || card.imageUrls;
    card.scryfallUrl = result.scryfallUrl || card.scryfallUrl;
    card.scryfall = Object.assign({}, card.scryfall || {}, result.scryfall || {});
    card.needsReview = false;
    const index = cards.indexOf(card);
    const article = document.querySelector(`.card[data-index="${index}"]`);
    if (article) {
      article.classList.remove("needs-review");
      const imageWrap = article.querySelector(".card-image-wrap");
      if (imageWrap) imageWrap.innerHTML = `<img class="card-image" loading="lazy" src="${escapeHtml(card.image)}" alt="${escapeHtml(card.name || "Carta")}">`;
    }
  }

  async function queueVisibleScryfallLookups(options = {}) {
    const { manual = false, limit = 24 } = options;
    if (state.lookupRunning || typeof fetch !== "function") return;
    const cache = loadRuntimeCache();
    const queue = [];
    const seen = new Set();
    for (const card of state.lastVisibleCards) {
      if (!card || card.image) continue;
      const key = cacheKeyFor(card);
      if (seen.has(key)) continue;
      seen.add(key);
      const cached = cache[key];
      if (cached && cached.image) {
        applyRuntimeImage(card, cached);
        continue;
      }
      if (!manual && cached && cached.notFound) continue;
      if (!manual && queue.length >= limit) break;
      queue.push({ card, key });
      if (queue.length >= limit) break;
    }
    if (!queue.length) {
      if (manual) setLookupStatus("No hay imagenes visibles pendientes o ya estaban cacheadas.");
      renderKpis();
      renderReview();
      return;
    }
    state.lookupRunning = true;
    setLookupStatus(`Consultando Scryfall: 0/${queue.length}`);
    let ok = 0;
    for (let i = 0; i < queue.length; i += 1) {
      const { card, key } = queue[i];
      const result = await lookupScryfall(card);
      cache[key] = result || { notFound: true };
      if (result && result.image) {
        ok += 1;
        const sameKeyCards = cards.filter(item => !item.image && cacheKeyFor(item) === key);
        sameKeyCards.forEach(item => applyRuntimeImage(item, result));
      }
      setLookupStatus(`Consultando Scryfall: ${i + 1}/${queue.length} · ${ok} imagenes`);
      await new Promise(resolve => setTimeout(resolve, 160));
    }
    saveRuntimeCache(cache);
    state.lookupRunning = false;
    setLookupStatus(ok ? `Imagenes resueltas: ${ok}. Cache guardada en este navegador.` : "No se resolvieron imagenes en este lote.");
    renderKpis();
    renderReview();
  }

  function init() {
    renderKpis();
    renderSetBreakdown();
    setupFilters();
    setupTheme();
    setupNav();
    setupModal();
    renderCards();
    renderReview();
  }

  init();
})();
