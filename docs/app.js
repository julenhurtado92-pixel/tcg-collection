(function () {
  const data = window.portfolioData || { updatedAt: null, cards: [], summary: {} };
  const cards = Array.isArray(data.cards) ? data.cards : [];
  cards.forEach((card, index) => { card.__index = index; });

  const state = {
    query: "",
    set: "",
    tcg: "",
    language: "",
    status: "",
    operation: "",
    condition: "",
    tab: "all",
    page: 1,
    pageSize: 20,
    sortKey: "date",
    sortDir: "desc",
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

  function safe(value, fallback = "-") {
    return value === null || value === undefined || value === "" ? fallback : String(value);
  }

  function number(value) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : 0;
  }

  function money(value) {
    if (value === null || value === undefined || value === "") return "Pendiente";
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return "Pendiente";
    return new Intl.NumberFormat("es-ES", { style: "currency", currency: "EUR" }).format(parsed);
  }

  function signedMoney(value) {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return "Pendiente";
    const prefix = parsed > 0 ? "+" : "";
    return prefix + money(parsed);
  }

  function formatDate(value) {
    if (!value) return "Pendiente";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return new Intl.DateTimeFormat("es-ES", {
      year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit"
    }).format(date);
  }

  function dateValue(value) {
    if (!value) return 0;
    const parsed = new Date(value).getTime();
    return Number.isFinite(parsed) ? parsed : 0;
  }

  function isSold(card) {
    return card.status === "Sold" || card.operationType === "Venta";
  }

  function isCancelled(card) {
    return card.status === "Cancelado" || card.operationType === "Cancelado";
  }

  function isActive(card) {
    return !isSold(card) && !isCancelled(card);
  }

  function activeCards() {
    return cards.filter(isActive);
  }

  function soldCards() {
    return cards.filter(isSold);
  }

  function totalAmount(list) {
    return list.reduce((sum, card) => sum + number(card.totalBuyPrice), 0);
  }

  function qtyAmount(list) {
    return list.reduce((sum, card) => sum + number(card.qty || 1), 0);
  }

  function computedSummary() {
    const active = activeCards();
    const sold = soldCards();
    const marketCards = active.filter(card => card.currentPrice !== null && card.currentPrice !== undefined && card.currentPrice !== "");
    const invested = totalAmount(active);
    const soldTotal = totalAmount(sold);
    const marketValue = marketCards.reduce((sum, card) => sum + number(card.currentPrice) * number(card.qty || 1), 0);
    return {
      cardsTotal: qtyAmount(active),
      invested,
      soldTotal,
      net: soldTotal - invested,
      marketValue: marketCards.length ? marketValue : null,
      needsReview: cards.filter(card => card.needsReview || !card.image).length,
      missingImages: cards.filter(card => !card.image).length,
      withMarketPrice: marketCards.length,
      rowsTotal: cards.length,
      activeRows: active.length,
      soldRows: sold.length,
      editions: new Set(cards.map(card => card.set).filter(Boolean)).size,
      uniqueCards: new Set(cards.map(card => normalizeText(card.lookupName || card.name)).filter(Boolean)).size
    };
  }

  function populateSelect(selectEl, values, label) {
    if (!selectEl) return;
    const current = selectEl.value;
    selectEl.innerHTML = `<option value="">${escapeHtml(label)}</option>`;
    [...new Set(values.filter(Boolean).map(String))]
      .sort((a, b) => a.localeCompare(b, "es"))
      .forEach(value => {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = value;
        selectEl.appendChild(option);
      });
    if ([...selectEl.options].some(option => option.value === current)) selectEl.value = current;
  }

  function aggregateBy(list, keyFn, valueFn) {
    const map = new Map();
    list.forEach(card => {
      const key = keyFn(card) || "Sin dato";
      map.set(key, (map.get(key) || 0) + valueFn(card));
    });
    return [...map.entries()].sort((a, b) => b[1] - a[1]);
  }

  function renderBarList(targetId, entries, options = {}) {
    const target = el(targetId);
    if (!target) return;
    const { formatter = value => value.toLocaleString("es-ES"), limit = 8, onClickType = null } = options;
    const shown = entries.slice(0, limit);
    const max = shown.length ? Math.max(...shown.map(entry => entry[1])) : 0;
    target.innerHTML = shown.length ? shown.map(([name, value]) => {
      const width = max ? Math.max(3, Math.round((value / max) * 100)) : 0;
      const button = onClickType
        ? `<button class="bar-name" type="button" data-filter-type="${escapeHtml(onClickType)}" data-filter-value="${escapeHtml(name)}" title="${escapeHtml(name)}">${escapeHtml(name)}</button>`
        : `<div class="bar-name" title="${escapeHtml(name)}">${escapeHtml(name)}</div>`;
      return `<div class="bar-row">${button}<div class="bar-track"><div class="bar-fill" style="--width:${width}%"></div></div><strong class="bar-value">${escapeHtml(formatter(value))}</strong></div>`;
    }).join("") : `<p class="muted">Sin datos todavia.</p>`;
  }

  function setupBarClicks() {
    document.querySelectorAll("[data-filter-type]").forEach(button => {
      button.addEventListener("click", () => {
        const type = button.dataset.filterType;
        const value = button.dataset.filterValue || "";
        if (type === "set") {
          state.set = value;
          if (el("setFilter")) el("setFilter").value = value;
        }
        if (type === "name") {
          state.query = value;
          if (el("searchInput")) el("searchInput").value = value;
        }
        state.page = 1;
        renderCards();
        document.getElementById("collection")?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });
  }

  function renderKpis() {
    const summary = computedSummary();
    if (el("updatedAt")) el("updatedAt").textContent = formatDate(data.updatedAt);
    if (el("kpiCards")) el("kpiCards").textContent = Number(summary.cardsTotal || 0).toLocaleString("es-ES");
    if (el("kpiInvested")) el("kpiInvested").textContent = money(summary.invested || 0);
    if (el("kpiSold")) el("kpiSold").textContent = money(summary.soldTotal || 0);
    if (el("kpiNet")) {
      el("kpiNet").textContent = signedMoney(summary.net || 0);
      el("kpiNet").className = summary.net >= 0 ? "positive" : "negative";
    }
    if (el("kpiMarket")) el("kpiMarket").textContent = summary.marketValue === null || summary.marketValue === undefined ? "Pendiente" : money(summary.marketValue);
    if (el("kpiReview")) el("kpiReview").textContent = Number(summary.needsReview || 0).toLocaleString("es-ES");

    const health = [
      ["Filas importadas", summary.rowsTotal],
      ["Filas activas", summary.activeRows],
      ["Filas vendidas", summary.soldRows],
      ["Ediciones", summary.editions],
      ["Cartas unicas", summary.uniqueCards],
      ["Sin imagen", summary.missingImages]
    ];
    if (el("dataHealth")) {
      el("dataHealth").innerHTML = health.map(([label, value]) => `
        <div class="health-item"><strong>${Number(value || 0).toLocaleString("es-ES")}</strong><span>${escapeHtml(label)}</span></div>
      `).join("");
    }
  }

  function renderBreakdowns() {
    const active = activeCards();
    const setCounts = aggregateBy(active, card => card.set || "Sin edicion", card => number(card.qty || 1));
    const setSpend = aggregateBy(active, card => card.set || "Sin edicion", card => number(card.totalBuyPrice));
    const cardSpend = aggregateBy(active, card => card.lookupName || card.name || "Sin nombre", card => number(card.totalBuyPrice));
    if (el("setCount")) el("setCount").textContent = new Set(active.map(card => card.set).filter(Boolean)).size.toLocaleString("es-ES");
    renderBarList("setBreakdown", setCounts, { formatter: value => Math.round(value).toLocaleString("es-ES"), onClickType: "set" });
    renderBarList("setSpendBreakdown", setSpend, { formatter: money, onClickType: "set" });
    renderBarList("cardSpendBreakdown", cardSpend, { formatter: money, onClickType: "name" });
    setupBarClicks();
  }

  function resetAndRender() {
    state.page = 1;
    renderCards();
  }

  function setupFilters() {
    populateSelect(el("setFilter"), cards.map(card => card.set), "Todas las ediciones");
    populateSelect(el("tcgFilter"), cards.map(card => card.tcg || "Sin TCG"), "Todos los TCG");
    populateSelect(el("languageFilter"), cards.map(card => card.language), "Todos los idiomas");
    populateSelect(el("statusFilter"), cards.map(card => card.status), "Todos los estados");
    populateSelect(el("operationFilter"), cards.map(card => card.operationType), "Todas las operaciones");
    populateSelect(el("conditionFilter"), cards.map(card => card.condition), "Todas las condiciones");

    el("searchInput")?.addEventListener("input", event => { state.query = event.target.value.trim(); resetAndRender(); });
    el("setFilter")?.addEventListener("change", event => { state.set = event.target.value; resetAndRender(); });
    el("tcgFilter")?.addEventListener("change", event => { state.tcg = event.target.value; resetAndRender(); });
    el("languageFilter")?.addEventListener("change", event => { state.language = event.target.value; resetAndRender(); });
    el("statusFilter")?.addEventListener("change", event => { state.status = event.target.value; resetAndRender(); });
    el("operationFilter")?.addEventListener("change", event => { state.operation = event.target.value; resetAndRender(); });
    el("conditionFilter")?.addEventListener("change", event => { state.condition = event.target.value; resetAndRender(); });

    document.querySelectorAll(".tab").forEach(button => {
      button.addEventListener("click", () => {
        document.querySelectorAll(".tab").forEach(tab => tab.classList.remove("active"));
        button.classList.add("active");
        state.tab = button.dataset.tab || "all";
        resetAndRender();
      });
    });

    el("sortSelect")?.addEventListener("change", event => { state.sortKey = event.target.value; resetAndRender(); });
    el("sortDirButton")?.addEventListener("click", () => {
      state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
      el("sortDirButton").textContent = state.sortDir === "asc" ? "Asc" : "Desc";
      resetAndRender();
    });
    el("pageSizeSelect")?.addEventListener("change", event => {
      state.pageSize = Number(event.target.value) || 20;
      resetAndRender();
    });
    el("prevPage")?.addEventListener("click", () => {
      if (state.page > 1) {
        state.page -= 1;
        renderCards({ scroll: true });
      }
    });
    el("nextPage")?.addEventListener("click", () => {
      state.page += 1;
      renderCards({ scroll: true });
    });

    const lookupButton = el("imageLookupButton");
    if (lookupButton) lookupButton.addEventListener("click", () => queueVisibleScryfallLookups({ manual: true, limit: state.pageSize }));
  }

  function matches(card) {
    const haystack = [
      card.name, card.lookupName, card.set, card.setCode, card.cardNumber,
      card.language, card.condition, card.status, card.tcg, card.operationType
    ].filter(Boolean).join(" ");
    if (state.query && !normalizeText(haystack).includes(normalizeText(state.query))) return false;
    if (state.set && card.set !== state.set) return false;
    if (state.tcg) {
      const tcg = card.tcg || "Sin TCG";
      if (tcg !== state.tcg) return false;
    }
    if (state.language && card.language !== state.language) return false;
    if (state.status && card.status !== state.status) return false;
    if (state.operation && card.operationType !== state.operation) return false;
    if (state.condition && card.condition !== state.condition) return false;
    if (state.tab !== "all") {
      if (state.tab === "review") return Boolean(card.needsReview || !card.image);
      return card.status === state.tab;
    }
    return true;
  }

  function sortValue(card, key) {
    if (key === "date") return dateValue(card.date);
    if (key === "totalBuyPrice") return number(card.totalBuyPrice);
    if (key === "buyPrice") return number(card.buyPrice);
    if (key === "qty") return number(card.qty || 1);
    if (key === "currentPrice") return number(card.currentPrice);
    if (key === "name") return normalizeText(card.lookupName || card.name);
    if (key === "set") return normalizeText(card.set);
    if (key === "status") return normalizeText(card.status);
    if (key === "language") return normalizeText(card.language);
    if (key === "tcg") return normalizeText(card.tcg || "Sin TCG");
    return normalizeText(card.name);
  }

  function sortCards(list) {
    const dir = state.sortDir === "asc" ? 1 : -1;
    return list.slice().sort((a, b) => {
      const aValue = sortValue(a, state.sortKey);
      const bValue = sortValue(b, state.sortKey);
      if (typeof aValue === "number" && typeof bValue === "number") {
        if (aValue === bValue) return a.__index - b.__index;
        return (aValue - bValue) * dir;
      }
      const compared = String(aValue).localeCompare(String(bValue), "es", { numeric: true });
      return compared === 0 ? a.__index - b.__index : compared * dir;
    });
  }

  function operationLabel(card) {
    if (card.operationType) return card.operationType;
    if (card.status === "Sold") return "Venta";
    if (card.status === "Holding") return "Compra";
    return safe(card.status);
  }

  function cardHtml(card) {
    const review = card.needsReview || !card.image;
    const img = card.image
      ? `<img class="card-image" loading="lazy" src="${escapeHtml(card.image)}" alt="${escapeHtml(card.name || "Carta")}">`
      : `<div class="card-placeholder">Sin imagen<br><small>Resolver Scryfall</small></div>`;
    const current = card.currentPrice === null || card.currentPrice === undefined ? "Pendiente" : money(card.currentPrice);
    const tcgChip = card.tcg ? `<span class="meta-chip">${escapeHtml(card.tcg)}</span>` : `<span class="meta-chip">Sin TCG</span>`;
    return `
      <article class="card ${review ? "needs-review" : ""}" data-index="${card.__index}">
        <div class="card-image-wrap">${img}</div>
        <div class="card-body">
          <h3 class="card-title">${escapeHtml(safe(card.name))}</h3>
          <div class="card-meta">
            <span class="meta-chip">${escapeHtml(safe(card.set))}</span>
            <span class="meta-chip">${escapeHtml(safe(card.language))}</span>
            <span class="meta-chip">${escapeHtml(safe(card.condition))}</span>
            <span class="meta-chip">x${escapeHtml(safe(card.qty, 1))}</span>
            <span class="meta-chip">${escapeHtml(operationLabel(card))}</span>
            ${tcgChip}
          </div>
          <div class="price-line">
            <div class="price-box"><span>Unitario</span><strong>${money(card.buyPrice)}</strong></div>
            <div class="price-box"><span>Total</span><strong>${money(card.totalBuyPrice)}</strong></div>
          </div>
          <div class="price-line">
            <div class="price-box"><span>Mercado</span><strong>${current}</strong></div>
            <div class="price-box"><span>Fecha</span><strong>${escapeHtml(card.date ? formatDate(card.date).split(",")[0] : "Pendiente")}</strong></div>
          </div>
          <div class="card-footer">
            ${review ? `<span class="review-dot" title="Necesita revision"></span>` : `<span class="meta-chip">${escapeHtml(safe(card.status))}</span>`}
            <button class="open-card" type="button" data-index="${card.__index}">Detalle</button>
          </div>
        </div>
      </article>
    `;
  }

  function updatePager(total) {
    const totalPages = Math.max(1, Math.ceil(total / state.pageSize));
    if (state.page > totalPages) state.page = totalPages;
    if (state.page < 1) state.page = 1;
    if (el("pageInfo")) el("pageInfo").textContent = `Pagina ${state.page.toLocaleString("es-ES")} de ${totalPages.toLocaleString("es-ES")}`;
    if (el("prevPage")) el("prevPage").disabled = state.page <= 1;
    if (el("nextPage")) el("nextPage").disabled = state.page >= totalPages;
  }

  function renderCards(options = {}) {
    const filtered = sortCards(cards.filter(matches));
    updatePager(filtered.length);
    const start = (state.page - 1) * state.pageSize;
    const shown = filtered.slice(start, start + state.pageSize);
    state.lastVisibleCards = shown;
    if (el("resultCount")) {
      const from = filtered.length ? start + 1 : 0;
      const to = Math.min(start + shown.length, filtered.length);
      el("resultCount").textContent = `${from.toLocaleString("es-ES")}-${to.toLocaleString("es-ES")} de ${filtered.length.toLocaleString("es-ES")} resultados`;
    }
    if (el("cardsGrid")) el("cardsGrid").innerHTML = shown.map(cardHtml).join("");
    if (el("emptyState")) el("emptyState").classList.toggle("hidden", filtered.length > 0);
    document.querySelectorAll(".open-card").forEach(button => {
      button.addEventListener("click", () => openModal(cards[Number(button.dataset.index)]));
    });
    if (options.scroll) document.getElementById("collection")?.scrollIntoView({ behavior: "smooth", block: "start" });
    queueVisibleScryfallLookups({ manual: false, limit: Math.min(10, state.pageSize) });
  }

  function renderReview() {
    const reviewCards = cards.filter(card => card.needsReview || !card.image);
    const rows = reviewCards.slice(0, 250);
    if (!el("reviewTableBody")) return;
    el("reviewTableBody").innerHTML = rows.length ? rows.map(card => {
      const reasons = [];
      if (!card.image) reasons.push("Sin imagen");
      if (card.needsReview) reasons.push("Matching pendiente/manual");
      if (card.scryfall && card.scryfall.matched === false) reasons.push(card.scryfall.matchedBy || "No encontrado en Scryfall");
      return `<tr><td>${escapeHtml(safe(card.name))}</td><td>${escapeHtml(safe(card.set))}</td><td>${escapeHtml(safe(card.language))}</td><td>${escapeHtml(reasons.join(", ") || "Revision")}</td><td>${escapeHtml(safe(card.source && card.source.row))}</td></tr>`;
    }).join("") + (reviewCards.length > rows.length ? `<tr><td colspan="5">Mostrando ${rows.length} de ${reviewCards.length}. Usa filtros o busqueda para acotar.</td></tr>` : "") : `<tr><td colspan="5">No hay elementos pendientes de revision.</td></tr>`;
  }

  function openModal(card) {
    if (!card || !el("cardModal")) return;
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
            <div><span>Operacion</span><strong>${escapeHtml(operationLabel(card))}</strong></div>
            <div><span>TCG</span><strong>${escapeHtml(safe(card.tcg, "Sin TCG"))}</strong></div>
            <div><span>Idioma</span><strong>${escapeHtml(safe(card.language))}</strong></div>
            <div><span>Condicion</span><strong>${escapeHtml(safe(card.condition))}</strong></div>
            <div><span>Cantidad</span><strong>${escapeHtml(safe(card.qty))}</strong></div>
            <div><span>Precio unidad</span><strong>${money(card.buyPrice)}</strong></div>
            <div><span>Importe total</span><strong>${money(card.totalBuyPrice)}</strong></div>
            <div><span>Mercado</span><strong>${money(card.currentPrice)}</strong></div>
            <div><span>Fecha</span><strong>${escapeHtml(formatDate(card.date))}</strong></div>
            <div><span>Scryfall match</span><strong>${card.scryfall && card.scryfall.matched ? "OK" : "Pendiente"} ${card.scryfall && card.scryfall.score ? "(" + card.scryfall.score + ")" : ""}</strong></div>
            <div><span>Fila Excel</span><strong>${escapeHtml(safe(card.source && card.source.row))}</strong></div>
          </div>
          <div class="modal-links">${links || "<span class='muted'>Sin enlaces externos.</span>"}</div>
        </div>
      </div>
    `;
    if (typeof modal.showModal === "function") modal.showModal();
  }

  function closeDialogOnBackdrop(dialog) {
    if (!dialog) return;
    dialog.addEventListener("click", event => {
      const rect = dialog.getBoundingClientRect();
      const inDialog = rect.top <= event.clientY && event.clientY <= rect.bottom && rect.left <= event.clientX && event.clientX <= rect.right;
      if (!inDialog) dialog.close();
    });
  }

  function setupModal() {
    el("closeModal")?.addEventListener("click", () => el("cardModal")?.close());
    closeDialogOnBackdrop(el("cardModal"));
  }

  function setupTheme() {
    const stored = localStorage.getItem("portfolio-theme");
    if (stored === "light") document.documentElement.classList.add("light");
    el("themeToggle")?.addEventListener("click", () => {
      document.documentElement.classList.toggle("light");
      localStorage.setItem("portfolio-theme", document.documentElement.classList.contains("light") ? "light" : "dark");
    });
  }

  function setupNav() {
    const menuDialog = el("menuDialog");
    el("menuButton")?.addEventListener("click", () => {
      if (menuDialog && typeof menuDialog.showModal === "function") menuDialog.showModal();
    });
    el("closeMenu")?.addEventListener("click", () => menuDialog?.close());
    closeDialogOnBackdrop(menuDialog);
    document.querySelectorAll(".nav-link").forEach(link => {
      link.addEventListener("click", () => {
        document.querySelectorAll(".nav-link").forEach(item => item.classList.remove("active"));
        link.classList.add("active");
        menuDialog?.close();
      });
    });
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
    const article = document.querySelector(`.card[data-index="${card.__index}"]`);
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
        cards.filter(item => !item.image && cacheKeyFor(item) === key).forEach(item => applyRuntimeImage(item, result));
      }
      setLookupStatus(`Consultando Scryfall: ${i + 1}/${queue.length} - ${ok} imagenes`);
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
    renderBreakdowns();
    setupFilters();
    setupTheme();
    setupNav();
    setupModal();
    renderCards();
    renderReview();
  }

  init();
})();
