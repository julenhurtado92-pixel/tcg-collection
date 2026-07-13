(() => {
  'use strict';

  const sourceData = window.portfolioData || { metadata: {}, cards: [], transactions: [], stockLots: [], aggregates: {} };
  const initialWishlistData = window.wishlistData || { metadata: {}, items: [] };
  const metadata = sourceData.metadata || {};
  const CONFIG = {
    pageSize: 24,
    localCardsKey: 'tcgCollection.localCards.v2',
    cardOverridesKey: 'tcgCollection.cardOverrides.v1',
    wishlistKey: 'tcgCollection.wishlist.v2',
    themeKey: 'tcgCollection.theme',
    minUnitCost: Number(metadata.minUnitPurchaseValue ?? 10),
  };

  const formatter = new Intl.NumberFormat('es-ES', { style: 'currency', currency: 'EUR' });
  const intFormatter = new Intl.NumberFormat('es-ES', { maximumFractionDigits: 0 });
  const decimalFormatter = new Intl.NumberFormat('es-ES', { minimumFractionDigits: 0, maximumFractionDigits: 2 });

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  const els = {
    body: document.body,
    menuToggle: $('#menuToggle'),
    closeMenu: $('#closeMenu'),
    sideMenu: $('#sideMenu'),
    menuBackdrop: $('#menuBackdrop'),
    themeToggle: $('#themeToggle'),
    menuUpdatedAt: $('#menuUpdatedAt'),
    quickExport: $('#quickExport'),
    menuExportPortfolio: $('#menuExportPortfolio'),
    menuExportWishlist: $('#menuExportWishlist'),
    exportPortfolio: $('#exportPortfolio'),
    exportWishlist: $('#exportWishlist'),
    heroValue: $('#heroValue'),
    heroMeta: $('#heroMeta'),
    metricItems: $('#metricItems'),
    metricUnits: $('#metricUnits'),
    metricCurrentValue: $('#metricCurrentValue'),
    metricHistoricalValue: $('#metricHistoricalValue'),
    metricSales: $('#metricSales'),
    metricWishlist: $('#metricWishlist'),
    summaryByTcg: $('#summaryByTcg'),
    summaryTopEditions: $('#summaryTopEditions'),
    summaryTopItems: $('#summaryTopItems'),
    searchInput: $('#searchInput'),
    tcgFilter: $('#tcgFilter'),
    editionFilter: $('#editionFilter'),
    languageFilter: $('#languageFilter'),
    variantFilter: $('#variantFilter'),
    priceBandFilter: $('#priceBandFilter'),
    sortSelect: $('#sortSelect'),
    filteredCount: $('#filteredCount'),
    collectionNote: $('#collectionNote'),
    cardsGrid: $('#cardsGrid'),
    emptyState: $('#emptyState'),
    prevPage: $('#prevPage'),
    nextPage: $('#nextPage'),
    pageInfo: $('#pageInfo'),
    chartMode: $('#chartMode'),
    chartTcgFilter: $('#chartTcgFilter'),
    chartEditionFilter: $('#chartEditionFilter'),
    chartLanguageFilter: $('#chartLanguageFilter'),
    chartVariantFilter: $('#chartVariantFilter'),
    chartPriceBandFilter: $('#chartPriceBandFilter'),
    chartTotal: $('#chartTotal'),
    chartUnits: $('#chartUnits'),
    chartRows: $('#chartRows'),
    yearlyChart: $('#yearlyChart'),
    monthlyChart: $('#monthlyChart'),
    marketRefreshAll: $('#marketRefreshAll'),
    wishlistForm: $('#wishlistForm'),
    wishlistList: $('#wishlistList'),
    wishlistCount: $('#wishlistCount'),
    collectionForm: $('#collectionForm'),
    localItemsList: $('#localItemsList'),
    localItemsCount: $('#localItemsCount'),
    cardModal: $('#cardModal'),
    closeModal: $('#closeModal'),
    modalBody: $('#modalBody'),
    summaryDialog: $('#summaryDialog'),
    closeSummaryDialog: $('#closeSummaryDialog'),
    summaryDialogTitle: $('#summaryDialogTitle'),
    summaryDialogBody: $('#summaryDialogBody'),
    toast: $('#toast'),
    datalists: {
      tcg: $('#tcgOptions'),
      cardName: $('#nameOptions'),
      edition: $('#editionOptions'),
      language: $('#languageOptions'),
      variant: $('#variantOptions'),
    },
  };

  const state = {
    section: 'summary',
    collection: {
      query: '',
      tcg: 'all',
      edition: 'all',
      language: 'all',
      variant: 'all',
      priceBand: 'all',
      sort: 'total_desc',
      page: 1,
    },
    charts: {
      mode: 'historical',
      tcg: 'all',
      edition: 'all',
      language: 'all',
      variant: 'all',
      priceBand: 'all',
    },
  };

  function text(value) {
    return String(value ?? '').trim();
  }

  function toNumber(value) {
    const number = Number(value || 0);
    return Number.isFinite(number) ? number : 0;
  }

  function escapeHtml(value) {
    return text(value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function stripAccents(value) {
    return text(value).normalize('NFD').replace(/[\u0300-\u036f]/g, '');
  }

  function normalize(value) {
    return stripAccents(value).toLowerCase().replace(/&/g, ' and ').replace(/[^a-z0-9]+/g, ' ').replace(/\s+/g, ' ').trim();
  }

  function formatCurrency(value) {
    return formatter.format(toNumber(value));
  }

  function formatNumber(value) {
    return intFormatter.format(toNumber(value));
  }

  function formatDecimal(value) {
    return decimalFormatter.format(toNumber(value));
  }

  function priceBand(value) {
    const unit = toNumber(value);
    if (unit >= 250) return '250€+';
    if (unit >= 100) return '100€ - 249,99€';
    if (unit >= 50) return '50€ - 99,99€';
    if (unit >= 20) return '20€ - 49,99€';
    if (unit >= 10) return '10€ - 19,99€';
    return '<10€';
  }

  function canonicalVariant(tcg, variant) {
    const current = text(variant) || 'Non-foil';
    if (normalize(tcg) !== 'riftbound') return current;
    const parts = current.split('·').map((part) => text(part)).filter(Boolean);
    const extras = parts.filter((part) => normalize(part) !== 'foil' && normalize(part) !== 'non foil' && normalize(part) !== 'nonfoil');
    return extras.length ? `Foil · ${extras.join(' · ')}` : 'Foil';
  }

  function currentImageUrl(item) {
    const images = item?.images || {};
    return text(images.normal || images.large || images.small || item?.imageUrl);
  }

  function manualImagesFromUrl(url, previous = {}) {
    const cleanUrl = text(url);
    if (!cleanUrl) {
      return { small: '', normal: '', large: '', artCrop: '', status: 'manual_empty', source: 'manual' };
    }
    return {
      ...previous,
      small: cleanUrl,
      normal: cleanUrl,
      large: cleanUrl,
      artCrop: previous.artCrop || '',
      status: 'manual',
      source: 'manual',
    };
  }

  function periodFromDate(dateValue) {
    const raw = text(dateValue);
    if (/^\d{4}-\d{2}/.test(raw)) return raw.slice(0, 7);
    return 'Sin fecha';
  }

  function yearFromDate(dateValue) {
    const raw = text(dateValue);
    if (/^\d{4}/.test(raw)) return raw.slice(0, 4);
    return 'Sin fecha';
  }

  function loadStorage(key, fallback) {
    try {
      const raw = localStorage.getItem(key);
      return raw ? JSON.parse(raw) : fallback;
    } catch (error) {
      console.warn('No se pudo leer localStorage', key, error);
      return fallback;
    }
  }

  function saveStorage(key, value) {
    localStorage.setItem(key, JSON.stringify(value));
  }

  function showToast(message) {
    if (!els.toast) return;
    els.toast.textContent = message;
    els.toast.classList.add('show');
    clearTimeout(showToast.timer);
    showToast.timer = setTimeout(() => els.toast.classList.remove('show'), 2800);
  }

  function unique(values) {
    return [...new Set(values.map(text).filter(Boolean))]
      .sort((a, b) => a.localeCompare(b, 'es', { sensitivity: 'base' }));
  }

  function sortPriceBands(values) {
    const order = ['250€+', '100€ - 249,99€', '50€ - 99,99€', '20€ - 49,99€', '10€ - 19,99€', '<10€'];
    return values.sort((a, b) => {
      const ai = order.indexOf(a);
      const bi = order.indexOf(b);
      if (ai >= 0 && bi >= 0) return ai - bi;
      if (ai >= 0) return -1;
      if (bi >= 0) return 1;
      return a.localeCompare(b, 'es', { sensitivity: 'base' });
    });
  }

  function imageHtml(item, context = 'card') {
    const images = item.images || {};
    const url = text(images.normal || images.large || images.small || item.imageUrl);
    const alt = escapeHtml(item.cardName || item.name || 'Producto TCG');
    if (url) return `<img src="${escapeHtml(url)}" alt="${alt}" loading="lazy" />`;
    const label = text(item.tcg).slice(0, 16) || 'TCG';
    return `<div class="card-placeholder"><span>${escapeHtml(label)}</span><small>${context === 'modal' ? 'Imagen no informada' : 'Sin imagen'}</small></div>`;
  }

  function normalizeCard(card, source = 'base') {
    const quantity = toNumber(card.quantity);
    const total = toNumber(card.stockCost ?? card.totalPurchaseValue ?? card.total ?? 0);
    const unit = toNumber(card.unitPurchaseValue ?? card.unitPrice ?? (quantity ? total / quantity : 0));
    const safeTotal = total || unit * quantity;
    const date = text(card.date || card.lastPurchaseDate || card.firstPurchaseDate);
    const normalized = {
      ...card,
      source,
      cardName: text(card.cardName || card.name),
      name: text(card.name || card.cardName),
      tcg: text(card.tcg) || 'Sin TCG',
      edition: text(card.edition) || 'Sin edición',
      language: text(card.language) || 'Sin idioma',
      variant: canonicalVariant(text(card.tcg) || 'Sin TCG', text(card.variant) || 'Non-foil'),
      quantity,
      unitPurchaseValue: unit,
      unitPrice: unit,
      stockCost: safeTotal,
      totalPurchaseValue: safeTotal,
      total: safeTotal,
      priceBand: priceBand(unit),
      date,
      year: text(card.year || yearFromDate(date)),
      period: text(card.period || periodFromDate(date)),
      saleUnitValue: toNumber(card.saleUnitValue ?? card.unitSaleValue ?? card.salePrice ?? 0),
      saleTotalValue: toNumber(card.saleTotalValue ?? 0),
      imageUrl: currentImageUrl(card),
      marketPrice: card.marketPrice || { average: null, currency: 'EUR', sources: [], lastUpdated: null, status: 'not_requested' },
    };
    if (normalized.saleUnitValue && !normalized.saleTotalValue) {
      normalized.saleTotalValue = normalized.saleUnitValue * normalized.quantity;
    }
    normalized.searchBlob = [
      normalized.cardName,
      normalized.name,
      normalized.edition,
      normalized.language,
      normalized.variant,
      normalized.tcg,
      normalized.priceBand,
      normalized.sellerBuyer,
      normalized.orderNumber,
    ].map(normalize).join(' ');
    return normalized;
  }

  function normalizeTransaction(row, mode = 'historical') {
    const quantity = toNumber(row.quantity);
    const total = toNumber(row.totalPurchaseValue ?? row.totalCost ?? row.stockCost ?? row.total ?? 0);
    const unit = toNumber(row.unitPurchaseValue ?? row.unitCost ?? (quantity ? total / quantity : 0));
    const date = text(row.date);
    return {
      ...row,
      mode,
      cardName: text(row.cardName || row.name),
      tcg: text(row.tcg) || 'Sin TCG',
      edition: text(row.edition) || 'Sin edición',
      language: text(row.language) || 'Sin idioma',
      variant: canonicalVariant(text(row.tcg) || 'Sin TCG', text(row.variant) || 'Non-foil'),
      quantity,
      unitPurchaseValue: unit,
      totalPurchaseValue: total,
      priceBand: priceBand(unit),
      date,
      period: text(row.period || periodFromDate(date)),
      year: text(row.year || yearFromDate(date)),
    };
  }

  function localCardToTransaction(card, mode = 'historical') {
    return normalizeTransaction({
      id: card.id,
      sourceRow: card.sourceRow || card.id,
      date: card.date,
      period: card.period,
      year: card.year,
      tcg: card.tcg,
      cardName: card.cardName,
      edition: card.edition,
      language: card.language,
      variant: card.variant,
      quantity: card.quantity,
      unitPurchaseValue: card.unitPurchaseValue,
      totalPurchaseValue: card.stockCost,
      priceBand: card.priceBand,
      operation: mode === 'stock' ? 'Stock actual' : 'Compra local',
    }, mode);
  }

  const baseCards = (sourceData.cards || []).map((card) => normalizeCard(card, 'base'));
  const baseTransactions = (sourceData.transactions || []).map((row) => normalizeTransaction(row, 'historical'));
  let cardOverrides = loadStorage(CONFIG.cardOverridesKey, {});
  let localCards = loadStorage(CONFIG.localCardsKey, []).map((card) => normalizeCard(card, 'local'));

  const initialWishlist = (initialWishlistData.items || []).map((item) => ({ ...item, source: item.source || 'file' }));
  const storedWishlist = loadStorage(CONFIG.wishlistKey, []);
  let wishlistItems = mergeById([...initialWishlist, ...storedWishlist]);

  function mergeById(items) {
    const map = new Map();
    items.forEach((item) => {
      const id = text(item.id) || `item-${Date.now()}-${Math.random().toString(16).slice(2)}`;
      map.set(id, { ...item, id });
    });
    return [...map.values()];
  }

  function getBaseCards() {
    return baseCards.map((card) => normalizeCard({ ...card, ...(cardOverrides[card.id] || {}) }, 'base'));
  }

  function getCards() {
    return mergeById([...getBaseCards(), ...localCards]);
  }

  function getHistoricalRows() {
    return mergeById([...baseTransactions, ...localCards.map((card) => localCardToTransaction(card, 'historical'))]);
  }

  function getStockRows() {
    return getCards().map((card) => localCardToTransaction(card, 'stock'));
  }

  function populateSelect(select, values, allLabel, currentValue = 'all') {
    if (!select) return 'all';
    const normalizedValues = unique(values);
    const finalValues = select.id.toLowerCase().includes('priceband') ? sortPriceBands(normalizedValues) : normalizedValues;
    const currentStillValid = currentValue === 'all' || finalValues.includes(currentValue);
    const value = currentStillValid ? currentValue : 'all';
    select.innerHTML = `<option value="all">${escapeHtml(allLabel)}</option>` + finalValues
      .map((item) => `<option value="${escapeHtml(item)}">${escapeHtml(item)}</option>`)
      .join('');
    select.value = value;
    return value;
  }

  function collectionOptionPool(level) {
    const cards = getCards();
    return cards.filter((card) => {
      if (level !== 'tcg' && state.collection.tcg !== 'all' && card.tcg !== state.collection.tcg) return false;
      if (!['tcg', 'edition'].includes(level) && state.collection.edition !== 'all' && card.edition !== state.collection.edition) return false;
      if (!['tcg', 'edition', 'language'].includes(level) && state.collection.language !== 'all' && card.language !== state.collection.language) return false;
      if (!['tcg', 'edition', 'language', 'variant'].includes(level) && state.collection.variant !== 'all' && card.variant !== state.collection.variant) return false;
      return true;
    });
  }

  function updateCollectionSelects() {
    const c = state.collection;
    c.tcg = populateSelect(els.tcgFilter, getCards().map((card) => card.tcg), 'Todos', c.tcg);
    c.edition = populateSelect(els.editionFilter, collectionOptionPool('edition').map((card) => card.edition), 'Todas', c.edition);
    c.language = populateSelect(els.languageFilter, collectionOptionPool('language').map((card) => card.language), 'Todos', c.language);
    c.variant = populateSelect(els.variantFilter, collectionOptionPool('variant').map((card) => card.variant), 'Todas', c.variant);
    c.priceBand = populateSelect(els.priceBandFilter, collectionOptionPool('priceBand').map((card) => card.priceBand), 'Todas', c.priceBand);
  }

  function filteredCards() {
    const c = state.collection;
    const query = normalize(c.query);
    let result = getCards().filter((card) => {
      if (query && !card.searchBlob.includes(query)) return false;
      if (c.tcg !== 'all' && card.tcg !== c.tcg) return false;
      if (c.edition !== 'all' && card.edition !== c.edition) return false;
      if (c.language !== 'all' && card.language !== c.language) return false;
      if (c.variant !== 'all' && card.variant !== c.variant) return false;
      if (c.priceBand !== 'all' && card.priceBand !== c.priceBand) return false;
      return true;
    });

    result = [...result].sort((a, b) => {
      switch (c.sort) {
        case 'unit_desc': return b.unitPurchaseValue - a.unitPurchaseValue;
        case 'quantity_desc': return b.quantity - a.quantity;
        case 'date_desc': return new Date(b.date || 0).getTime() - new Date(a.date || 0).getTime();
        case 'name_asc': return a.cardName.localeCompare(b.cardName, 'es', { sensitivity: 'base' });
        case 'edition_asc': return a.edition.localeCompare(b.edition, 'es', { sensitivity: 'base' });
        case 'total_desc':
        default: return b.stockCost - a.stockCost;
      }
    });
    return result;
  }

  function aggregateRows(list, key, limit = 10) {
    const map = new Map();
    list.forEach((item) => {
      const label = text(item[key]) || 'Sin dato';
      const row = map.get(label) || { label, total: 0, quantity: 0, count: 0 };
      row.total += toNumber(item.stockCost ?? item.totalPurchaseValue);
      row.quantity += toNumber(item.quantity);
      row.count += 1;
      map.set(label, row);
    });
    return [...map.values()].sort((a, b) => b.total - a.total).slice(0, limit);
  }

  function renderBarList(container, rows, valueMode = 'currency') {
    if (!container) return;
    if (!rows.length) {
      container.innerHTML = '<p class="chart-empty">Sin datos.</p>';
      return;
    }
    const max = Math.max(...rows.map((row) => toNumber(row.total || row.value || row.quantity)), 1);
    container.innerHTML = rows.map((row) => {
      const value = toNumber(row.total || row.value || row.quantity);
      const width = Math.max(4, Math.round((value / max) * 100));
      const displayValue = valueMode === 'quantity' ? `${formatDecimal(value)} uds.` : formatCurrency(value);
      return `
        <div class="bar-row">
          <div class="bar-row-main"><span title="${escapeHtml(row.label)}">${escapeHtml(row.label)}</span><strong>${displayValue}</strong></div>
          <div class="bar-track"><div class="bar-fill" style="width:${width}%"></div></div>
        </div>`;
    }).join('');
  }

  function renderSummary() {
    const cards = getCards();
    const historical = getHistoricalRows();
    const totalCurrent = cards.reduce((sum, card) => sum + card.stockCost, 0);
    const totalUnits = cards.reduce((sum, card) => sum + card.quantity, 0);
    const historicalSpend = historical.reduce((sum, row) => sum + row.totalPurchaseValue, 0);
    const matchedSales = toNumber(metadata.matchedSaleRows || 0);

    els.heroValue.textContent = formatCurrency(totalCurrent);
    els.heroMeta.textContent = `${formatNumber(cards.length)} elementos · ${formatDecimal(totalUnits)} unidades`;
    els.metricItems.textContent = formatNumber(cards.length);
    els.metricUnits.textContent = formatDecimal(totalUnits);
    els.metricCurrentValue.textContent = formatCurrency(totalCurrent);
    els.metricHistoricalValue.textContent = formatCurrency(historicalSpend);
    els.metricSales.textContent = formatNumber(matchedSales);
    els.metricWishlist.textContent = formatNumber(wishlistItems.length);

    renderBarList(els.summaryByTcg, aggregateRows(cards, 'tcg', 8));
    renderBarList(els.summaryTopEditions, aggregateRows(cards, 'edition', 8));
    renderBarList(els.summaryTopItems, aggregateRows(cards, 'cardName', 8));
  }

  function renderCollection() {
    updateCollectionSelects();
    const cards = filteredCards();
    const totalPages = Math.max(1, Math.ceil(cards.length / CONFIG.pageSize));
    state.collection.page = Math.min(Math.max(1, state.collection.page), totalPages);
    const start = (state.collection.page - 1) * CONFIG.pageSize;
    const pageCards = cards.slice(start, start + CONFIG.pageSize);

    els.filteredCount.textContent = formatNumber(cards.length);
    els.pageInfo.textContent = `Página ${state.collection.page}/${totalPages}`;
    els.prevPage.disabled = state.collection.page <= 1;
    els.nextPage.disabled = state.collection.page >= totalPages;
    els.collectionNote.textContent = `${formatDecimal(cards.reduce((sum, card) => sum + card.quantity, 0))} unidades · ${formatCurrency(cards.reduce((sum, card) => sum + card.stockCost, 0))}`;

    els.cardsGrid.innerHTML = pageCards.map(renderCard).join('');
    els.emptyState.classList.toggle('hidden', cards.length > 0);
  }

  function renderCard(card) {
    const saleLine = card.saleUnitValue ? `<p class="card-sale-line">Venta u. ${formatCurrency(card.saleUnitValue)} · Total ${formatCurrency(card.saleTotalValue || card.saleUnitValue * card.quantity)}</p>` : '';
    return `
      <article class="collection-card" data-card-id="${escapeHtml(card.id)}">
        <div class="card-image-stage">
          <span class="card-badge">${escapeHtml(card.priceBand)}</span>
          ${imageHtml(card)}
        </div>
        <div class="card-body">
          <div>
            <h2 class="card-title">${escapeHtml(card.cardName)}</h2>
            <p class="card-meta">${escapeHtml(card.edition)} · ${escapeHtml(card.language)}</p>
          </div>
          <div class="card-tags">
            <span class="tcg-badge">${escapeHtml(card.tcg)}</span>
            <span class="variant-badge">${escapeHtml(card.variant)}</span>
          </div>
          <div class="card-stats">
            <div><span>Unid.</span><strong>${formatDecimal(card.quantity)}</strong></div>
            <div><span>Coste u.</span><strong>${formatCurrency(card.unitPurchaseValue)}</strong></div>
            <div><span>Total</span><strong>${formatCurrency(card.stockCost)}</strong></div>
          </div>
          ${saleLine}
          <div class="card-actions">
            <button class="ghost-button" type="button" data-action="detail" data-card-id="${escapeHtml(card.id)}">Detalle</button>
            <button class="secondary-action" type="button" data-action="market" data-card-id="${escapeHtml(card.id)}">Precio</button>
          </div>
        </div>
      </article>`;
  }

  function findCard(id) {
    return getCards().find((card) => text(card.id) === text(id));
  }

  function openCardModal(card) {
    if (!card || !els.cardModal || !els.modalBody) return;
    const purchaseRows = Array.isArray(card.purchaseSourceRows) ? card.purchaseSourceRows.length : toNumber(card.purchaseCount || 0);
    const saleRows = Array.isArray(card.saleSourceRows) ? card.saleSourceRows.length : toNumber(card.saleCount || 0);
    const saleUnit = toNumber(card.saleUnitValue);
    const saleTotal = toNumber(card.saleTotalValue || saleUnit * card.quantity);
    const overrideExists = card.source !== 'local' && Boolean(cardOverrides[card.id]);
    els.modalBody.innerHTML = `
      <div class="modal-layout editable-modal-layout">
        <div class="modal-image editable-preview">
          ${imageHtml(card, 'modal')}
          <small>La imagen puede sustituirse pegando otra URL y guardando cambios.</small>
        </div>
        <div class="modal-content">
          <p class="eyebrow">${escapeHtml(card.tcg)}</p>
          <h2>${escapeHtml(card.cardName)}</h2>
          <p class="card-meta">${escapeHtml(card.edition)} · ${escapeHtml(card.language)} · ${escapeHtml(card.variant)}</p>
          <div class="detail-grid">
            <div><span>Unidades en stock</span><strong>${formatDecimal(card.quantity)}</strong></div>
            <div><span>Coste unitario medio</span><strong>${formatCurrency(card.unitPurchaseValue)}</strong></div>
            <div><span>Coste actual</span><strong>${formatCurrency(card.stockCost)}</strong></div>
            <div><span>Precio venta u.</span><strong>${saleUnit ? formatCurrency(saleUnit) : 'Sin informar'}</strong></div>
            <div><span>Venta total estimada</span><strong>${saleUnit ? formatCurrency(saleTotal) : 'Sin informar'}</strong></div>
            <div><span>Banda</span><strong>${escapeHtml(card.priceBand)}</strong></div>
            <div><span>Compras agrupadas</span><strong>${formatNumber(purchaseRows)}</strong></div>
            <div><span>Ventas descontadas</span><strong>${formatNumber(saleRows)}</strong></div>
          </div>
          <form id="cardEditForm" class="edit-form" data-card-id="${escapeHtml(card.id)}">
            <h3>Editar elemento</h3>
            <div class="form-grid compact-form-grid">
              <label><span>TCG</span><input name="tcg" list="tcgOptions" required value="${escapeHtml(card.tcg)}" /></label>
              <label><span>Nombre</span><input name="cardName" list="nameOptions" required value="${escapeHtml(card.cardName)}" /></label>
              <label><span>Edición</span><input name="edition" list="editionOptions" required value="${escapeHtml(card.edition)}" /></label>
              <label><span>Idioma</span><input name="language" list="languageOptions" value="${escapeHtml(card.language)}" /></label>
              <label><span>Variante</span><input name="variant" list="variantOptions" value="${escapeHtml(card.variant)}" /></label>
              <label><span>Unidades</span><input name="quantity" type="number" min="1" step="1" required value="${escapeHtml(card.quantity)}" /></label>
              <label><span>Coste unitario</span><input name="unitCost" type="number" min="${escapeHtml(CONFIG.minUnitCost)}" step="0.01" required value="${escapeHtml(card.unitPurchaseValue)}" /></label>
              <label><span>Precio venta unitario</span><input name="saleUnitValue" type="number" min="0" step="0.01" value="${escapeHtml(saleUnit || '')}" placeholder="0,00" /></label>
              <label class="full"><span>URL imagen</span><input name="imageUrl" type="url" value="${escapeHtml(currentImageUrl(card))}" placeholder="https://…" /></label>
              <label class="full"><span>Notas</span><textarea name="notes" rows="3" placeholder="Estado, cambios manuales, precio de venta…">${escapeHtml(card.notes || '')}</textarea></label>
            </div>
            <p class="form-hint">Los cambios se guardan en este navegador. Usa Exportar colección para descargar los archivos actualizados y reemplazarlos en el repositorio.</p>
            <div class="hero-actions modal-action-row">
              <button class="primary-action" type="submit">Guardar cambios</button>
              <button class="secondary-action" type="button" data-modal-market="${escapeHtml(card.id)}">Buscar precio de mercado</button>
              ${overrideExists ? `<button class="ghost-button danger-text" type="button" data-modal-reset="${escapeHtml(card.id)}">Restaurar original</button>` : ''}
              <button class="ghost-button" type="button" data-modal-close>Cerrar</button>
            </div>
          </form>
        </div>
      </div>`;
    showDialog(els.cardModal);
  }

  function showDialog(dialog) {
    if (!dialog) return;
    if (dialog.open) return;
    if (typeof dialog.showModal === 'function') dialog.showModal();
    else dialog.setAttribute('open', '');
  }

  function closeDialog(dialog) {
    if (!dialog) return;
    if (typeof dialog.close === 'function') dialog.close();
    else dialog.removeAttribute('open');
  }


  function persistCardPatch(card, patch) {
    if (!card) return null;
    if (card.source === 'local') {
      localCards = localCards.map((item) => item.id === card.id ? normalizeCard({ ...item, ...patch }, 'local') : item);
      saveStorage(CONFIG.localCardsKey, localCards.map(stripTransientCard));
      return localCards.find((item) => item.id === card.id);
    }
    cardOverrides = {
      ...cardOverrides,
      [card.id]: {
        ...(cardOverrides[card.id] || {}),
        ...patch,
        updatedAt: new Date().toISOString(),
        manualEdited: true,
      },
    };
    saveStorage(CONFIG.cardOverridesKey, cardOverrides);
    return findCard(card.id);
  }

  function resetCardPatch(cardId) {
    if (!cardOverrides[cardId]) return;
    const next = { ...cardOverrides };
    delete next[cardId];
    cardOverrides = next;
    saveStorage(CONFIG.cardOverridesKey, cardOverrides);
  }

  function handleCardEditSubmit(event) {
    const form = event.target.closest('#cardEditForm');
    if (!form) return;
    event.preventDefault();
    normalizeFormFields(form);
    const card = findCard(form.dataset.cardId);
    if (!card) return;
    const values = readForm(form);
    const quantity = Math.max(1, toNumber(values.quantity || 1));
    const unitCost = toNumber(values.unitCost);
    if (unitCost < CONFIG.minUnitCost) {
      showToast(`El coste unitario debe ser igual o superior a ${formatCurrency(CONFIG.minUnitCost)}.`);
      return;
    }
    const saleUnit = toNumber(values.saleUnitValue);
    const tcg = text(values.tcg) || 'Sin TCG';
    const variant = canonicalVariant(tcg, text(values.variant) || 'Non-foil');
    const stockCost = unitCost * quantity;
    const imageUrl = text(values.imageUrl);
    const patch = {
      tcg,
      cardName: text(values.cardName),
      name: text(values.cardName),
      edition: text(values.edition) || 'Sin edición',
      language: text(values.language) || 'Sin idioma',
      variant,
      quantity,
      unitPurchaseValue: unitCost,
      unitPrice: unitCost,
      stockCost,
      totalPurchaseValue: stockCost,
      total: stockCost,
      priceBand: priceBand(unitCost),
      saleUnitValue: saleUnit,
      saleTotalValue: saleUnit ? saleUnit * quantity : 0,
      imageUrl,
      images: manualImagesFromUrl(imageUrl, card.images || {}),
      notes: text(values.notes),
    };
    const updated = persistCardPatch(card, patch);
    refreshAll();
    updateDatalists();
    if (updated) openCardModal(updated);
    showToast('Cambios guardados. Exporta la colección para persistirlos en el JSON.');
  }

  function requestMarketPrice(item, type = 'collection') {
    const name = text(item.cardName || item.name);
    if (type === 'wishlist') {
      item.marketPrice = { ...(item.marketPrice || {}), status: 'requested', requestedAt: new Date().toISOString() };
      saveStorage(CONFIG.wishlistKey, wishlistItems);
      renderWishlist();
    } else {
      persistCardPatch(item, {
        marketPrice: { ...(item.marketPrice || {}), status: 'requested', requestedAt: new Date().toISOString() },
      });
    }
    showToast(`Solicitud preparada para buscar precio de mercado: ${name}.`);
  }

  function chartBaseRows() {
    return state.charts.mode === 'stock' ? getStockRows() : getHistoricalRows();
  }

  function chartOptionPool(level) {
    const rows = chartBaseRows();
    return rows.filter((row) => {
      if (level !== 'tcg' && state.charts.tcg !== 'all' && row.tcg !== state.charts.tcg) return false;
      if (!['tcg', 'edition'].includes(level) && state.charts.edition !== 'all' && row.edition !== state.charts.edition) return false;
      if (!['tcg', 'edition', 'language'].includes(level) && state.charts.language !== 'all' && row.language !== state.charts.language) return false;
      if (!['tcg', 'edition', 'language', 'variant'].includes(level) && state.charts.variant !== 'all' && row.variant !== state.charts.variant) return false;
      return true;
    });
  }

  function updateChartSelects() {
    const c = state.charts;
    c.tcg = populateSelect(els.chartTcgFilter, chartBaseRows().map((row) => row.tcg), 'Todos', c.tcg);
    c.edition = populateSelect(els.chartEditionFilter, chartOptionPool('edition').map((row) => row.edition), 'Todas', c.edition);
    c.language = populateSelect(els.chartLanguageFilter, chartOptionPool('language').map((row) => row.language), 'Todos', c.language);
    c.variant = populateSelect(els.chartVariantFilter, chartOptionPool('variant').map((row) => row.variant), 'Todas', c.variant);
    c.priceBand = populateSelect(els.chartPriceBandFilter, chartOptionPool('priceBand').map((row) => row.priceBand), 'Todas', c.priceBand);
  }

  function filteredChartRows() {
    const c = state.charts;
    return chartBaseRows().filter((row) => {
      if (c.tcg !== 'all' && row.tcg !== c.tcg) return false;
      if (c.edition !== 'all' && row.edition !== c.edition) return false;
      if (c.language !== 'all' && row.language !== c.language) return false;
      if (c.variant !== 'all' && row.variant !== c.variant) return false;
      if (c.priceBand !== 'all' && row.priceBand !== c.priceBand) return false;
      return true;
    });
  }

  function groupChartRows(rows, key) {
    const map = new Map();
    rows.forEach((row) => {
      const label = key === 'year' ? text(row.year || yearFromDate(row.date)) : text(row.period || periodFromDate(row.date));
      const safeLabel = label || 'Sin fecha';
      const item = map.get(safeLabel) || { label: safeLabel, total: 0, quantity: 0, count: 0 };
      item.total += toNumber(row.totalPurchaseValue);
      item.quantity += toNumber(row.quantity);
      item.count += 1;
      map.set(safeLabel, item);
    });
    return [...map.values()].sort((a, b) => a.label.localeCompare(b.label, 'es', { numeric: true }));
  }

  function renderChart(container, rows, maxBars = 30) {
    if (!container) return;
    const validRows = rows.filter((row) => toNumber(row.total) > 0);
    if (!validRows.length) {
      container.innerHTML = '<p class="chart-empty">Sin datos para los filtros seleccionados.</p>';
      return;
    }
    const sliced = validRows.slice(-maxBars);
    const max = Math.max(...sliced.map((row) => row.total), 1);
    container.innerHTML = sliced.map((row) => {
      const width = Math.max(3, Math.round((row.total / max) * 100));
      return `
        <div class="chart-row">
          <span title="${escapeHtml(row.label)}">${escapeHtml(row.label)}</span>
          <div class="chart-track"><div class="chart-bar" style="--w:${width}%"></div></div>
          <strong>${formatCurrency(row.total)}</strong>
        </div>`;
    }).join('');
  }

  function renderCharts() {
    updateChartSelects();
    const rows = filteredChartRows();
    const total = rows.reduce((sum, row) => sum + row.totalPurchaseValue, 0);
    const units = rows.reduce((sum, row) => sum + row.quantity, 0);
    els.chartTotal.textContent = formatCurrency(total);
    els.chartUnits.textContent = formatDecimal(units);
    els.chartRows.textContent = formatNumber(rows.length);
    renderChart(els.yearlyChart, groupChartRows(rows, 'year'), 12);
    renderChart(els.monthlyChart, groupChartRows(rows, 'period'), 30);
  }

  function normalizeManualValue(value, values) {
    const raw = text(value);
    if (!raw) return raw;
    const exact = values.find((candidate) => normalize(candidate) === normalize(raw));
    if (exact) return exact;
    const rawNorm = normalize(raw);
    let best = { value: raw, score: 0 };
    values.forEach((candidate) => {
      const candNorm = normalize(candidate);
      if (!candNorm) return;
      let score = similarity(rawNorm, candNorm);
      if (candNorm.includes(rawNorm) || rawNorm.includes(candNorm)) score = Math.max(score, 0.88);
      if (score > best.score) best = { value: candidate, score };
    });
    return best.score >= 0.78 ? best.value : raw;
  }

  function similarity(a, b) {
    if (a === b) return 1;
    if (!a || !b) return 0;
    const bigrams = (value) => {
      const out = new Map();
      for (let i = 0; i < value.length - 1; i += 1) {
        const key = value.slice(i, i + 2);
        out.set(key, (out.get(key) || 0) + 1);
      }
      return out;
    };
    const aa = bigrams(a);
    const bb = bigrams(b);
    let overlap = 0;
    aa.forEach((count, key) => {
      overlap += Math.min(count, bb.get(key) || 0);
    });
    return (2 * overlap) / Math.max(1, a.length + b.length - 2);
  }

  function valuesFor(field) {
    const cards = getCards();
    const rows = getHistoricalRows();
    const wish = wishlistItems;
    return unique([
      ...cards.map((item) => item[field]),
      ...rows.map((item) => item[field]),
      ...wish.map((item) => item[field]),
    ]);
  }

  function updateDatalists() {
    const fields = ['tcg', 'cardName', 'edition', 'language', 'variant'];
    fields.forEach((field) => {
      const datalist = els.datalists[field];
      if (!datalist) return;
      datalist.innerHTML = valuesFor(field).map((value) => `<option value="${escapeHtml(value)}"></option>`).join('');
    });
  }

  function normalizeFormFields(form) {
    ['tcg', 'cardName', 'edition', 'language', 'variant'].forEach((name) => {
      const input = form.elements[name];
      if (!input) return;
      input.value = normalizeManualValue(input.value, valuesFor(name));
    });
  }

  function readForm(form) {
    const data = new FormData(form);
    return Object.fromEntries(data.entries());
  }

  function renderWishlist() {
    els.wishlistCount.textContent = formatNumber(wishlistItems.length);
    els.metricWishlist.textContent = formatNumber(wishlistItems.length);
    if (!wishlistItems.length) {
      els.wishlistList.innerHTML = '<p class="chart-empty">Todavía no hay objetivos guardados.</p>';
      return;
    }
    els.wishlistList.innerHTML = wishlistItems.map((item) => renderListItem(item, 'wishlist')).join('');
  }

  function renderLocalItems() {
    els.localItemsCount.textContent = formatNumber(localCards.length);
    if (!localCards.length) {
      els.localItemsList.innerHTML = '<p class="chart-empty">No hay altas locales todavía.</p>';
      return;
    }
    els.localItemsList.innerHTML = localCards.map((item) => renderListItem(item, 'local')).join('');
  }

  function renderListItem(item, type) {
    const img = text(item.images?.normal || item.imageUrl);
    const thumb = img ? `<img src="${escapeHtml(img)}" alt="${escapeHtml(item.cardName)}" loading="lazy" />` : escapeHtml(text(item.tcg).slice(0, 3) || 'TCG');
    const amount = type === 'wishlist'
      ? (toNumber(item.targetPrice) ? `Objetivo ${formatCurrency(item.targetPrice)}` : 'Sin precio objetivo')
      : `${formatDecimal(item.quantity)} uds. · ${formatCurrency(item.stockCost)}`;
    return `
      <div class="list-item" data-id="${escapeHtml(item.id)}" data-list-type="${escapeHtml(type)}">
        <div class="list-thumb">${thumb}</div>
        <div>
          <h3>${escapeHtml(item.cardName || item.name)}</h3>
          <p>${escapeHtml(item.tcg)} · ${escapeHtml(item.edition)} · ${escapeHtml(item.language || 'Sin idioma')}</p>
          <p>${escapeHtml(amount)}${item.priority ? ` · ${escapeHtml(item.priority)}` : ''}</p>
          <div class="list-actions">
            <button class="small-button" type="button" data-list-action="market">Precio</button>
            <button class="small-button danger" type="button" data-list-action="delete">Eliminar</button>
          </div>
        </div>
      </div>`;
  }

  function handleWishlistSubmit(event) {
    event.preventDefault();
    normalizeFormFields(els.wishlistForm);
    const values = readForm(els.wishlistForm);
    const item = {
      id: `wish-${Date.now()}-${Math.random().toString(16).slice(2)}`,
      source: 'localStorage',
      createdAt: new Date().toISOString(),
      tcg: text(values.tcg) || 'Sin TCG',
      cardName: text(values.cardName),
      name: text(values.cardName),
      edition: text(values.edition) || 'Sin edición',
      language: text(values.language) || 'Sin idioma',
      variant: canonicalVariant(text(values.tcg) || 'Sin TCG', text(values.variant) || 'Non-foil'),
      quantity: Math.max(1, toNumber(values.quantity || 1)),
      targetPrice: toNumber(values.targetPrice),
      priority: text(values.priority || 'Media'),
      notes: text(values.notes),
      imageUrl: text(values.imageUrl),
      images: values.imageUrl ? { normal: text(values.imageUrl), small: text(values.imageUrl), large: text(values.imageUrl), artCrop: '', status: 'manual' } : {},
      marketPrice: { average: null, currency: 'EUR', sources: [], lastUpdated: null, status: 'not_requested' },
    };
    wishlistItems.push(item);
    saveStorage(CONFIG.wishlistKey, wishlistItems);
    els.wishlistForm.reset();
    updateDatalists();
    renderWishlist();
    renderSummary();
    showToast('Objetivo añadido a la Wish List.');
  }

  function handleCollectionSubmit(event) {
    event.preventDefault();
    normalizeFormFields(els.collectionForm);
    const values = readForm(els.collectionForm);
    const unitCost = toNumber(values.unitCost);
    if (unitCost < CONFIG.minUnitCost) {
      showToast(`El coste unitario debe ser igual o superior a ${formatCurrency(CONFIG.minUnitCost)}.`);
      return;
    }
    const quantity = Math.max(1, toNumber(values.quantity || 1));
    const date = text(values.date) || new Date().toISOString().slice(0, 10);
    const stockCost = unitCost * quantity;
    const card = normalizeCard({
      id: `local-${Date.now()}-${Math.random().toString(16).slice(2)}`,
      source: 'localStorage',
      createdAt: new Date().toISOString(),
      tcg: text(values.tcg) || 'Sin TCG',
      cardName: text(values.cardName),
      name: text(values.cardName),
      edition: text(values.edition) || 'Sin edición',
      language: text(values.language) || 'Sin idioma',
      variant: canonicalVariant(text(values.tcg) || 'Sin TCG', text(values.variant) || 'Non-foil'),
      quantity,
      purchasedQuantity: quantity,
      soldQuantity: 0,
      unitPurchaseValue: unitCost,
      unitPrice: unitCost,
      stockCost,
      totalPurchaseValue: stockCost,
      total: stockCost,
      grossPurchaseValue: stockCost,
      priceBand: priceBand(unitCost),
      date,
      firstPurchaseDate: date,
      lastPurchaseDate: date,
      year: yearFromDate(date),
      period: periodFromDate(date),
      notes: text(values.notes),
      images: values.imageUrl ? { normal: text(values.imageUrl), small: text(values.imageUrl), large: text(values.imageUrl), artCrop: '', status: 'manual' } : {},
      imageUrl: text(values.imageUrl),
      purchaseSourceRows: [],
      saleSourceRows: [],
      marketPrice: { average: null, currency: 'EUR', sources: [], lastUpdated: null, status: 'not_requested' },
    }, 'local');
    localCards.push(card);
    saveStorage(CONFIG.localCardsKey, localCards.map(stripTransientCard));
    els.collectionForm.reset();
    updateDatalists();
    refreshAll();
    showToast('Elemento añadido a la colección local.');
  }

  function stripTransientCard(card) {
    const { searchBlob, source, ...rest } = card;
    return rest;
  }

  function handleListClick(event) {
    const button = event.target.closest('[data-list-action]');
    if (!button) return;
    const itemNode = event.target.closest('.list-item');
    if (!itemNode) return;
    const id = itemNode.dataset.id;
    const type = itemNode.dataset.listType;
    const action = button.dataset.listAction;
    if (type === 'wishlist') {
      const item = wishlistItems.find((entry) => entry.id === id);
      if (action === 'delete') {
        wishlistItems = wishlistItems.filter((entry) => entry.id !== id);
        saveStorage(CONFIG.wishlistKey, wishlistItems);
        renderWishlist();
        renderSummary();
        showToast('Objetivo eliminado.');
      } else if (action === 'market' && item) {
        requestMarketPrice(item, 'wishlist');
      }
    }
    if (type === 'local') {
      const item = localCards.find((entry) => entry.id === id);
      if (action === 'delete') {
        localCards = localCards.filter((entry) => entry.id !== id);
        saveStorage(CONFIG.localCardsKey, localCards.map(stripTransientCard));
        refreshAll();
        showToast('Alta local eliminada.');
      } else if (action === 'market' && item) {
        requestMarketPrice(item, 'collection');
      }
    }
  }

  function exportPortfolioData() {
    const localTransactionRows = localCards.map((card) => localCardToTransaction(card, 'historical'));
    const payload = {
      ...sourceData,
      metadata: {
        ...(sourceData.metadata || {}),
        exportedAt: new Date().toISOString(),
        localAdditions: localCards.length,
        manualOverrides: Object.keys(cardOverrides).length,
        exportNote: 'Incluye altas y ediciones guardadas en localStorage desde la web.',
      },
      cards: getCards().map(stripTransientCard),
      transactions: mergeById([...(sourceData.transactions || []), ...localTransactionRows]),
      stockLots: getStockRows(),
    };
    downloadDataFiles(payload, 'portfolio-data', 'portfolioData');
  }

  function exportWishlistData() {
    const payload = {
      metadata: {
        ...(initialWishlistData.metadata || {}),
        exportedAt: new Date().toISOString(),
        count: wishlistItems.length,
      },
      items: wishlistItems,
    };
    downloadDataFiles(payload, 'wishlist-data', 'wishlistData');
  }

  function downloadBlob(textContent, filename, mimeType) {
    const blob = new Blob([textContent], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  function downloadDataFiles(payload, baseName, globalName) {
    const jsonText = JSON.stringify(payload, null, 2);
    downloadBlob(jsonText, `${baseName}.json`, 'application/json');
    downloadBlob(`window.${globalName} = ${jsonText};\n`, `${baseName}.js`, 'text/javascript');
    showToast(`Archivos preparados: ${baseName}.json y ${baseName}.js`);
  }

  function showSection(section) {
    state.section = section;
    $$('.app-section').forEach((node) => node.classList.toggle('active', node.id === section));
    $$('[data-section-target]').forEach((node) => {
      if (node.classList.contains('menu-link')) node.classList.toggle('active', node.dataset.sectionTarget === section);
    });
    closeMenu();
    if (section === 'charts') renderCharts();
    if (section === 'collection') renderCollection();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function openMenu() {
    els.body.classList.add('menu-open');
    els.menuToggle?.setAttribute('aria-expanded', 'true');
    els.sideMenu?.setAttribute('aria-hidden', 'false');
    if (els.menuBackdrop) els.menuBackdrop.hidden = false;
  }

  function closeMenu() {
    els.body.classList.remove('menu-open');
    els.menuToggle?.setAttribute('aria-expanded', 'false');
    els.sideMenu?.setAttribute('aria-hidden', 'true');
    if (els.menuBackdrop) els.menuBackdrop.hidden = true;
  }

  function renderSummaryDialog(metric) {
    const cards = getCards();
    const rows = getHistoricalRows();
    const data = {
      items: ['Elementos agrupados', formatNumber(cards.length), 'Cada tarjeta representa stock actual tras compras y ventas.'],
      units: ['Unidades en stock', formatDecimal(cards.reduce((sum, card) => sum + card.quantity, 0)), 'Suma de unidades actuales, incluyendo playsets convertidos a 4 unidades.'],
      current: ['Coste actual', formatCurrency(cards.reduce((sum, card) => sum + card.stockCost, 0)), 'Coste medio unitario aplicado al stock en posesión.'],
      historical: ['Gasto histórico', formatCurrency(rows.reduce((sum, row) => sum + row.totalPurchaseValue, 0)), 'Compras registradas en el Excel y altas locales.'],
      sales: ['Ventas imputadas', formatNumber(toNumber(metadata.matchedSaleRows)), 'Ventas conciliadas contra compras para calcular stock actual.'],
      wishlist: ['Wish List', formatNumber(wishlistItems.length), 'Objetivos guardados en este navegador o cargados desde wishlist-data.'],
    }[metric];
    if (!data) return;
    els.summaryDialogTitle.textContent = data[0];
    els.summaryDialogBody.innerHTML = `<div class="metric-detail-list"><div><span>Valor</span><strong>${data[1]}</strong></div><p>${escapeHtml(data[2])}</p></div>`;
    showDialog(els.summaryDialog);
  }

  function setTheme(theme) {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem(CONFIG.themeKey, theme);
    if (els.themeToggle) els.themeToggle.textContent = theme === 'dark' ? 'Claro' : 'Oscuro';
  }

  function refreshAll() {
    renderSummary();
    renderCollection();
    renderCharts();
    renderWishlist();
    renderLocalItems();
    updateDatalists();
  }

  function bindEvents() {
    els.menuToggle?.addEventListener('click', openMenu);
    els.closeMenu?.addEventListener('click', closeMenu);
    els.menuBackdrop?.addEventListener('click', closeMenu);
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') closeMenu();
    });

    $$('[data-section-target]').forEach((button) => {
      button.addEventListener('click', () => showSection(button.dataset.sectionTarget));
    });
    $('[data-section-link="summary"]')?.addEventListener('click', (event) => {
      event.preventDefault();
      showSection('summary');
    });

    els.themeToggle?.addEventListener('click', () => {
      const current = document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light';
      setTheme(current === 'dark' ? 'light' : 'dark');
    });

    els.searchInput?.addEventListener('input', (event) => {
      state.collection.query = event.target.value;
      state.collection.page = 1;
      renderCollection();
    });
    els.tcgFilter?.addEventListener('change', (event) => {
      state.collection.tcg = event.target.value;
      state.collection.edition = 'all';
      state.collection.language = 'all';
      state.collection.variant = 'all';
      state.collection.priceBand = 'all';
      state.collection.page = 1;
      renderCollection();
    });
    els.editionFilter?.addEventListener('change', (event) => {
      state.collection.edition = event.target.value;
      state.collection.language = 'all';
      state.collection.variant = 'all';
      state.collection.priceBand = 'all';
      state.collection.page = 1;
      renderCollection();
    });
    els.languageFilter?.addEventListener('change', (event) => {
      state.collection.language = event.target.value;
      state.collection.variant = 'all';
      state.collection.priceBand = 'all';
      state.collection.page = 1;
      renderCollection();
    });
    els.variantFilter?.addEventListener('change', (event) => {
      state.collection.variant = event.target.value;
      state.collection.priceBand = 'all';
      state.collection.page = 1;
      renderCollection();
    });
    els.priceBandFilter?.addEventListener('change', (event) => {
      state.collection.priceBand = event.target.value;
      state.collection.page = 1;
      renderCollection();
    });
    els.sortSelect?.addEventListener('change', (event) => {
      state.collection.sort = event.target.value;
      renderCollection();
    });
    els.prevPage?.addEventListener('click', () => {
      state.collection.page = Math.max(1, state.collection.page - 1);
      renderCollection();
    });
    els.nextPage?.addEventListener('click', () => {
      state.collection.page += 1;
      renderCollection();
    });

    els.cardsGrid?.addEventListener('click', (event) => {
      const button = event.target.closest('[data-action]');
      if (!button) return;
      const card = findCard(button.dataset.cardId);
      if (button.dataset.action === 'detail') openCardModal(card);
      if (button.dataset.action === 'market' && card) requestMarketPrice(card, 'collection');
    });
    els.modalBody?.addEventListener('submit', handleCardEditSubmit);
    els.modalBody?.addEventListener('click', (event) => {
      const close = event.target.closest('[data-modal-close]');
      const market = event.target.closest('[data-modal-market]');
      const reset = event.target.closest('[data-modal-reset]');
      if (close) closeDialog(els.cardModal);
      if (market) {
        const card = findCard(market.dataset.modalMarket);
        if (card) requestMarketPrice(card, 'collection');
      }
      if (reset) {
        resetCardPatch(reset.dataset.modalReset);
        refreshAll();
        const card = findCard(reset.dataset.modalReset);
        if (card) openCardModal(card);
        showToast('Valores originales restaurados.');
      }
    });
    els.closeModal?.addEventListener('click', () => closeDialog(els.cardModal));
    els.closeSummaryDialog?.addEventListener('click', () => closeDialog(els.summaryDialog));

    els.chartMode?.addEventListener('change', (event) => {
      state.charts.mode = event.target.value;
      state.charts.tcg = 'all';
      state.charts.edition = 'all';
      state.charts.language = 'all';
      state.charts.variant = 'all';
      state.charts.priceBand = 'all';
      renderCharts();
    });
    els.chartTcgFilter?.addEventListener('change', (event) => {
      state.charts.tcg = event.target.value;
      state.charts.edition = 'all';
      state.charts.language = 'all';
      state.charts.variant = 'all';
      state.charts.priceBand = 'all';
      renderCharts();
    });
    els.chartEditionFilter?.addEventListener('change', (event) => {
      state.charts.edition = event.target.value;
      state.charts.language = 'all';
      state.charts.variant = 'all';
      state.charts.priceBand = 'all';
      renderCharts();
    });
    els.chartLanguageFilter?.addEventListener('change', (event) => {
      state.charts.language = event.target.value;
      state.charts.variant = 'all';
      state.charts.priceBand = 'all';
      renderCharts();
    });
    els.chartVariantFilter?.addEventListener('change', (event) => {
      state.charts.variant = event.target.value;
      state.charts.priceBand = 'all';
      renderCharts();
    });
    els.chartPriceBandFilter?.addEventListener('change', (event) => {
      state.charts.priceBand = event.target.value;
      renderCharts();
    });

    els.wishlistForm?.addEventListener('submit', handleWishlistSubmit);
    els.collectionForm?.addEventListener('submit', handleCollectionSubmit);
    els.wishlistList?.addEventListener('click', handleListClick);
    els.localItemsList?.addEventListener('click', handleListClick);

    [els.quickExport, els.menuExportPortfolio, els.exportPortfolio].forEach((button) => button?.addEventListener('click', exportPortfolioData));
    [els.menuExportWishlist, els.exportWishlist].forEach((button) => button?.addEventListener('click', exportWishlistData));

    els.marketRefreshAll?.addEventListener('click', () => {
      showToast('Botón preparado. El conector de precios se añadirá en la siguiente fase.');
    });

    $$('.summary-metric').forEach((button) => {
      button.addEventListener('click', () => renderSummaryDialog(button.dataset.summaryMetric));
    });

    $$('input[list]').forEach((input) => {
      input.addEventListener('blur', () => {
        const field = input.name;
        if (field) input.value = normalizeManualValue(input.value, valuesFor(field));
      });
    });
  }

  function init() {
    const savedTheme = localStorage.getItem(CONFIG.themeKey);
    const preferredTheme = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    setTheme(savedTheme || preferredTheme);
    if (els.menuUpdatedAt && metadata.generatedAt) {
      els.menuUpdatedAt.textContent = `Datos: ${new Date(metadata.generatedAt).toLocaleDateString('es-ES')}`;
    }
    bindEvents();
    refreshAll();
    showSection('summary');
  }

  init();
})();
