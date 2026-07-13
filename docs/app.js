(() => {
  'use strict';

  const sourceData = window.portfolioData || { metadata: {}, cards: [], review: [], aggregates: {} };
  const metadata = sourceData.metadata || {};
  const CONFIG = {
    minUnitPurchaseValue: Number(metadata.minUnitPurchaseValue ?? 20),
    pageSize: 24,
    baseOperation: 'compra',
  };

  const formatter = new Intl.NumberFormat('es-ES', { style: 'currency', currency: 'EUR' });
  const intFormatter = new Intl.NumberFormat('es-ES', { maximumFractionDigits: 0 });
  const oneDecimalFormatter = new Intl.NumberFormat('es-ES', { maximumFractionDigits: 1 });

  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => Array.from(document.querySelectorAll(selector));
  const els = {
    themeToggle: $('#themeToggle'),
    menuToggle: $('#menuToggle'),
    menuDialog: $('#menuDialog'),
    closeMenu: $('#closeMenu'),
    menuUpdatedAt: $('#menuUpdatedAt'),
    heroRule: $('#heroRule'),
    heroRows: $('#heroRows'),
    heroHidden: $('#heroHidden'),
    heroValue: $('#heroValue'),
    metricVisibleRows: $('#metricVisibleRows'),
    metricThreshold: $('#metricThreshold'),
    metricTotalValue: $('#metricTotalValue'),
    metricAvgUnit: $('#metricAvgUnit'),
    metricSourceRows: $('#metricSourceRows'),
    metricImages: $('#metricImages'),
    filteredCount: $('#filteredCount'),
    searchInput: $('#searchInput'),
    tcgFilter: $('#tcgFilter'),
    editionFilter: $('#editionFilter'),
    languageFilter: $('#languageFilter'),
    priceBandFilter: $('#priceBandFilter'),
    sortSelect: $('#sortSelect'),
    activeRuleLabel: $('#activeRuleLabel'),
    cardsGrid: $('#cardsGrid'),
    emptyState: $('#emptyState'),
    prevPage: $('#prevPage'),
    nextPage: $('#nextPage'),
    pageInfo: $('#pageInfo'),
    topEditions: $('#topEditions'),
    topCards: $('#topCards'),
    byTcg: $('#byTcg'),
    byPriceBand: $('#byPriceBand'),
    healthSource: $('#healthSource'),
    healthNonPurchase: $('#healthNonPurchase'),
    healthBelow: $('#healthBelow'),
    healthReview: $('#healthReview'),
    reviewSummary: $('#reviewSummary'),
    reviewTableBody: $('#reviewTableBody'),
    cardModal: $('#cardModal'),
    closeModal: $('#closeModal'),
    modalBody: $('#modalBody'),
    metricsDialog: $('#metricsDialog'),
    closeMetrics: $('#closeMetrics'),
    metricsTitle: $('#metricsTitle'),
    metricsBody: $('#metricsBody'),
  };

  const state = {
    query: '',
    tcg: 'all',
    edition: 'all',
    language: 'all',
    priceBand: 'all',
    sort: 'unit_desc',
    page: 1,
  };

  function toNumber(value) {
    const number = Number(value || 0);
    return Number.isFinite(number) ? number : 0;
  }

  function text(value) {
    return String(value ?? '').trim();
  }

  function escapeHtml(value) {
    return text(value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function formatCurrency(value) {
    return formatter.format(toNumber(value));
  }

  function formatNumber(value) {
    return intFormatter.format(toNumber(value));
  }

  function formatDecimal(value) {
    return oneDecimalFormatter.format(toNumber(value));
  }

  function normalizedOperation(card) {
    return text(card.operation).toLowerCase();
  }

  function normalizeCard(card) {
    const unit = toNumber(card.unitPurchaseValue ?? card.unitPrice);
    const quantity = toNumber(card.quantity);
    const total = toNumber(card.totalPurchaseValue ?? card.total);
    return {
      ...card,
      unitPurchaseValue: unit,
      unitPrice: unit,
      quantity,
      totalPurchaseValue: total,
      total,
      operationNormalized: normalizedOperation(card),
      searchBlob: [card.cardName, card.name, card.edition, card.language, card.tcg, card.sellerBuyer, card.orderNumber, card.priceBand]
        .map(text)
        .join(' ')
        .toLowerCase(),
    };
  }

  const cards = (sourceData.cards || [])
    .map(normalizeCard)
    .filter((card) => card.operationNormalized === CONFIG.baseOperation && card.unitPurchaseValue >= CONFIG.minUnitPurchaseValue);

  function uniqueValues(key) {
    return [...new Set(cards.map((card) => text(card[key])).filter(Boolean))]
      .sort((a, b) => a.localeCompare(b, 'es', { sensitivity: 'base' }));
  }

  function populateSelect(select, values, allLabel) {
    if (!select) return;
    select.innerHTML = `<option value="all">${escapeHtml(allLabel)}</option>` + values
      .map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`)
      .join('');
  }

  function compareDateDesc(a, b) {
    return new Date(b.date || 0).getTime() - new Date(a.date || 0).getTime();
  }

  function filteredCards() {
    const query = state.query.toLowerCase().trim();
    let result = cards.filter((card) => {
      if (query && !card.searchBlob.includes(query)) return false;
      if (state.tcg !== 'all' && card.tcg !== state.tcg) return false;
      if (state.edition !== 'all' && card.edition !== state.edition) return false;
      if (state.language !== 'all' && card.language !== state.language) return false;
      if (state.priceBand !== 'all' && card.priceBand !== state.priceBand) return false;
      return true;
    });

    result = [...result].sort((a, b) => {
      switch (state.sort) {
        case 'total_desc': return b.totalPurchaseValue - a.totalPurchaseValue;
        case 'date_desc': return compareDateDesc(a, b);
        case 'name_asc': return text(a.cardName).localeCompare(text(b.cardName), 'es', { sensitivity: 'base' });
        case 'edition_asc': return text(a.edition).localeCompare(text(b.edition), 'es', { sensitivity: 'base' });
        case 'unit_desc':
        default: return b.unitPurchaseValue - a.unitPurchaseValue;
      }
    });
    return result;
  }

  function aggregateRows(list, key, limit = 10) {
    const map = new Map();
    list.forEach((card) => {
      const label = text(card[key]) || 'Sin dato';
      const item = map.get(label) || { label, total: 0, quantity: 0, count: 0 };
      item.total += toNumber(card.totalPurchaseValue);
      item.quantity += toNumber(card.quantity);
      item.count += 1;
      map.set(label, item);
    });
    return [...map.values()].sort((a, b) => b.total - a.total).slice(0, limit);
  }

  function renderBarList(container, rows, valueLabel = 'total') {
    if (!container) return;
    if (!rows.length) {
      container.innerHTML = '<p class="muted">Sin datos.</p>';
      return;
    }
    const maxValue = Math.max(...rows.map((row) => toNumber(row.total || row.value || row.quantity)), 1);
    container.innerHTML = rows.map((row) => {
      const value = toNumber(row.total || row.value || row.quantity);
      const width = Math.max(4, Math.round((value / maxValue) * 100));
      const displayValue = valueLabel === 'quantity' ? `${formatDecimal(value)} uds.` : formatCurrency(value);
      return `
        <div class="bar-row">
          <div class="bar-row-main"><span title="${escapeHtml(row.label)}">${escapeHtml(row.label)}</span><strong>${displayValue}</strong></div>
          <div class="bar-track"><div class="bar-fill" style="width:${width}%"></div></div>
        </div>`;
    }).join('');
  }

  function cardImageHtml(card, context = 'card') {
    const normal = text(card.images?.normal || card.images?.large || card.images?.artCrop);
    const placeholderText = text(card.tcg).slice(0, 18) || 'TCG';
    if (normal) {
      return `<img src="${escapeHtml(normal)}" alt="${escapeHtml(card.cardName)}" loading="lazy" />`;
    }
    return `<div class="card-placeholder"><span>${escapeHtml(placeholderText)}</span><small>${context === 'modal' ? 'Imagen pendiente' : 'Sin imagen'}</small></div>`;
  }

  function renderCard(card) {
    return `
      <article class="collection-card">
        <div class="card-image-stage">
          <span class="card-badge">${escapeHtml(card.priceBand || '≥20€')}</span>
          ${cardImageHtml(card)}
        </div>
        <div class="card-body">
          <div>
            <h3 class="card-title">${escapeHtml(card.cardName || card.name)}</h3>
            <p class="card-meta">${escapeHtml(card.edition || 'Sin edición')} · ${escapeHtml(card.language || 'Sin idioma')} · ${escapeHtml(card.tcg || 'Sin TCG')}</p>
          </div>
          <div class="card-kpis">
            <div><span>Unidad</span><strong>${formatCurrency(card.unitPurchaseValue)}</strong></div>
            <div><span>Qty</span><strong>${formatDecimal(card.quantity)}</strong></div>
            <div><span>Total</span><strong>${formatCurrency(card.totalPurchaseValue)}</strong></div>
          </div>
          <div class="card-footer">
            <small>Fila Excel ${escapeHtml(card.sourceRow)}</small>
            <button class="detail-button" type="button" data-card-id="${escapeHtml(card.id)}">Detalle</button>
          </div>
        </div>
      </article>`;
  }

  function renderCards() {
    const list = filteredCards();
    const totalPages = Math.max(1, Math.ceil(list.length / CONFIG.pageSize));
    if (state.page > totalPages) state.page = totalPages;
    const start = (state.page - 1) * CONFIG.pageSize;
    const pageCards = list.slice(start, start + CONFIG.pageSize);

    els.filteredCount.textContent = formatNumber(list.length);
    els.pageInfo.textContent = `Página ${state.page}/${totalPages}`;
    els.prevPage.disabled = state.page <= 1;
    els.nextPage.disabled = state.page >= totalPages;
    els.cardsGrid.innerHTML = pageCards.map(renderCard).join('');
    els.emptyState.classList.toggle('hidden', list.length > 0);

    $$('.detail-button').forEach((button) => {
      button.addEventListener('click', () => openCardModal(button.dataset.cardId));
    });
  }

  function renderSummary() {
    const visibleValue = cards.reduce((sum, card) => sum + toNumber(card.totalPurchaseValue), 0);
    const avgUnit = cards.length ? cards.reduce((sum, card) => sum + toNumber(card.unitPurchaseValue), 0) / cards.length : 0;
    const imageStats = metadata.imageResolution || {};
    const resolvedImages = toNumber(imageStats.resolvedRows);
    const totalImageRows = toNumber(imageStats.totalRows || cards.length);
    const hiddenBelow = toNumber(metadata.excludedPurchaseRowsBelowThreshold);

    els.heroRule.textContent = `Compra · Unit Price ≥ ${formatCurrency(CONFIG.minUnitPurchaseValue)}`;
    els.heroRows.textContent = formatNumber(cards.length);
    els.heroHidden.textContent = formatNumber(hiddenBelow);
    els.heroValue.textContent = formatCurrency(visibleValue);
    els.metricVisibleRows.textContent = formatNumber(cards.length);
    els.metricThreshold.textContent = formatCurrency(CONFIG.minUnitPurchaseValue);
    els.metricTotalValue.textContent = formatCurrency(visibleValue);
    els.metricAvgUnit.textContent = formatCurrency(avgUnit);
    els.metricSourceRows.textContent = formatNumber(metadata.totalSourceRows || 0);
    els.metricImages.textContent = `${formatNumber(resolvedImages)}/${formatNumber(totalImageRows)}`;
    els.activeRuleLabel.textContent = `Filtro base: Tipo Operación = Compra y Unit Price ≥ ${formatCurrency(CONFIG.minUnitPurchaseValue)}.`;
    els.menuUpdatedAt.textContent = metadata.generatedAt ? `Actualizado ${new Date(metadata.generatedAt).toLocaleString('es-ES')}` : 'Actualización no informada';
  }

  function renderAnalytics() {
    const byBand = aggregateRows(cards, 'priceBand', 12);
    renderBarList(els.topEditions, aggregateRows(cards, 'edition', 10));
    renderBarList(els.topCards, aggregateRows(cards, 'cardName', 10));
    renderBarList(els.byTcg, aggregateRows(cards, 'tcg', 10));
    renderBarList(els.byPriceBand, byBand);
  }

  function renderReview() {
    const review = sourceData.review || [];
    els.healthSource.textContent = metadata.sourceFile || 'Excel';
    els.healthNonPurchase.textContent = formatNumber(metadata.excludedNonPurchaseRows || 0);
    els.healthBelow.textContent = formatNumber(metadata.excludedPurchaseRowsBelowThreshold || 0);
    els.healthReview.textContent = formatNumber(review.length);
    els.reviewSummary.textContent = review.length
      ? `${formatNumber(review.length)} entradas visibles requieren revisión de campos.`
      : 'No se han detectado errores de nombre, edición o idioma dentro del dataset visible.';

    els.reviewTableBody.innerHTML = review.length ? review.slice(0, 80).map((item) => `
      <tr>
        <td>${escapeHtml(item.cardName)}</td>
        <td>${escapeHtml(item.edition)}</td>
        <td>${escapeHtml(item.language)}</td>
        <td>${escapeHtml(item.reason)}</td>
        <td>${escapeHtml(item.sourceRow)}</td>
      </tr>`).join('') : '<tr><td colspan="5">Sin incidencias visibles.</td></tr>';
  }

  function openCardModal(cardId) {
    const card = cards.find((item) => item.id === cardId);
    if (!card) return;
    const scryfallLink = text(card.imageResolution?.searchUri || card.scryfall?.uri || card.scryfall?.searchUri);
    const sourceLink = text(card.imageResolution?.sourceUrl || card.imageResolution?.searchUri || '');
    const imageLink = text(card.images?.large || card.images?.normal || card.images?.small);
    els.modalBody.innerHTML = `
      <div class="modal-layout">
        <div class="modal-image-stage">${cardImageHtml(card, 'modal')}</div>
        <div>
          <p class="eyebrow">Detalle de entrada</p>
          <h3 class="modal-title">${escapeHtml(card.cardName || card.name)}</h3>
          <p class="modal-subtitle">${escapeHtml(card.edition || 'Sin edición')} · ${escapeHtml(card.language || 'Sin idioma')} · ${escapeHtml(card.tcg || 'Sin TCG')}</p>
          <div class="modal-stats">
            <div class="modal-stat"><span>Valor unitario</span><strong>${formatCurrency(card.unitPurchaseValue)}</strong></div>
            <div class="modal-stat"><span>Cantidad</span><strong>${formatDecimal(card.quantity)}</strong></div>
            <div class="modal-stat"><span>Total compra</span><strong>${formatCurrency(card.totalPurchaseValue)}</strong></div>
          </div>
          <div class="modal-list">
            <div><span>Pedido</span><strong>${escapeHtml(card.orderNumber || 'Sin pedido')}</strong></div>
            <div><span>Fecha</span><strong>${escapeHtml(card.date || 'Sin fecha')}</strong></div>
            <div><span>Vendedor/Comprador</span><strong>${escapeHtml(card.sellerBuyer || 'Sin dato')}</strong></div>
            <div><span>Playset</span><strong>${escapeHtml(card.playset || 'Sin dato')}</strong></div>
            <div><span>Banda precio</span><strong>${escapeHtml(card.priceBand || '')}</strong></div>
            <div><span>Fila Excel</span><strong>${escapeHtml(card.sourceRow)}</strong></div>
          </div>
          <div class="modal-links">
            ${scryfallLink ? `<a href="${escapeHtml(scryfallLink)}" target="_blank" rel="noopener">Abrir Scryfall</a>` : ''}
            ${imageLink ? `<a href="${escapeHtml(imageLink)}" target="_blank" rel="noopener">Abrir imagen</a>` : ''}
            ${sourceLink && sourceLink !== scryfallLink ? `<a href="${escapeHtml(sourceLink)}" target="_blank" rel="noopener">Fuente imagen</a>` : ''}
          </div>
        </div>
      </div>`;
    els.cardModal.showModal();
  }

  function openMetric(metric) {
    const rows = {
      visible: [
        ['Filas publicadas', formatNumber(cards.length)],
        ['Filas fuente Excel', formatNumber(metadata.totalSourceRows || 0)],
        ['Regla', metadata.displayRule || 'Compra y Unit Price >= 20 EUR'],
      ],
      threshold: [
        ['Umbral unitario', formatCurrency(CONFIG.minUnitPurchaseValue)],
        ['Modo de umbral', metadata.thresholdMode || 'unit_purchase_value'],
        ['Compras ocultas por umbral', formatNumber(metadata.excludedPurchaseRowsBelowThreshold || 0)],
      ],
      total: [
        ['Valor compra visible', formatCurrency(cards.reduce((sum, card) => sum + card.totalPurchaseValue, 0))],
        ['Unidades visibles', formatDecimal(cards.reduce((sum, card) => sum + card.quantity, 0))],
      ],
      avg: [
        ['Precio medio unitario', formatCurrency(cards.length ? cards.reduce((sum, card) => sum + card.unitPurchaseValue, 0) / cards.length : 0)],
        ['Precio máximo unitario', formatCurrency(Math.max(...cards.map((card) => card.unitPurchaseValue), 0))],
      ],
      source: [
        ['Fuente', metadata.sourceFile || 'Excel'],
        ['Hoja', metadata.sourceSheet || 'Colección'],
        ['Filas compra', formatNumber(metadata.purchaseRows || 0)],
        ['No compra excluidas', formatNumber(metadata.excludedNonPurchaseRows || 0)],
      ],
      quality: [
        ['Imagenes resueltas', `${formatNumber(metadata.imageResolution?.resolvedRows || 0)} / ${formatNumber(metadata.imageResolution?.totalRows || cards.length)}`],
        ['Scryfall MTG', formatNumber(metadata.imageResolution?.scryfallEndpointRows || 0)],
        ['Riftbound Scrydex', formatNumber(metadata.imageResolution?.scrydexRows || 0)],
        ['One Piece DB', formatNumber(metadata.imageResolution?.onePieceDbRows || 0)],
        ['Productos/manuales', formatNumber(metadata.imageResolution?.manualProductRows || 0)],
        ['Pendientes', formatNumber(metadata.imageResolution?.pendingRows || 0)],
        ['Revision campos visibles', formatNumber((sourceData.review || []).length)],
      ],
    }[metric] || [];

    const titles = {
      visible: 'Dataset web',
      threshold: 'Umbral de publicación',
      total: 'Valor visible',
      avg: 'Precio medio',
      source: 'Fuente Excel',
      quality: 'Calidad de datos',
    };

    els.metricsTitle.textContent = titles[metric] || 'Detalle';
    els.metricsBody.innerHTML = `<div class="metrics-list">${rows.map(([label, value]) => `
      <div class="metrics-row"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`).join('')}</div>`;
    els.metricsDialog.showModal();
  }

  function bindEvents() {
    els.themeToggle.addEventListener('click', () => {
      document.body.classList.toggle('light');
      localStorage.setItem('tcg-theme', document.body.classList.contains('light') ? 'light' : 'dark');
    });
    els.menuToggle.addEventListener('click', () => els.menuDialog.showModal());
    els.closeMenu.addEventListener('click', () => els.menuDialog.close());
    els.closeModal.addEventListener('click', () => els.cardModal.close());
    els.closeMetrics.addEventListener('click', () => els.metricsDialog.close());

    $$('.menu-nav a').forEach((link) => link.addEventListener('click', () => els.menuDialog.close()));
    $$('.summary-metric').forEach((button) => button.addEventListener('click', () => openMetric(button.dataset.metric)));

    els.searchInput.addEventListener('input', (event) => { state.query = event.target.value; state.page = 1; renderCards(); });
    els.tcgFilter.addEventListener('change', (event) => { state.tcg = event.target.value; state.page = 1; renderCards(); });
    els.editionFilter.addEventListener('change', (event) => { state.edition = event.target.value; state.page = 1; renderCards(); });
    els.languageFilter.addEventListener('change', (event) => { state.language = event.target.value; state.page = 1; renderCards(); });
    els.priceBandFilter.addEventListener('change', (event) => { state.priceBand = event.target.value; state.page = 1; renderCards(); });
    els.sortSelect.addEventListener('change', (event) => { state.sort = event.target.value; state.page = 1; renderCards(); });
    els.prevPage.addEventListener('click', () => { state.page = Math.max(1, state.page - 1); renderCards(); });
    els.nextPage.addEventListener('click', () => { state.page += 1; renderCards(); });
  }

  function init() {
    if (localStorage.getItem('tcg-theme') === 'light') {
      document.body.classList.add('light');
    }
    populateSelect(els.tcgFilter, uniqueValues('tcg'), 'Todos');
    populateSelect(els.editionFilter, uniqueValues('edition'), 'Todas');
    populateSelect(els.languageFilter, uniqueValues('language'), 'Todos');
    populateSelect(els.priceBandFilter, ['20€ - 49,99€', '50€ - 99,99€', '100€ - 249,99€', '250€+'], 'Todas');
    renderSummary();
    renderAnalytics();
    renderReview();
    renderCards();
    bindEvents();
  }

  init();
})();
