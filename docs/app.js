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
    lookupRunning: false,
    lastVisibleCards: []
  };

  const CACHE_KEY = "coleccion-scryfall-runtime-cache-v2";
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

  function intFormat(value) {
    return Number(value || 0).toLocaleString("es-ES");
  }

  function formatDate(value, compact = false) {
    if (!value) return "Pendiente";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return new Intl.DateTimeFormat("es-ES", compact ? {
      year: "2-digit", month: "2-digit", day: "2-digit"
    } : {
      year: "numeric", month: "2-digit", day: "2-digit"
    }).format(date);
  }

  function monthKey(value) {
    const date = value ? new Date(value) : null;
    if (!date || Number.isNaN(date.getTime())) return "Sin fecha";
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
  }

  function valueOf(card) {
    const total = number(card.totalBuyPrice);
    return total || number(card.buyPrice) * Math.max(1, number(card.qty));
  }

  function currentValueOf(card) {
    if (card.currentPrice === null || card.currentPrice === undefined || card.currentPrice === "") return null;
    const current = number(card.currentPrice);
    if (!current) return null;
    return current * Math.max(1, number(card.qty));
  }

  function operationLabel(card) {
    return safe(card.operationType || (isSold(card) ? "Venta" : "Compra"));
  }

  function isSold(card) {
    const status = normalizeText(card.status);
    const operation = normalizeText(card.operationType);
    return status === "sold" || status === "vendido" || operation === "venta";
  }

  function isCancelled(card) {
    const status = normalizeText(card.status);
    const operation = normalizeText(card.operationType);
    return status === "cancelado" || status === "cancelled" || operation === "cancelado" || operation === "cancelled";
  }

  function isActive(card) {
    return !isSold(card) && !isCancelled(card);
  }

  function isReview(card) {
    return Boolean(card.needsReview || !getImage(card) || (card.scryfall && card.scryfall.matched === false));
  }

  function getImage(card) {
    return card.image || (card.imageUrls && (card.imageUrls.normal || card.imageUrls.large || card.imageUrls.small || card.imageUrls.png)) || null;
  }

  function cleanLookupName(value) {
    return String(value || "")
      .replace(/\s*\[(playset|set|lot)\]\s*$/i, "")
      .replace(/\s*\(v\.?\s*\d+\)\s*$/i, "")
      .trim();
  }

  function initials(value) {
    const parts = String(value || "TCG").replace(/\[[^\]]+\]/g, "").split(/\s+/).filter(Boolean).slice(0, 2);
    return (parts.map(part => part[0]).join("") || "TCG").toUpperCase();
  }

  function buildSummary() {
    const active = cards.filter(isActive);
    const sold = cards.filter(isSold);
    const cancelled = cards.filter(isCancelled);
    const marketCards = active.map(currentValueOf).filter(value => value !== null);
    const activeUnits = active.reduce((sum, card) => sum + number(card.qty), 0);
    const soldUnits = sold.reduce((sum, card) => sum + number(card.qty), 0);
    const investedActive = active.reduce((sum, card) => sum + valueOf(card), 0);
    const soldAmount = sold.reduce((sum, card) => sum + valueOf(card), 0);
    const grossVolume = cards.reduce((sum, card) => sum + valueOf(card), 0);
    const uniqueSets = new Set(cards.map(card => safe(card.set, "Sin edicion")).filter(Boolean));
    const uniqueTcg = new Set(cards.map(card => safe(card.tcg, "Sin TCG")).filter(Boolean));

    return {
      rows: cards.length,
      activeRows: active.length,
      soldRows: sold.length,
      cancelledRows: cancelled.length,
      activeUnits,
      soldUnits,
      investedActive,
      soldAmount,
      grossVolume,
      netBalance: soldAmount - investedActive,
      marketValue: marketCards.length ? marketCards.reduce((sum, value) => sum + value, 0) : null,
      marketCount: marketCards.length,
      needsReview: cards.filter(isReview).length,
      missingImages: cards.filter(card => !getImage(card)).length,
      uniqueSets: uniqueSets.size,
      uniqueTcg: uniqueTcg.size
    };
  }

  function populateSelect(selectEl, values, label) {
    if (!selectEl) return;
    const current = selectEl.value;
    selectEl.innerHTML = `<option value="">${escapeHtml(label)}</option>`;
    [...new Set(values.filter(value => value !== null && value !== undefined && value !== "").map(String))]
      .sort((a, b) => a.localeCompare(b, "es"))
      .forEach(value => {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = value;
        selectEl.appendChild(option);
      });
    selectEl.value = current;
  }

  function setText(id, value) {
    const node = el(id);
    if (node) node.textContent = value;
  }

  function renderSummary() {
    const summary = buildSummary();
    const updated = formatDate(data.updatedAt);
    setText("headerUpdatedAt", updated);
    setText("menuUpdatedAt", updated);
    setText("heroRows", intFormat(summary.rows));
    setText("heroEditions", intFormat(summary.uniqueSets));
    setText("heroTcg", intFormat(summary.uniqueTcg));
    setText("heroDatasetState", summary.rows ? "Activo" : "Sin datos");

    setText("kpiActiveUnits", intFormat(summary.activeUnits));
    setText("kpiInvestedActive", money(summary.investedActive));
    setText("kpiSoldAmount", money(summary.soldAmount));
    setText("kpiNetBalance", money(summary.netBalance));
    setText("kpiMarketValue", summary.marketValue === null ? "Pendiente" : money(summary.marketValue));
    setText("kpiNeedsReview", intFormat(summary.needsReview));

    const netMetric = el("netMetric");
    if (netMetric) {
      netMetric.classList.toggle("positive", summary.netBalance >= 0);
      netMetric.classList.toggle("negative", summary.netBalance < 0);
    }

    const health = [
      ["Filas", summary.rows],
      ["Activas", summary.activeRows],
      ["Vendidas", summary.soldRows],
      ["Canceladas", summary.cancelledRows],
      ["Sin imagen", summary.missingImages],
      ["Con precio", summary.marketCount]
    ];
    const healthNode = el("dataHealth");
    if (healthNode) {
      healthNode.innerHTML = health.map(([label, value]) => `
        <div class="health-item"><strong>${intFormat(value)}</strong><span>${escapeHtml(label)}</span></div>
      `).join("");
    }
  }

  function aggregate(items, keyFn, valueFn) {
    const map = new Map();
    for (const item of items) {
      const key = keyFn(item) || "Sin dato";
      map.set(key, (map.get(key) || 0) + valueFn(item));
    }
    return [...map.entries()].sort((a, b) => b[1] - a[1]);
  }

  function renderBars(id, entries, options = {}) {
    const node = el(id);
    if (!node) return;
    const limit = options.limit || 8;
    const shown = entries.slice(0, limit);
    const max = shown.length ? Math.max(...shown.map(entry => Math.abs(entry[1]))) : 0;
    if (!shown.length) {
      node.innerHTML = `<p class="muted">Sin datos todavia.</p>`;
      return;
    }
    node.innerHTML = shown.map(([name, value]) => {
      const width = max ? Math.max(4, Math.round((Math.abs(value) / max) * 100)) : 0;
      const formatted = options.money ? money(value) : intFormat(value);
      const action = options.action ? ` data-action="${escapeHtml(options.action)}" data-value="${escapeHtml(name)}"` : "";
      return `
        <div class="bar-row ${options.action ? "clickable" : ""}"${action} title="${escapeHtml(name)}">
          <div class="bar-name">${escapeHtml(name)}</div>
          <div class="bar-track"><div class="bar-fill" style="--width:${width}%"></div></div>
          <strong>${escapeHtml(formatted)}</strong>
        </div>
      `;
    }).join("");
  }

  function renderAnalytics() {
    const active = cards.filter(isActive);
    const setCounts = aggregate(active, card => safe(card.set, "Sin edicion"), card => number(card.qty));
    const setSpend = aggregate(cards, card => safe(card.set, "Sin edicion"), valueOf);
    const cardSpend = aggregate(cards, card => safe(card.name, "Sin carta"), valueOf);
    const operationSpend = aggregate(cards, operationLabel, valueOf);

    setText("setCount", intFormat(setCounts.length));
    renderBars("setCountBreakdown", setCounts, { action: "set" });
    renderBars("setSpendBreakdown", setSpend, { money: true, action: "set" });
    renderBars("cardSpendBreakdown", cardSpend, { money: true, action: "query", limit: 8 });
    renderBars("operationBreakdown", operationSpend, { money: true, action: "operation", limit: 6 });
    renderMonthlyFlow();
  }

  function renderMonthlyFlow() {
    const node = el("monthlyFlow");
    if (!node) return;
    const map = new Map();
    for (const card of cards) {
      const key = monthKey(card.date);
      if (key === "Sin fecha") continue;
      if (!map.has(key)) map.set(key, { buy: 0, sell: 0 });
      const item = map.get(key);
      if (isSold(card)) item.sell += valueOf(card);
      else item.buy += valueOf(card);
    }
    const entries = [...map.entries()].sort((a, b) => a[0].localeCompare(b[0])).slice(-12);
    const max = entries.length ? Math.max(...entries.flatMap(entry => [entry[1].buy, entry[1].sell])) : 0;
    if (!entries.length) {
      node.innerHTML = `<p class="muted">Sin fechas disponibles.</p>`;
      return;
    }
    node.innerHTML = entries.map(([key, values]) => {
      const buyHeight = max ? Math.max(2, Math.round((values.buy / max) * 100)) : 2;
      const sellHeight = max ? Math.max(2, Math.round((values.sell / max) * 100)) : 2;
      const label = key.slice(5) + "/" + key.slice(2, 4);
      return `
        <div class="month-column" title="${escapeHtml(key)} - Compra ${escapeHtml(money(values.buy))} / Venta ${escapeHtml(money(values.sell))}">
          <div class="month-bars">
            <div class="month-bar buy" style="height:${buyHeight}%"></div>
            <div class="month-bar sell" style="height:${sellHeight}%"></div>
          </div>
          <div class="month-label">${escapeHtml(label)}</div>
        </div>
      `;
    }).join("");
  }

  function renderWatchlist() {
    const node = el("watchlistCarousel");
    if (!node) return;
    const watchlist = cards.filter(card => normalizeText(card.status) === "watchlist");
    const source = watchlist.length ? watchlist : cards.filter(isActive).sort((a, b) => valueOf(b) - valueOf(a)).slice(0, 18);
    setText("watchlistCount", intFormat(source.length));
    if (!source.length) {
      node.innerHTML = `<p class="muted">Sin elementos destacados.</p>`;
      return;
    }
    node.innerHTML = source.map(card => {
      const image = getImage(card);
      const thumb = image
        ? `<img loading="lazy" src="${escapeHtml(image)}" alt="${escapeHtml(safe(card.name, "Carta"))}">`
        : `<span>Sin imagen</span>`;
      return `
        <button class="watch-card" type="button" data-index="${card.__index}">
          <span class="watch-thumb">${thumb}</span>
          <span class="watch-body">
            <strong>${escapeHtml(safe(card.name))}</strong>
            <span>${escapeHtml(safe(card.set, "Sin edicion"))}</span>
            <span>${escapeHtml(operationLabel(card))} · x${escapeHtml(safe(card.qty, 1))}</span>
            <em>${escapeHtml(money(valueOf(card)))}</em>
          </span>
        </button>
      `;
    }).join("");
    node.querySelectorAll(".watch-card").forEach(button => {
      button.addEventListener("click", () => openModal(cards[Number(button.dataset.index)]));
    });
  }

  function setupFilters() {
    populateSelect(el("setFilter"), cards.map(card => card.set), "Todas las ediciones");
    populateSelect(el("tcgFilter"), cards.map(card => card.tcg || "Sin TCG"), "Todos los TCG");
    populateSelect(el("languageFilter"), cards.map(card => card.language), "Todos los idiomas");
    populateSelect(el("statusFilter"), cards.map(card => card.status), "Todos los estados");
    populateSelect(el("operationFilter"), cards.map(operationLabel), "Todas las operaciones");
    populateSelect(el("conditionFilter"), cards.map(card => card.condition), "Todas las condiciones");

    const inputs = [
      ["searchInput", "query", event => event.target.value],
      ["setFilter", "set", event => event.target.value],
      ["tcgFilter", "tcg", event => event.target.value],
      ["languageFilter", "language", event => event.target.value],
      ["statusFilter", "status", event => event.target.value],
      ["operationFilter", "operation", event => event.target.value],
      ["conditionFilter", "condition", event => event.target.value]
    ];
    inputs.forEach(([id, key, reader]) => {
      el(id)?.addEventListener(id === "searchInput" ? "input" : "change", event => {
        state[key] = reader(event);
        state.page = 1;
        renderCollection({ scroll: false });
      });
    });

    document.querySelectorAll(".filter-chip").forEach(button => {
      button.addEventListener("click", () => {
        document.querySelectorAll(".filter-chip").forEach(item => item.classList.remove("active"));
        button.classList.add("active");
        state.tab = button.dataset.tab || "all";
        state.page = 1;
        renderCollection({ scroll: false });
      });
    });

    el("sortSelect")?.addEventListener("change", event => {
      state.sortKey = event.target.value;
      state.page = 1;
      renderCollection({ scroll: false });
    });
    el("sortDirButton")?.addEventListener("click", () => {
      state.sortDir = state.sortDir === "desc" ? "asc" : "desc";
      setText("sortDirButton", state.sortDir === "desc" ? "Desc" : "Asc");
      renderCollection({ scroll: false });
    });
    el("pageSizeSelect")?.addEventListener("change", event => {
      state.pageSize = Number(event.target.value) || 20;
      state.page = 1;
      renderCollection({ scroll: false });
    });
    el("prevPage")?.addEventListener("click", () => {
      if (state.page > 1) {
        state.page -= 1;
        renderCollection({ scroll: true });
      }
    });
    el("nextPage")?.addEventListener("click", () => {
      state.page += 1;
      renderCollection({ scroll: true });
    });

    document.querySelectorAll("[data-summary-filter]").forEach(node => {
      node.addEventListener("click", () => applySummaryFilter(node.dataset.summaryFilter));
    });

    document.addEventListener("click", event => {
      const row = event.target.closest("[data-action]");
      if (!row) return;
      const action = row.dataset.action;
      const value = row.dataset.value || "";
      if (action === "set") applyFieldFilter("set", value);
      if (action === "operation") applyFieldFilter("operation", value);
      if (action === "query") applyQuery(value);
    });

    el("imageLookupButton")?.addEventListener("click", () => queueVisibleScryfallLookups({ manual: true, limit: Math.min(80, state.pageSize) }));
  }

  function applySummaryFilter(kind) {
    if (kind === "active") {
      state.tab = "active";
      clearExplicitFilters();
    } else if (kind === "sold") {
      state.tab = "Sold";
      clearExplicitFilters();
    } else if (kind === "buy") {
      state.tab = "active";
      state.operation = "Compra";
      if (el("operationFilter")) el("operationFilter").value = "Compra";
    } else if (kind === "review") {
      state.tab = "review";
      clearExplicitFilters();
    }
    document.querySelectorAll(".filter-chip").forEach(button => button.classList.toggle("active", button.dataset.tab === state.tab));
    state.page = 1;
    renderCollection({ scroll: true });
  }

  function clearExplicitFilters() {
    state.set = "";
    state.tcg = "";
    state.language = "";
    state.status = "";
    state.operation = "";
    state.condition = "";
    ["setFilter", "tcgFilter", "languageFilter", "statusFilter", "operationFilter", "conditionFilter"].forEach(id => {
      if (el(id)) el(id).value = "";
    });
  }

  function applyFieldFilter(field, value) {
    clearExplicitFilters();
    state.tab = "all";
    document.querySelectorAll(".filter-chip").forEach(button => button.classList.toggle("active", button.dataset.tab === "all"));
    state[field] = value;
    const id = field === "set" ? "setFilter" : field === "operation" ? "operationFilter" : null;
    if (id && el(id)) el(id).value = value;
    state.page = 1;
    renderCollection({ scroll: true });
  }

  function applyQuery(value) {
    clearExplicitFilters();
    state.tab = "all";
    state.query = value;
    if (el("searchInput")) el("searchInput").value = value;
    document.querySelectorAll(".filter-chip").forEach(button => button.classList.toggle("active", button.dataset.tab === "all"));
    state.page = 1;
    renderCollection({ scroll: true });
  }

  function matches(card) {
    const query = normalizeText(state.query);
    const haystack = normalizeText([
      card.name, card.lookupName, card.set, card.setCode, card.cardNumber, card.language,
      card.condition, card.status, card.tcg || "Sin TCG", operationLabel(card), card.date
    ].filter(Boolean).join(" "));
    if (query && !haystack.includes(query)) return false;
    if (state.set && card.set !== state.set) return false;
    if (state.tcg && safe(card.tcg, "Sin TCG") !== state.tcg) return false;
    if (state.language && card.language !== state.language) return false;
    if (state.status && card.status !== state.status) return false;
    if (state.operation && operationLabel(card) !== state.operation) return false;
    if (state.condition && card.condition !== state.condition) return false;

    if (state.tab === "active") return isActive(card);
    if (state.tab === "review") return isReview(card);
    if (state.tab === "Holding") return normalizeText(card.status) === "holding";
    if (state.tab === "Sold") return isSold(card);
    if (state.tab === "Cancelado") return isCancelled(card);
    return true;
  }

  function sortValue(card, key) {
    if (key === "date") {
      const date = new Date(card.date || 0);
      return Number.isNaN(date.getTime()) ? 0 : date.getTime();
    }
    if (key === "totalBuyPrice") return valueOf(card);
    if (key === "buyPrice") return number(card.buyPrice);
    if (key === "currentPrice") return number(card.currentPrice);
    if (key === "qty") return number(card.qty);
    if (key === "operation") return operationLabel(card).toLowerCase();
    return safe(card[key], "").toLowerCase();
  }

  function sortedCards(items) {
    const dir = state.sortDir === "desc" ? -1 : 1;
    return [...items].sort((a, b) => {
      const av = sortValue(a, state.sortKey);
      const bv = sortValue(b, state.sortKey);
      if (typeof av === "number" && typeof bv === "number") return (av - bv) * dir;
      return String(av).localeCompare(String(bv), "es") * dir;
    });
  }

  function statusClass(card) {
    if (isSold(card)) return "bad";
    if (isCancelled(card)) return "warn";
    if (isActive(card)) return "good";
    return "";
  }

  function cardHtml(card) {
    const image = getImage(card);
    const review = isReview(card);
    const imageHtml = image
      ? `<img class="card-image" loading="lazy" src="${escapeHtml(image)}" alt="${escapeHtml(safe(card.name, "Carta"))}">`
      : `<div class="card-placeholder"><b>${escapeHtml(initials(card.name))}</b><small>Sin imagen</small></div>`;
    const market = currentValueOf(card);
    const status = safe(card.status, isSold(card) ? "Sold" : "Holding");
    return `
      <article class="card ${review ? "needs-review" : ""} ${isSold(card) ? "sold" : ""}" data-index="${card.__index}">
        <div class="card-image-wrap">${imageHtml}</div>
        <div class="card-body">
          <h3 class="card-title">${escapeHtml(safe(card.name))}</h3>
          <div class="card-meta">
            <span class="meta-chip ${statusClass(card)}">${escapeHtml(status)}</span>
            <span class="meta-chip">${escapeHtml(operationLabel(card))}</span>
            <span class="meta-chip">x${escapeHtml(safe(card.qty, 1))}</span>
            <span class="meta-chip">${escapeHtml(safe(card.language))}</span>
            <span class="meta-chip">${escapeHtml(safe(card.condition))}</span>
            ${card.tcg ? `<span class="meta-chip">${escapeHtml(card.tcg)}</span>` : ""}
          </div>
          <div class="card-meta">
            <span class="meta-chip" title="${escapeHtml(safe(card.set, "Sin edicion"))}">${escapeHtml(safe(card.set, "Sin edicion"))}</span>
          </div>
          <div class="price-line">
            <div class="price-box"><span>Unidad</span><strong>${escapeHtml(money(card.buyPrice))}</strong></div>
            <div class="price-box"><span>Total</span><strong>${escapeHtml(money(valueOf(card)))}</strong></div>
          </div>
          <div class="card-footer">
            ${review ? `<span class="review-dot" title="Necesita revision"></span>` : `<span class="meta-chip">${escapeHtml(formatDate(card.date, true))}</span>`}
            <button class="open-card" type="button" data-index="${card.__index}">Detalle</button>
          </div>
          ${market !== null ? `<div class="card-footer"><span class="meta-chip good">Mercado ${escapeHtml(money(market))}</span></div>` : ""}
        </div>
      </article>
    `;
  }

  function renderCollection(options = {}) {
    const filtered = sortedCards(cards.filter(matches));
    const totalPages = Math.max(1, Math.ceil(filtered.length / state.pageSize));
    if (state.page > totalPages) state.page = totalPages;
    if (state.page < 1) state.page = 1;
    const start = (state.page - 1) * state.pageSize;
    const shown = filtered.slice(start, start + state.pageSize);
    state.lastVisibleCards = shown;

    if (el("cardsGrid")) el("cardsGrid").innerHTML = shown.map(cardHtml).join("");
    if (el("emptyState")) el("emptyState").classList.toggle("hidden", filtered.length > 0);
    const from = filtered.length ? start + 1 : 0;
    const to = Math.min(start + shown.length, filtered.length);
    setText("resultCount", `${intFormat(from)}-${intFormat(to)} de ${intFormat(filtered.length)} resultados`);
    setText("pageInfo", `Pagina ${intFormat(state.page)} de ${intFormat(totalPages)}`);
    if (el("prevPage")) el("prevPage").disabled = state.page <= 1;
    if (el("nextPage")) el("nextPage").disabled = state.page >= totalPages;

    document.querySelectorAll(".open-card").forEach(button => {
      button.addEventListener("click", () => openModal(cards[Number(button.dataset.index)]));
    });

    if (options.scroll) document.getElementById("collection")?.scrollIntoView({ behavior: "smooth", block: "start" });
    queueVisibleScryfallLookups({ manual: false, limit: Math.min(8, shown.length) });
  }

  function renderReview() {
    const reviewCards = cards.filter(isReview);
    const rows = reviewCards.slice(0, 250);
    const node = el("reviewTableBody");
    if (!node) return;
    if (!rows.length) {
      node.innerHTML = `<tr><td colspan="5">No hay elementos pendientes de revision.</td></tr>`;
      return;
    }
    node.innerHTML = rows.map(card => {
      const reasons = [];
      if (!getImage(card)) reasons.push("Sin imagen");
      if (card.needsReview) reasons.push("Matching pendiente");
      if (card.scryfall && card.scryfall.matched === false) reasons.push(card.scryfall.matchedBy || "No encontrado");
      return `
        <tr>
          <td>${escapeHtml(safe(card.name))}</td>
          <td>${escapeHtml(safe(card.set))}</td>
          <td>${escapeHtml(safe(card.language))}</td>
          <td>${escapeHtml(reasons.join(", ") || "Revision")}</td>
          <td>${escapeHtml(safe(card.source && card.source.row))}</td>
        </tr>
      `;
    }).join("") + (reviewCards.length > rows.length ? `<tr><td colspan="5">Mostrando ${rows.length} de ${reviewCards.length}. Usa la coleccion para filtrar.</td></tr>` : "");
  }

  function openModal(card) {
    if (!card) return;
    const modal = el("cardModal");
    const body = el("modalBody");
    if (!modal || !body) return;
    const image = getImage(card);
    const imageHtml = image
      ? `<img src="${escapeHtml(image)}" alt="${escapeHtml(safe(card.name, "Carta"))}">`
      : `<div class="card-placeholder"><b>${escapeHtml(initials(card.name))}</b><small>Sin imagen</small></div>`;
    const market = currentValueOf(card);
    const links = [
      card.scryfallUrl ? `<a href="${escapeHtml(card.scryfallUrl)}" target="_blank" rel="noreferrer">Scryfall</a>` : "",
      card.cardmarketUrl ? `<a href="${escapeHtml(card.cardmarketUrl)}" target="_blank" rel="noreferrer">Cardmarket</a>` : ""
    ].filter(Boolean).join("");

    body.innerHTML = `
      <div class="modal-layout">
        <div class="modal-image-stage">${imageHtml}</div>
        <div class="modal-content">
          <p class="eyebrow">Detalle de carta</p>
          <h3>${escapeHtml(safe(card.name))}</h3>
          <p class="modal-subtitle">${escapeHtml(safe(card.set, "Sin edicion"))} ${card.cardNumber ? "- #" + escapeHtml(card.cardNumber) : ""}</p>
          <div class="modal-stats">
            <div class="modal-stat"><span>Unidad</span><strong>${escapeHtml(money(card.buyPrice))}</strong></div>
            <div class="modal-stat"><span>Total</span><strong>${escapeHtml(money(valueOf(card)))}</strong></div>
            <div class="modal-stat"><span>Mercado</span><strong>${escapeHtml(market === null ? "Pendiente" : money(market))}</strong></div>
          </div>
          <div class="modal-list">
            <div><span>Estado</span><strong>${escapeHtml(safe(card.status))}</strong></div>
            <div><span>Operacion</span><strong>${escapeHtml(operationLabel(card))}</strong></div>
            <div><span>TCG</span><strong>${escapeHtml(safe(card.tcg, "Sin TCG"))}</strong></div>
            <div><span>Idioma</span><strong>${escapeHtml(safe(card.language))}</strong></div>
            <div><span>Condicion</span><strong>${escapeHtml(safe(card.condition))}</strong></div>
            <div><span>Cantidad</span><strong>${escapeHtml(safe(card.qty))}</strong></div>
            <div><span>Fecha</span><strong>${escapeHtml(formatDate(card.date))}</strong></div>
            <div><span>Scryfall</span><strong>${card.scryfall && card.scryfall.matched ? "OK" : "Pendiente"}</strong></div>
            <div><span>Fila Excel</span><strong>${escapeHtml(safe(card.source && card.source.row))}</strong></div>
          </div>
          <div class="modal-links">${links || "<span class='muted'>Sin enlaces externos.</span>"}</div>
        </div>
      </div>
    `;
    if (typeof modal.showModal === "function") modal.showModal();
  }

  function openMetrics(title, rows) {
    const dialog = el("metricsDialog");
    if (!dialog) return;
    setText("metricsTitle", title);
    const body = el("metricsBody");
    if (body) {
      body.innerHTML = `<div class="metrics-list">${rows.map(([label, value]) => `
        <div class="metrics-row"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>
      `).join("")}</div>`;
    }
    if (typeof dialog.showModal === "function") dialog.showModal();
  }

  function setupMetricsModal() {
    el("closeMetrics")?.addEventListener("click", () => el("metricsDialog")?.close());
    el("netMetric")?.addEventListener("click", () => {
      const summary = buildSummary();
      openMetrics("Balance operativo", [
        ["Invertido activo", money(summary.investedActive)],
        ["Ventas registradas", money(summary.soldAmount)],
        ["Balance", money(summary.netBalance)],
        ["Volumen total", money(summary.grossVolume)]
      ]);
    });
  }

  function closeDialogOnBackdrop(dialog) {
    if (!dialog) return;
    dialog.addEventListener("click", event => {
      const rect = dialog.getBoundingClientRect();
      const inDialog = rect.top <= event.clientY && event.clientY <= rect.bottom && rect.left <= event.clientX && event.clientX <= rect.right;
      if (!inDialog) dialog.close();
    });
  }

  function setupDialogs() {
    el("closeModal")?.addEventListener("click", () => el("cardModal")?.close());
    closeDialogOnBackdrop(el("cardModal"));
    closeDialogOnBackdrop(el("metricsDialog"));

    const menu = el("menuDialog");
    el("menuButton")?.addEventListener("click", () => {
      if (menu && typeof menu.showModal === "function") menu.showModal();
    });
    el("closeMenu")?.addEventListener("click", () => menu?.close());
    closeDialogOnBackdrop(menu);

    document.querySelectorAll(".menu-link").forEach(link => {
      link.addEventListener("click", () => {
        document.querySelectorAll(".menu-link").forEach(item => item.classList.remove("active"));
        link.classList.add("active");
        menu?.close();
      });
    });

    document.addEventListener("keydown", event => {
      if (event.key === "Escape") {
        el("cardModal")?.close();
        el("metricsDialog")?.close();
        menu?.close();
      }
    });
  }

  function setupTheme() {
    const stored = localStorage.getItem("portfolio-theme");
    if (stored === "light") document.documentElement.classList.add("light");
    el("themeToggle")?.addEventListener("click", () => {
      document.documentElement.classList.toggle("light");
      localStorage.setItem("portfolio-theme", document.documentElement.classList.contains("light") ? "light" : "dark");
    });
  }

  function cacheKeyFor(card) {
    return [cleanLookupName(card.lookupName || card.name), card.setCode || card.set || "", card.cardNumber || "", card.language || ""].map(normalizeText).join("|");
  }

  function loadRuntimeCache() {
    try { return JSON.parse(localStorage.getItem(CACHE_KEY) || "{}"); }
    catch (_) { return {}; }
  }

  function saveRuntimeCache(cache) {
    try { localStorage.setItem(CACHE_KEY, JSON.stringify(cache)); }
    catch (_) { /* cache may be full or disabled */ }
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

  function imageFromScryfallPayload(payload, matchedBy = "browser-runtime") {
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
        matchedBy,
        score: matchedBy.includes("set") ? 95 : 60,
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

  function scryfallLang(value) {
    const key = normalizeText(value);
    const map = {
      "ingles": "en", "english": "en",
      "japones": "ja", "japanese": "ja",
      "espanol": "es", "spanish": "es",
      "chino s": "zhs", "chinese": "zhs", "simplified chinese": "zhs",
      "chino t": "zht", "traditional chinese": "zht",
      "italiano": "it", "italian": "it",
      "frances": "fr", "french": "fr",
      "aleman": "de", "german": "de",
      "ruso": "ru", "russian": "ru"
    };
    return map[key] || "";
  }

  async function lookupScryfall(card) {
    const name = cleanLookupName(card.lookupName || card.name);
    if (!name || isLikelyNonMtg(card)) return { notFound: true, reason: "skip-non-mtg" };

    const setCode = String(card.setCode || "").trim().toLowerCase();
    const collectorNumber = String(card.cardNumber || "").trim();
    if (setCode && collectorNumber) {
      const lang = scryfallLang(card.language);
      const exactUrls = [];
      if (lang) exactUrls.push(`https://api.scryfall.com/cards/${encodeURIComponent(setCode)}/${encodeURIComponent(collectorNumber)}/${encodeURIComponent(lang)}`);
      exactUrls.push(`https://api.scryfall.com/cards/${encodeURIComponent(setCode)}/${encodeURIComponent(collectorNumber)}`);
      for (const url of exactUrls) {
        const payload = await fetchJsonWithTimeout(url);
        const result = imageFromScryfallPayload(payload, "browser-runtime-set-collector");
        if (result) return result;
      }
    }

    if (setCode) {
      const escapedName = name.replace(/"/g, "\"");
      const query = `!"${escapedName}" set:${setCode}`;
      const searchUrl = `https://api.scryfall.com/cards/search?unique=prints&order=set&q=${encodeURIComponent(query)}`;
      const payload = await fetchJsonWithTimeout(searchUrl);
      const first = payload && Array.isArray(payload.data) ? payload.data[0] : null;
      const result = imageFromScryfallPayload(first, "browser-runtime-set-search");
      if (result) return result;
    }

    const exactUrl = `https://api.scryfall.com/cards/named?exact=${encodeURIComponent(name)}`;
    let payload = await fetchJsonWithTimeout(exactUrl);
    let result = imageFromScryfallPayload(payload, "browser-runtime-name-exact");
    if (result) return result;
    const fuzzyUrl = `https://api.scryfall.com/cards/named?fuzzy=${encodeURIComponent(name)}`;
    payload = await fetchJsonWithTimeout(fuzzyUrl);
    result = imageFromScryfallPayload(payload, "browser-runtime-name-fuzzy");
    return result || { notFound: true, reason: "not-found" };
  }

  function applyRuntimeImage(card, result) {
    if (!result || !result.image) return;
    card.image = result.image;
    card.imageUrls = result.imageUrls || card.imageUrls;
    card.scryfallUrl = result.scryfallUrl || card.scryfallUrl;
    card.scryfall = Object.assign({}, card.scryfall || {}, result.scryfall || {});
    card.needsReview = false;

    document.querySelectorAll(`.card[data-index="${card.__index}"]`).forEach(article => {
      article.classList.remove("needs-review");
      const imageWrap = article.querySelector(".card-image-wrap");
      if (imageWrap) imageWrap.innerHTML = `<img class="card-image" loading="lazy" src="${escapeHtml(card.image)}" alt="${escapeHtml(card.name || "Carta")}">`;
    });
  }

  async function queueVisibleScryfallLookups(options = {}) {
    const { manual = false, limit = 24 } = options;
    if (state.lookupRunning || typeof fetch !== "function") return;
    const cache = loadRuntimeCache();
    const queue = [];
    const seen = new Set();

    for (const card of state.lastVisibleCards) {
      if (!card || getImage(card)) continue;
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
      renderSummary();
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
        cards.filter(item => !getImage(item) && cacheKeyFor(item) === key).forEach(item => applyRuntimeImage(item, result));
      }
      setLookupStatus(`Consultando Scryfall: ${i + 1}/${queue.length} - ${ok} imagenes`);
      await new Promise(resolve => setTimeout(resolve, 160));
    }

    saveRuntimeCache(cache);
    state.lookupRunning = false;
    setLookupStatus(ok ? `Imagenes resueltas: ${ok}. Cache guardada en este navegador.` : "No se resolvieron imagenes en este lote.");
    renderSummary();
    renderWatchlist();
    renderReview();
  }

  function init() {
    renderSummary();
    renderAnalytics();
    renderWatchlist();
    setupFilters();
    setupDialogs();
    setupMetricsModal();
    setupTheme();
    renderCollection();
    renderReview();
  }

  init();
})();
