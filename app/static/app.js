function isoMinuteNow() {
  const now = new Date();
  const localTime = new Date(now.getTime() - now.getTimezoneOffset() * 60_000);
  return localTime.toISOString().slice(0, 16);
}

async function jsonRequest(url, options = {}) {
  const response = await fetch(url, {headers: {'Content-Type': 'application/json'}, ...options});
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || `Request failed (${response.status})`);
  return body;
}

window.initOrderForm = function () {
  const form = document.querySelector('#order-form');
  form.paid_at.value = isoMinuteNow();
  document.querySelector('[data-add-item]').addEventListener('click', () => {
    document.querySelector('#item-rows').insertAdjacentHTML('beforeend', '<div class="item-row"><label class="item-input item-name">Item<input placeholder="Item name" required></label><label class="item-input">Quantity<input data-item-quantity type="number" value="1" min="1" required></label><label class="item-input">Price (€)<input data-item-price type="number" value="0.00" min="0" step="0.01" required></label><button type="button" class="icon" data-remove-item aria-label="Remove item">×</button></div>');
  });
  form.addEventListener('click', event => {
    if (event.target.matches('[data-remove-item]') && document.querySelectorAll('.item-row').length > 1) event.target.closest('.item-row').remove();
  });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const message = document.querySelector('#form-message');
    const rows = [...document.querySelectorAll('.item-row')];
    const paidAt = new Date(form.paid_at.value).toISOString();
    const data = {
      external_order_id: form.external_order_id.value.trim(), order_type: form.order_type.value,
      table_number: form.table_number.value.trim() || null,
      staff_name: form.staff_name.value.trim() || null, ordered_at: paidAt, paid_at: paidAt,
      items: rows.map(row => ({
        name: row.querySelector('.item-name input').value.trim(),
        quantity: Number(row.querySelector('[data-item-quantity]').value),
        price: row.querySelector('[data-item-price]').value
      }))
    };
    try {
      message.textContent = 'Creating…';
      const order = await jsonRequest('/api/orders', {method: 'POST', body: JSON.stringify(data)});
      location.href = `/orders/${order.id}/qr`;
    } catch (error) { message.textContent = error.message; message.className = 'error'; }
  });
};

window.initScanpoints = function () {
  const list = document.querySelector('[data-scanpoint-list]');
  const form = document.querySelector('#scanpoint-form');
  const message = document.querySelector('#scanpoint-message');

  function card(scanpoint) {
    const article = document.createElement('article');
    article.className = 'scanpoint-card';
    const qr = document.createElement('img');
    qr.src = `/api/scanpoints/${scanpoint.id}/qr`;
    qr.alt = `QR code for ${scanpoint.label}`;
    const body = document.createElement('div');
    const heading = document.createElement('h3');
    heading.textContent = scanpoint.label;
    const meta = document.createElement('p');
    meta.textContent = `${scanpoint.serial_number} · ${scanpoint.status} · ${scanpoint.table_label || 'Unassigned'}`;
    const url = document.createElement('code');
    url.textContent = scanpoint.scan_url;
    body.append(heading, meta, url);
    article.append(qr, body);
    return article;
  }

  async function load() {
    try {
      const scanpoints = await jsonRequest('/api/scanpoints');
      list.replaceChildren(...scanpoints.map(card));
      if (!scanpoints.length) list.textContent = 'No scanpoints provisioned yet.';
    } catch (error) { list.textContent = error.message; }
  }
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const data = {
      serial_number: form.serial_number.value.trim(),
      label: form.label.value.trim(),
      table_ref: form.table_ref.value.trim() || null
    };
    try {
      message.textContent = 'Provisioning…';
      await jsonRequest('/api/scanpoints', {method: 'POST', body: JSON.stringify(data)});
      form.reset();
      message.textContent = 'Scanpoint provisioned.';
      await load();
    } catch (error) { message.textContent = error.message; message.className = 'error'; }
  });
  load();
};

window.initReviewForm = function () {
  const form = document.querySelector('#review-form');
  form.created_at.value = isoMinuteNow();
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const message = document.querySelector('#review-message');
    const data = {
      rating: Number(form.rating.value), comment: form.comment.value.trim() || null,
      reviewer_display_name: form.reviewer_display_name.value.trim() || null,
      created_at: new Date(form.created_at.value).toISOString()
    };
    try {
      message.textContent = 'Creating…';
      await jsonRequest('/api/reviews/mock', {method: 'POST', body: JSON.stringify(data)});
      if (form.run_matcher.checked) await jsonRequest('/api/matching/run', {method: 'POST'});
      location.href = '/';
    } catch (error) { message.textContent = error.message; message.className = 'error'; }
  });
};

window.initCustomerReviewForm = function () {
  const form = document.querySelector('#customer-review-form');
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const message = document.querySelector('#customer-review-message');
    const selectedRating = form.querySelector('input[name="rating"]:checked');
    if (!selectedRating) {
      message.textContent = 'Please choose a star rating.';
      message.className = 'error';
      return;
    }
    const data = {
      token: form.dataset.token,
      rating: Number(selectedRating.value),
      comment: form.comment.value.trim() || null,
      reviewer_display_name: form.reviewer_display_name.value.trim() || null
    };
    const submit = form.querySelector('button[type="submit"]');
    try {
      submit.disabled = true;
      submit.textContent = 'Posting…';
      message.textContent = '';
      const result = await jsonRequest('/api/reviews/mock/customer', {method: 'POST', body: JSON.stringify(data)});
      location.href = result.thank_you_url;
    } catch (error) {
      message.textContent = error.message;
      message.className = 'error';
      submit.disabled = false;
      submit.textContent = 'Post mock review';
    }
  });
};

window.initRatingDistributions = function () {
  const modal = document.querySelector('[data-rating-modal]');
  if (!modal) return;

  const title = modal.querySelector('#rating-modal-title');
  const summary = modal.querySelector('#rating-modal-summary');
  const chart = modal.querySelector('[data-rating-chart]');
  const accessible = modal.querySelector('[data-rating-chart-accessible]');
  const closeButton = modal.querySelector('.rating-modal-close');
  const workerContext = modal.querySelector('[data-worker-context]');
  const workerRaw = modal.querySelector('[data-worker-raw]');
  const workerRebalanced = modal.querySelector('[data-worker-rebalanced]');
  const workerAdjustment = modal.querySelector('[data-worker-adjustment]');
  const workerTotal = modal.querySelector('[data-worker-total]');
  const lowSampleWarning = modal.querySelector('[data-worker-low-sample]');
  let previousFocus = null;

  function percentageLabel(count, total) {
    return `${total ? ((count / total) * 100).toFixed(1) : '0.0'}%`;
  }

  function buildAccessibleTable(name, counts, total) {
    const table = document.createElement('table');
    const caption = document.createElement('caption');
    caption.textContent = `Accessible rating distribution for ${name}`;
    table.appendChild(caption);

    const header = document.createElement('thead');
    const headerRow = document.createElement('tr');
    ['Rating', 'Eligible reviews', 'Percentage'].forEach(label => {
      const cell = document.createElement('th');
      cell.scope = 'col';
      cell.textContent = label;
      headerRow.appendChild(cell);
    });
    header.appendChild(headerRow);
    table.appendChild(header);

    const body = document.createElement('tbody');
    [5, 4, 3, 2, 1].forEach(rating => {
      const row = document.createElement('tr');
      [`${rating} stars`, String(counts[rating]), percentageLabel(counts[rating], total)].forEach(value => {
        const cell = document.createElement('td');
        cell.textContent = value;
        row.appendChild(cell);
      });
      body.appendChild(row);
    });
    table.appendChild(body);
    accessible.replaceChildren(table);
  }

  function openDistribution(trigger) {
    previousFocus = trigger;
    const name = trigger.dataset.ratingName;
    const average = trigger.dataset.ratingAverage;
    const total = Number(trigger.dataset.ratingTotal);
    const counts = {};
    [1, 2, 3, 4, 5].forEach(rating => {
      counts[rating] = Number(trigger.getAttribute(`data-rating-${rating}`));
    });

    title.textContent = `Rating distribution for ${name}`;
    summary.textContent = `${average} average stars · ${total} eligible review${total === 1 ? '' : 's'}`;
    const isWorker = trigger.dataset.ratingKind === 'worker';
    workerContext.hidden = !isWorker;
    lowSampleWarning.hidden = !isWorker || trigger.dataset.ratingLowSample !== 'true';
    if (isWorker) {
      workerRaw.textContent = `${average} stars`;
      workerRebalanced.textContent = `${trigger.dataset.ratingRebalanced} stars`;
      workerAdjustment.textContent = trigger.dataset.ratingAdjustment;
      workerTotal.textContent = String(total);
    }
    chart.replaceChildren();
    [5, 4, 3, 2, 1].forEach(rating => {
      const count = counts[rating];
      const percentage = total ? (count / total) * 100 : 0;
      const row = document.createElement('div');
      row.className = 'distribution-row';

      const label = document.createElement('span');
      label.className = 'distribution-label';
      label.textContent = `${rating} stars`;

      const track = document.createElement('span');
      track.className = 'distribution-track';
      const fill = document.createElement('span');
      fill.className = 'distribution-fill';
      fill.style.width = `${percentage}%`;
      track.appendChild(fill);

      const value = document.createElement('span');
      value.className = 'distribution-value';
      value.textContent = `${count} · ${percentageLabel(count, total)}`;

      row.append(label, track, value);
      chart.appendChild(row);
    });
    buildAccessibleTable(name, counts, total);
    modal.hidden = false;
    document.body.classList.add('modal-open');
    requestAnimationFrame(() => closeButton.focus());
  }

  function closeDistribution() {
    if (modal.hidden) return;
    modal.hidden = true;
    document.body.classList.remove('modal-open');
    const focusTarget = previousFocus;
    previousFocus = null;
    if (focusTarget && focusTarget.isConnected) focusTarget.focus();
  }

  document.querySelectorAll('[data-rating-trigger]').forEach(trigger => {
    trigger.addEventListener('click', () => openDistribution(trigger));
    const row = trigger.closest('.rating-data-row');
    row.addEventListener('click', event => {
      if (!event.target.closest('[data-rating-trigger]')) trigger.click();
    });
  });
  modal.querySelectorAll('[data-rating-modal-close]').forEach(control => {
    control.addEventListener('click', closeDistribution);
  });
  document.addEventListener('keydown', event => {
    if (modal.hidden) return;
    if (event.key === 'Escape') {
      event.preventDefault();
      closeDistribution();
      return;
    }
    if (event.key !== 'Tab') return;
    const focusable = [...modal.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')]
      .filter(element => !element.disabled && !element.hidden);
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });
};

document.querySelectorAll('[data-run-matcher]').forEach(button => button.addEventListener('click', async () => {
  button.disabled = true; button.textContent = 'Matching…';
  try { await jsonRequest('/api/matching/run', {method: 'POST'}); location.reload(); }
  catch (error) { alert(error.message); button.disabled = false; button.textContent = 'Run matcher'; }
}));
