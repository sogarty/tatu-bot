/* ===================================================
   TATU — Telegram Mini App (app.js)
   Без зависимостей. Работает внутри Telegram.
   =================================================== */

'use strict';

/* ===================================================
   CONFIG
   =================================================== */

const API_BASE = '/api/v1/';

// Мастер-контакт вынесен сюда: поменять — одно место.
const MASTER_TELEGRAM = 'https://t.me/aritu_tattoo';

const STATUS_MAP = {
  draft:       { text: 'Черновик',   icon: '📝', cssClass: 'new' },
  new:         { text: 'В очереди',  icon: '⏳', cssClass: 'new' },
  accepted:    { text: 'Принята',    icon: '✅', cssClass: 'accepted' },
  in_progress: { text: 'Создаётся',  icon: '🖌',  cssClass: 'in_progress' },
  scheduled:   { text: 'Записана',   icon: '📅', cssClass: 'scheduled' },
  completed:   { text: 'Завершена',  icon: '✨', cssClass: 'completed' },
  rejected:    { text: 'Отклонена',  icon: '❌', cssClass: 'rejected' },
  cancelled:   { text: 'Отменена',   icon: '🚫', cssClass: 'rejected' },
};

const PORTFOLIO_WORKS = [
  { id: 'k01', title: 'Пион', place: 'Бедро', tags: ['color', 'botanical'] },
  { id: 'k02', title: 'Любовь', place: 'Кожа', tags: ['graphic'] },
  { id: 'k03', title: 'Ботаника', place: 'Предплечье', tags: ['graphic', 'botanical'] },
  { id: 'k04', title: 'Фея', place: 'Плечо', tags: ['graphic'] },
  { id: 'k05', title: 'Птица и лилии', place: 'Спина', tags: ['color', 'botanical'] },
  { id: 'k06', title: 'Пион и жуки', place: 'Плечо', tags: ['color', 'botanical'] },
  { id: 'k07', title: 'Осенние цветы', place: 'Рука', tags: ['color', 'botanical'] },
  { id: 'k08', title: 'Паук и линии', place: 'Грудь', tags: ['graphic'] },
  { id: 'k09', title: 'Стебли', place: 'Бок', tags: ['graphic', 'botanical'] },
  { id: 'k10', title: 'Тонкая линия', place: 'Талия', tags: ['graphic'] },
  { id: 'k11', title: 'Орнаментальный рукав', place: 'Рука', tags: ['black'] },
  { id: 'k12', title: 'Чёрный рукав', place: 'Рука', tags: ['black'] },
  { id: 'k13', title: 'Чёрный зверь', place: 'Нога', tags: ['black'] },
  { id: 'k14', title: 'Пантера', place: 'Бедро', tags: ['black'] },
  { id: 'k15', title: 'Ветвь', place: 'Рука', tags: ['graphic', 'botanical'] },
  { id: 'k16', title: 'Леттеринг', place: 'Предплечье', tags: ['graphic'] },
];

const COLOR_LABELS = { bw: 'Чёрно-белая', color: 'Цветная' };
const URGENCY_LABELS = { yes: 'Да, срочно', no: 'Нет, обычная очередь' };

const BRIEF_LABELS = {
  experience_level: 'Опыт',
  preferred_style: 'Стиль',
  inspiration_source: 'Вдохновение',
  importance: 'Важнее всего',
};

const BRIEF_VALUES = {
  experience_level: { none: 'Нет, первая', few: 'Была 1–2', many: 'Было 3+' },
  preferred_style: {
    realism: 'Реализм', graphics: 'Графика', watercolor: 'Акварель',
    geometry: 'Геометрия', other: 'Свой вариант',
  },
  inspiration_source: {
    pinterest: 'Pinterest', instagram: 'Instagram',
    own: 'Свои референсы', dontknow: 'Не знаю',
  },
  importance: { aesthetics: 'Эстетика', meaning: 'Смысл', safety: 'Безопасность' },
};

const TOTAL_STEPS = 8;

const FORM_STEP_NAMES = {
  1: 'Идея',
  2: 'Референсы',
  3: 'Место на теле',
  4: 'Размер',
  5: 'Цвет',
  6: 'Срочность',
  7: 'Вопросы для эскиза',
  8: 'Проверка заявки',
};

// Сколько ждём ответ сервера. Дольше держать человека на спиннере нельзя.
const REQUEST_TIMEOUT_MS = 20000;

// Бесплатный хостинг «засыпает» и просыпается ~50 секунд. Первый запрос
// после пробуждения поэтому может не успеть. Вход (me) повторяем дольше,
// с понятным текстом, чтобы человек не видел ложную ошибку.
const LOGIN_TIMEOUT_MS = 30000;
const LOGIN_RETRIES = 3;
const RESUME_REFRESH_AFTER_MS = 5 * 60 * 1000;

/* ===================================================
   STATE
   =================================================== */

const tg = window.Telegram?.WebApp;

const state = {
  ready: false,
  me: null,             // { user_id, is_admin, first_name }
  settings: null,
  requests: [],
  masterRequests: [],
  currentStep: 1,
  draft: null,
  calendarYear: new Date().getFullYear(),
  calendarMonth: new Date().getMonth(),
  calendarSlots: {},
  lastRequestId: null,
  pendingScheduleId: null,
  sessionRefreshPromise: null,
  lastVisibleAt: Date.now(),
  requestIdempotencyKey: null,
  portfolio: [],
  portfolioLoaded: false,
  adminPortfolio: [],
  editingPortfolioId: null,
  referenceFiles: [],
  referenceObjectUrls: new Map(),
  referenceUploadRequestId: null,
  uploadedReferenceCount: 0,
  portfolioObjectUrls: new Map(),
};

function emptyDraft() {
  return {
    description: '',
    location: '',
    size: '',
    colorMode: '',
    isUrgent: '',
    urgentSurcharge: 0,
    brief: {
      experience_level: '',
      preferred_style: '',
      otherStyle: '',
      inspiration_source: '',
      importance: '',
    },
    references: [],
  };
}

/* ===================================================
   TELEGRAM
   =================================================== */

function haptic(type) {
  try {
    const map = { light: 'lightImpact', medium: 'mediumImpact', heavy: 'heavyImpact' };
    tg?.HapticFeedback?.impactOccurred(map[type] || 'light');
  } catch (e) { /* не критично */ }
}

function tgAlert(message) {
  if (tg?.showAlert) { tg.showAlert(message); return; }
  toast(message);
}

function toast(message, ms = 2600) {
  const el = document.getElementById('toast');
  if (!el) return;
  el.textContent = message;
  el.classList.remove('hidden');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.add('hidden'), ms);
}

function initTelegram() {
  if (tg) {
    try {
      tg.ready();
      tg.expand();
      tg.setHeaderColor?.('#07070A');
      tg.setBackgroundColor?.('#07070A');
      tg.BackButton?.hide?.();
    } catch (e) { /* не критично */ }
  }
}

/* ===================================================
   API
   =================================================== */

function authHeader() {
  // Telegram кладёт подписанную строку в initData.
  // Без неё сервер не может доверять запросу.
  const raw = tg?.initData || '';
  return raw ? { Authorization: 'TelegramWebApp ' + raw } : {};
}

async function apiFetch(endpoint, options = {}) {
  const { timeoutMs, ...fetchOptions } = options;
  const isFormData = typeof FormData !== 'undefined' && fetchOptions.body instanceof FormData;
  const headers = Object.assign(
    isFormData ? {} : { 'Content-Type': 'application/json' },
    authHeader(),
    fetchOptions.headers || {}
  );

  let res;
  let timer;
  try {
    // Таймаут обязателен: на мобильной связи запрос может «висеть» вечно,
    // и человек останется навсегда на экране загрузки.
    const controller = new AbortController();
    timer = setTimeout(
      () => controller.abort(),
      timeoutMs || REQUEST_TIMEOUT_MS
    );
    res = await fetch(API_BASE + endpoint, {
      ...fetchOptions,
      headers,
      signal: controller.signal,
    });

    // The timeout covers body reading too. A server can send headers and then
    // stall while Telegram's WebView waits forever for res.text().
    const text = await res.text();
    clearTimeout(timer);

    let data = null;
    if (text) {
      try { data = JSON.parse(text); } catch (e) { data = null; }
    }

    if (!res.ok) {
      const detail =
        (data && (typeof data.detail === 'string' ? data.detail : null)) ||
        (res.status === 401 ? 'Открой приложение из Telegram' : `Ошибка ${res.status}`);
      return { ok: false, status: res.status, error: detail, data };
    }

    return { ok: true, status: res.status, error: null, data };
  } catch (err) {
    // Abort can happen while reading the response body, not only in fetch().
    // Always clear the timer on every failure path.
    clearTimeout(timer);
    const timeout = err && err.name === 'AbortError';
    return {
      ok: false,
      status: 0,
      error: timeout ? 'Сервер не отвечает. Попробуй ещё раз.' : 'Нет связи с сервером',
      data: null,
    };
  }
}

const apiGet = (endpoint) => apiFetch(endpoint, { method: 'GET' });
const apiPost = (endpoint, body, headers = {}) =>
  apiFetch(endpoint, {
    method: 'POST',
    body: JSON.stringify(body || {}),
    headers,
  });

const apiUpload = (endpoint, formData) =>
  apiFetch(endpoint, { method: 'POST', body: formData });

/* ===================================================
   NAVIGATION
   =================================================== */

function showScreen(screenId) {
  const id = screenId.startsWith('screen-') ? screenId : 'screen-' + screenId;

  document.querySelectorAll('.screen').forEach((s) => s.classList.remove('active'));
  const target = document.getElementById(id);
  if (target) target.classList.add('active');

  window.scrollTo(0, 0);

  const hideNav = ['screen-request-form', 'screen-loading', 'screen-error', 'screen-success'];
  const nav = document.getElementById('bottom-nav');
  if (nav) nav.classList.toggle('hidden', hideNav.includes(id));

  updateBottomNav(id);
}

function updateClientOnlyControls() {
  document.querySelectorAll('[data-client-only]').forEach((element) => {
    element.classList.toggle('hidden', Boolean(state.me?.is_admin));
  });
}

function portfolioImageUrl(work) {
  return work.image_url || `assets/portfolio/${work.id}.jpg`;
}

function renderHomePortfolio() {
  const strip = document.querySelector('.home-work-strip');
  if (!strip || !state.portfolioLoaded) return;
  strip.innerHTML = state.portfolio.slice(0, 3).map((work) => `
    <button onclick="App.openPortfolio()"><img src="${escapeHtml(portfolioImageUrl(work))}" alt="${escapeHtml(work.title)}"><span>${escapeHtml(work.title)}</span></button>`).join('');
}

function renderPortfolio(filter = 'all') {
  const grid = document.getElementById('portfolio-grid');
  if (!grid) return;
  const source = state.portfolioLoaded ? state.portfolio : PORTFOLIO_WORKS;
  const works = filter === 'all' ? source : source.filter((work) => (work.tags || []).includes(filter));
  grid.innerHTML = works.map((work) => `
    <button class="portfolio-tile" data-portfolio-preview="${escapeHtml(String(work.id))}" aria-label="Открыть ${escapeHtml(work.title)}">
      <img src="${escapeHtml(portfolioImageUrl(work))}" alt="${escapeHtml(work.title)} на теле, ${escapeHtml(work.place)}" loading="lazy">
      <figcaption><b>${escapeHtml(work.title)}</b><span>${escapeHtml(work.place)}</span></figcaption>
    </button>`).join('');
  grid.querySelectorAll('[data-portfolio-preview]').forEach((button) => {
    button.addEventListener('click', () => {
      const work = source.find((item) => String(item.id) === button.dataset.portfolioPreview);
      if (work) openImagePreview(portfolioImageUrl(work), work.title);
    });
  });
}

async function loadPortfolio(force = false) {
  if (state.portfolioLoaded && !force) return;
  const res = await apiGet('portfolio');
  if (res.ok && Array.isArray(res.data)) {
    state.portfolio = res.data;
    state.portfolioLoaded = true;
    renderHomePortfolio();
  }
}

async function openPortfolio() {
  const grid = document.getElementById('portfolio-grid');
  if (grid && !state.portfolioLoaded) grid.innerHTML = '<div class="portfolio-loading">Загружаем работы…</div>';
  await loadPortfolio();
  renderPortfolio();
  showScreen('screen-portfolio');
}

function openImagePreview(src, caption = '') {
  const image = document.getElementById('image-preview');
  const label = document.getElementById('image-preview-caption');
  if (!image) return;
  image.src = src;
  image.alt = caption;
  if (label) label.textContent = caption;
  openModal('modal-image-preview');
}

function requireTelegramAuth() {
  if (state.ready) return true;
  toast('Заявки доступны при открытии приложения из Telegram.');
  return false;
}

function filterPortfolio(filter, button) {
  document.querySelectorAll('.portfolio-filters button').forEach((item) => item.classList.toggle('selected', item === button));
  renderPortfolio(filter);
}

function closeIntro() {
  const intro = document.getElementById('intro-overlay');
  if (!intro) return;
  intro.classList.add('intro-closing');
  intro.classList.remove('intro-playing');
  try { sessionStorage.setItem('tatu.intro.seen', '1'); } catch (e) { /* storage can be unavailable */ }
  setTimeout(() => {
    intro.classList.add('hidden');
    intro.classList.remove('intro-closing');
  }, 650);
}

function playIntro() {
  const intro = document.getElementById('intro-overlay');
  if (!intro) return;
  intro.classList.remove('hidden', 'intro-closing', 'intro-playing');
  void intro.offsetWidth;
  intro.classList.add('intro-playing');
  setTimeout(() => intro.classList.contains('hidden') || closeIntro(), 6500);
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);
}

function updateBottomNav(activeScreen) {
  document.querySelectorAll('#bottom-nav .nav-item').forEach((item) => {
    item.classList.toggle('active', item.dataset.screen === activeScreen);
  });
}

function showFatal(title, text) {
  document.getElementById('error-title').textContent = title;
  document.getElementById('error-text').textContent = text;
  showScreen('screen-error');
}

/* ===================================================
   INIT
   =================================================== */

async function init() {
  initTelegram();
  showScreen('screen-loading');

  if (!tg || !tg.initData) {
    // Public pages remain inspectable in a browser; authenticated actions stay Telegram-only.
    state.me = { first_name: 'гость', is_admin: false };
    state.ready = false;
    document.getElementById('home-master-block')?.classList.add('hidden');
    document.getElementById('home-last-request')?.classList.add('hidden');
    updateClientOnlyControls();
    showScreen('screen-home');
    document.getElementById('home-subtitle').textContent =
      'Тонкая графика, ботаника, цвет и тяжёлый чёрный. Эскиз соберём вместе, под тебя и твою идею.';
    loadPortfolio().catch(() => {});
    return;
  }

  setLoadingText('Загружаем...');

  try {
    const res = await loginWithRetry();
    if (!res.ok) {
      showFatal('Не удалось войти', res.error || 'Проверь связь и попробуй снова.');
      return;
    }

    state.me = res.data;
    state.ready = true;
  } catch (err) {
    // Любой неожиданный сбой не должен оставлять человека на спиннере.
    showFatal('Что-то пошло не так', 'Попробуй открыть приложение ещё раз.');
    return;
  } finally {
    setLoadingText('Загружаем...');
  }

  // Показываем вход в кабинет только мастеру
  const masterBlock = document.getElementById('home-master-block');
  if (masterBlock) masterBlock.style.display = state.me.is_admin ? '' : 'none';
  updateClientOnlyControls();

  await goHome();
  if (state.me.is_admin) openMasterCabinet();
}

async function refreshSessionOnResume() {
  if (!tg?.initData || !state.ready || state.sessionRefreshPromise) return;

  state.sessionRefreshPromise = (async () => {
    // Re-read Telegram's current object. Telegram can refresh initData when the
    // WebView is resumed; authHeader() intentionally reads tg.initData live.
    initTelegram();
    const res = await loginWithRetry({ silent: true });
    if (res.ok) {
      state.me = res.data;
      state.ready = true;
      return;
    }

    if (res.status === 401 || res.status === 403) {
      state.ready = false;
      toast('Сессия Telegram устарела. Закрой и снова открой приложение из бота.', 5000);
      return;
    }

    // Keep the already-rendered app usable during a temporary backend outage.
    toast('Сервер временно недоступен. Попробуй действие ещё раз.', 4000);
  })().finally(() => {
    state.sessionRefreshPromise = null;
  });

  await state.sessionRefreshPromise;
}

/** Меняет подпись под спиннером (например, «сервер просыпается»). */
function setLoadingText(text) {
  const el = document.getElementById('loading-text');
  if (el) el.textContent = text;
}

/**
 * Вход с повторами.
 *
 * Бесплатный сервер засыпает после простоя и просыпается не мгновенно.
 * Первый вход после пробуждения может просто не успеть — это не ошибка
 * человека и не повод показывать «Не удалось войти». Повторяем несколько
 * раз и честно пишем, что сервер просыпается.
 */
async function loginWithRetry({ silent = false } = {}) {
  let last = null;

  for (let attempt = 1; attempt <= LOGIN_RETRIES; attempt++) {
    const res = await apiFetch('me', { method: 'GET', timeoutMs: LOGIN_TIMEOUT_MS });

    // Retry only transport failures and temporary gateway/service responses.
    // Never repeat an expired/invalid Telegram authorization.
    const retryable = res.status === 0 || [502, 503, 504].includes(res.status);
    if (res.ok || (res.status && !retryable)) {
      return res;
    }

    last = res;
    if (attempt < LOGIN_RETRIES && retryable) {
      if (!silent) setLoadingText('Сервер просыпается, подожди немного…');
      await sleep(1500 * attempt);
    } else if (!retryable) {
      return res;
    }
  }

  return last || { ok: false, status: 0, error: 'Сервер не отвечает. Попробуй ещё раз.' };
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function retryInit() {
  await init();
}

/* ===================================================
   HOME
   =================================================== */

async function goHome() {
  haptic('light');
  showScreen('screen-home');

  document.getElementById('home-subtitle').textContent =
    'Тонкая графика, ботаника, цвет и тяжёлый чёрный. Эскиз соберём вместе, под тебя и твою идею.';

  loadPortfolio().then(() => renderPortfolio()).catch(() => {});

  if (!state.settings) {
    const s = await apiGet('settings');
    state.settings = s.ok ? s.data : {};
  }

  applyUrgentPrice();

  const reqs = await apiGet('requests?limit=1');
  if (reqs.ok && Array.isArray(reqs.data) && reqs.data.length > 0) {
    showLastRequest(reqs.data[0]);
  } else {
    document.getElementById('home-last-request').classList.add('hidden');
  }
}

function showLastRequest(req) {
  const status = STATUS_MAP[req.status] || STATUS_MAP.new;

  const statusEl = document.getElementById('last-request-status');
  statusEl.className = `status-badge ${status.cssClass}`;
  statusEl.textContent = `${status.icon} ${status.text}`;

  document.getElementById('last-request-info').textContent =
    `#${req.id} — ${(req.description || 'Заявка').slice(0, 40)}…`;

  state.lastRequestId = req.id;
  document.getElementById('home-last-request').classList.remove('hidden');
}

function openLastRequest() {
  if (state.lastRequestId) openRequestDetail(state.lastRequestId);
}

/** Показывает цену за срочность из настроек (если мастер её задал). */
function applyUrgentPrice() {
  const price = Number(state.settings?.urgent_price || 0);
  const label = document.getElementById('urgent-price-label');
  if (!label) return;
  label.textContent = price > 0 ? `${price} ₽` : 'уточняется';
}

/* ===================================================
   REQUEST FORM
   =================================================== */

function startNewRequest() {
  if (!requireTelegramAuth()) return;
  haptic('light');
  state.draft = emptyDraft();
  state.requestIdempotencyKey = window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
  state.currentStep = 1;
  resetFormFields();
  applyUrgentPrice();
  renderStep();
  showScreen('screen-request-form');
}

/** Есть ли уже что-то введённое в текущей форме. */
function hasDraftContent() {
  const d = state.draft;
  if (!d) return false;
  return Boolean(
    d.description ||
      d.location ||
      d.size ||
      d.colorMode ||
      d.isUrgent ||
      state.referenceFiles.length > 0 ||
      Object.values(d.brief || {}).some(Boolean)
  );
}

/**
 * Навигация из нижнего меню: не теряем уже введённую заявку молча.
 * Если форма заполнена — спрашиваем подтверждение.
 */
function navNewRequest() {
  if (!requireTelegramAuth()) return;
  if (hasDraftContent() && !confirm('Начать новую заявку? Введённое не сохранится.')) {
    return;
  }
  startNewRequest();
}

function resetFormFields() {
  const desc = document.getElementById('field-description');
  if (desc) desc.value = '';
  document.getElementById('desc-count').textContent = '0';
  document.getElementById('field-location').value = '';
  document.getElementById('field-size').value = '';
  document.getElementById('field-brief-other').value = '';
  state.referenceFiles = [];
  state.referenceUploadRequestId = null;
  state.uploadedReferenceCount = 0;
  state.draft.references = [];
  state.referenceObjectUrls.forEach((url) => URL.revokeObjectURL(url));
  state.referenceObjectUrls.clear();
  renderReferencePreviews();
  document.getElementById('brief-other-field').classList.add('hidden');

  document
    .querySelectorAll('.color-option, .urgency-option, .chip, .brief-option')
    .forEach((el) => el.classList.remove('selected'));

  document.querySelectorAll('.error-message').forEach((el) => {
    el.classList.add('hidden');
    el.textContent = '';
  });
}

function cancelRequestForm() {
  haptic('light');
  // Подтверждение нужно всегда, когда уже что-то введено —
  // даже если человек вернулся на первый шаг.
  if (!hasDraftContent() || confirm('Отменить создание заявки? Введённое не сохранится.')) {
    state.draft = null;
    goHome();
  }
}

function renderStep() {
  const step = state.currentStep;

  document.getElementById('step-label').textContent = `${FORM_STEP_NAMES[step]} · ${step}/${TOTAL_STEPS}`;
  document.getElementById('progress-fill').style.width = `${(step / TOTAL_STEPS) * 100}%`;

  document.querySelectorAll('.form-step').forEach((s) => s.classList.remove('active'));
  document.getElementById(`step-${step}`)?.classList.add('active');

  const btnBack = document.getElementById('btn-back');
  const btnNext = document.getElementById('btn-next');

  btnBack.disabled = step === 1;
  btnBack.style.opacity = step === 1 ? '0.4' : '1';

  // На последнем шаге кнопка ведёт к отправке, а не «далее»
  btnNext.textContent = step === TOTAL_STEPS ? '✉️ Отправить заявку' : 'Далее →';

  if (step === TOTAL_STEPS) renderReviewCard();
}

function nextStep() {
  haptic('light');
  if (!validateCurrentStep()) return;

  if (state.currentStep === TOTAL_STEPS) {
    submitRequest();
    return;
  }

  state.currentStep += 1;
  renderStep();
}

function prevStep() {
  haptic('light');
  if (state.currentStep <= 1) return;
  state.currentStep -= 1;
  renderStep();
}

function validateCurrentStep() {
  const step = state.currentStep;

  document.querySelectorAll('.error-message').forEach((el) => {
    el.classList.add('hidden');
    el.textContent = '';
  });

  if (step === 1) {
    const desc = document.getElementById('field-description').value.trim();
    if (desc.length < 10) {
      showError('description', 'Расскажи чуть подробнее — минимум 10 символов');
      shakeField('field-description');
      return false;
    }
    state.draft.description = desc;
  }

  if (step === 3) {
    const loc = document.getElementById('field-location').value.trim();
    if (loc.length < 3) {
      showError('location', 'Укажи место — минимум 3 символа');
      shakeField('field-location');
      return false;
    }
    state.draft.location = loc;
  }

  if (step === 4) {
    const size = document.getElementById('field-size').value.trim();
    if (!size) {
      showError('size', 'Укажи размер татуировки');
      shakeField('field-size');
      return false;
    }
    state.draft.size = size;
  }

  if (step === 5 && !state.draft.colorMode) {
    showError('color', 'Выбери цветовой вариант');
    return false;
  }

  if (step === 6 && !state.draft.isUrgent) {
    showError('urgency', 'Выбери вариант срочности');
    return false;
  }

  // Шаг 6 (анкета) — необязательный
  return true;
}

function showError(fieldId, message) {
  const el = document.getElementById(`error-${fieldId}`);
  if (el) {
    el.textContent = message;
    el.classList.remove('hidden');
  }
}

function shakeField(fieldId) {
  const el = document.getElementById(fieldId);
  if (!el) return;
  el.classList.add('shake');
  setTimeout(() => el.classList.remove('shake'), 500);
}

/* ===================================================
   FORM CONTROLS
   =================================================== */

function initFormControls() {
  const desc = document.getElementById('field-description');
  desc?.addEventListener('input', () => {
    document.getElementById('desc-count').textContent = desc.value.length;
  });

  document.getElementById('field-references')?.addEventListener('change', (event) => {
    addReferenceFiles(Array.from(event.target.files || []));
    event.target.value = '';
  });

  // Быстрые кнопки места/размера
  document.querySelectorAll('.quick-buttons .chip').forEach((chip) => {
    chip.addEventListener('click', () => {
      haptic('light');
      const group = chip.closest('.quick-buttons');
      group.querySelectorAll('.chip').forEach((c) => c.classList.remove('selected'));
      chip.classList.add('selected');

      const input = chip.closest('.form-step')?.querySelector('input[type="text"]');
      if (input) input.value = chip.dataset.value;
    });
  });

  // Цвет
  document.querySelectorAll('.color-option').forEach((btn) => {
    btn.addEventListener('click', () => {
      haptic('light');
      state.draft.colorMode = btn.dataset.value;
      document.querySelectorAll('.color-option').forEach((b) => b.classList.remove('selected'));
      btn.classList.add('selected');
    });
  });

  // Срочность
  document.querySelectorAll('.urgency-option').forEach((btn) => {
    btn.addEventListener('click', () => {
      haptic('light');
      state.draft.isUrgent = btn.dataset.value;
      document.querySelectorAll('.urgency-option').forEach((b) => b.classList.remove('selected'));
      btn.classList.add('selected');

      const price = Number(state.settings?.urgent_price || 0);
      state.draft.urgentSurcharge = btn.dataset.value === 'yes' ? price : 0;

      const box = document.getElementById('urgent-surcharge');
      box.classList.toggle('hidden', btn.dataset.value !== 'yes');
      if (btn.dataset.value === 'yes') {
        document.getElementById('surcharge-amount').textContent = price ? `${price} ₽` : 'уточнит мастер';
      }
    });
  });

  // Бриф
  document.querySelectorAll('.brief-option').forEach((btn) => {
    btn.addEventListener('click', () => {
      haptic('light');
      const key = btn.dataset.key;
      const value = btn.dataset.value;

      const group = btn.closest('.brief-options');
      group.querySelectorAll('.brief-option').forEach((b) => b.classList.remove('selected'));
      btn.classList.add('selected');

      state.draft.brief[key] = value;

      const otherBox = document.getElementById('brief-other-field');
      if (key === 'preferred_style' && value === 'other') {
        otherBox.classList.remove('hidden');
        document.getElementById('field-brief-other').focus();
      } else if (key === 'preferred_style') {
        otherBox.classList.add('hidden');
        state.draft.brief.otherStyle = '';
        document.getElementById('field-brief-other').value = '';
      }
    });
  });

  document.getElementById('field-brief-other')?.addEventListener('input', (e) => {
    state.draft.brief.otherStyle = e.target.value.trim();
  });
}

function addReferenceFiles(files) {
  const available = 5 - state.referenceFiles.length;
  const selected = files.slice(0, available);
  if (files.length > available) toast('Можно прикрепить не больше 5 изображений');
  selected.forEach((file) => {
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
      toast('Поддерживаются JPEG, PNG и WebP');
      return;
    }
    if (file.size > 8 * 1024 * 1024) {
      toast('Каждое изображение должно быть не больше 8 МБ');
      return;
    }
    state.referenceFiles.push(file);
  });
  state.draft.references = state.referenceFiles;
  renderReferencePreviews();
}

function removeReference(index) {
  const [file] = state.referenceFiles.splice(index, 1);
  const url = state.referenceObjectUrls.get(file);
  if (url) URL.revokeObjectURL(url);
  state.referenceObjectUrls.delete(file);
  state.draft.references = state.referenceFiles;
  renderReferencePreviews();
}

function renderReferencePreviews() {
  const grid = document.getElementById('references-grid');
  if (!grid) return;
  grid.innerHTML = state.referenceFiles.map((file, index) => {
    let url = state.referenceObjectUrls.get(file);
    if (!url) {
      url = URL.createObjectURL(file);
      state.referenceObjectUrls.set(file, url);
    }
    return `<div class="reference-thumb"><img src="${escapeHtml(url)}" alt="Референс ${index + 1}"><button type="button" class="remove-ref" onclick="App.removeReference(${index})" aria-label="Удалить референс">×</button></div>`;
  }).join('');
}

/* ===================================================
   REVIEW
   =================================================== */

function renderReviewCard() {
  const d = state.draft;

  document.getElementById('review-description').textContent = d.description || '—';
  document.getElementById('review-location').textContent = d.location || '—';
  document.getElementById('review-size').textContent = d.size || '—';
  document.getElementById('review-color').textContent = COLOR_LABELS[d.colorMode] || '—';
  document.getElementById('review-urgency').textContent = URGENCY_LABELS[d.isUrgent] || '—';
  const referenceReview = document.getElementById('review-references');
  referenceReview.innerHTML = d.references?.length
    ? d.references.map((file, index) => {
      const url = state.referenceObjectUrls.get(file);
      return `<img src="${escapeHtml(url || '')}" alt="Референс ${index + 1}">`;
    }).join('')
    : '<span class="review-empty">Без референсов</span>';

  const brief = d.brief;

  // Если стиль «другое» — подставляем введённый текст
  const effectiveStyle =
    brief.preferred_style === 'other'
      ? (brief.otherStyle || 'Другое')
      : BRIEF_VALUES.preferred_style[brief.preferred_style] || '';

  const items = [
    { label: BRIEF_LABELS.experience_level, value: BRIEF_VALUES.experience_level[brief.experience_level] },
    { label: BRIEF_LABELS.preferred_style, value: effectiveStyle },
    { label: BRIEF_LABELS.inspiration_source, value: BRIEF_VALUES.inspiration_source[brief.inspiration_source] },
    { label: BRIEF_LABELS.importance, value: BRIEF_VALUES.importance[brief.importance] },
  ].filter((i) => i.value);

  const section = document.getElementById('review-brief-section');
  const container = document.getElementById('review-brief');

  if (items.length === 0) {
    section.classList.add('hidden');
    return;
  }

  section.classList.remove('hidden');
  container.innerHTML = items
    .map(
      (i) => `<div class="review-brief-item">
        <span class="label">${escapeHtml(i.label)}</span>
        <span class="value">${escapeHtml(i.value)}</span>
      </div>`
    )
    .join('');
}

function showEditOptions() {
  haptic('light');

  const d = state.draft || emptyDraft();
  const summaries = {
    1: d.description ? `Идея: ${d.description.slice(0, 48)}${d.description.length > 48 ? '…' : ''}` : 'Описание татуировки',
    2: d.references?.length ? `${d.references.length} ${d.references.length === 1 ? 'изображение' : 'изображения'}` : 'Без изображений',
    3: d.location || 'Место на теле',
    4: d.size || 'Размер татуировки',
    5: COLOR_LABELS[d.colorMode] || 'Цветовой вариант',
    6: URGENCY_LABELS[d.isUrgent] || 'Сроки и срочность',
    7: [
      BRIEF_VALUES.experience_level[d.brief?.experience_level],
      BRIEF_VALUES.preferred_style[d.brief?.preferred_style] || d.brief?.otherStyle,
      BRIEF_VALUES.inspiration_source[d.brief?.inspiration_source],
      BRIEF_VALUES.importance[d.brief?.importance],
    ].filter(Boolean).join(' · ') || 'Дополнительные пожелания',
    8: 'Посмотреть заявку целиком',
  };

  const overlay = document.createElement('div');
  overlay.className = 'edit-options-overlay';
  overlay.innerHTML = `
    <div class="edit-options-backdrop"></div>
    <div class="edit-options-panel">
       <h3>Что хочешь поправить?</h3>
       ${Array.from({ length: TOTAL_STEPS }, (_, i) => i + 1)
        .map(
          (i) => `<button class="edit-option-btn" data-step="${i}">
            <span class="step-num">${i}</span><span class="edit-option-copy"><b>${FORM_STEP_NAMES[i]}</b><small>${escapeHtml(summaries[i])}</small></span><span aria-hidden="true">›</span></button>`
        )
        .join('')}
    </div>`;

  document.body.appendChild(overlay);

  overlay.querySelector('.edit-options-backdrop').addEventListener('click', () => overlay.remove());
  overlay.querySelectorAll('.edit-option-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      state.currentStep = Number(btn.dataset.step);
      overlay.remove();
      renderStep();
      haptic('medium');
    });
  });
}

/* ===================================================
   SUBMIT
   =================================================== */

let submitting = false;

async function submitRequest() {
  if (submitting) return;
  const isResuming = Boolean(state.referenceUploadRequestId);
  if (!isResuming && !state.requestIdempotencyKey) {
    state.requestIdempotencyKey = window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
  }

  // Финальная проверка всех обязательных шагов
  const saved = state.currentStep;
  for (const step of [1, 3, 4, 5, 6]) {
    state.currentStep = step;
    if (!validateCurrentStep()) {
      state.currentStep = step;
      renderStep();
      return;
    }
  }
  state.currentStep = saved;

  submitting = true;
  haptic('heavy');

  const btn = document.getElementById('btn-submit');
  const original = btn.textContent;
  btn.textContent = 'Отправка…';
  btn.disabled = true;

  const brief = {
    experience_level: state.draft.brief.experience_level || null,
    preferred_style:
      state.draft.brief.preferred_style === 'other'
        ? (state.draft.brief.otherStyle || 'other')
        : (state.draft.brief.preferred_style || null),
    inspiration_source: state.draft.brief.inspiration_source || null,
    importance: state.draft.brief.importance || null,
  };

  Object.keys(brief).forEach((k) => {
    if (!brief[k]) delete brief[k];
  });

  const payload = {
    description: state.draft.description,
    location: state.draft.location,
    size: state.draft.size,
    color_mode: state.draft.colorMode,
    is_urgent: state.draft.isUrgent === 'yes',
    urgent_surcharge: state.draft.urgentSurcharge || null,
    brief_answers: Object.keys(brief).length ? brief : null,
  };

  let res;
  try {
    res = isResuming
      ? { ok: true, data: { id: state.referenceUploadRequestId } }
      : await apiPost('requests', payload, {
        'Idempotency-Key': state.requestIdempotencyKey,
      });
  } catch (error) {
    res = { ok: false, error: 'Сервер временно недоступен. Попробуй ещё раз.' };
  }

  if (!res.ok) {
    submitting = false;
    btn.textContent = original;
    btn.disabled = false;
    tgAlert('Не удалось отправить заявку: ' + (res.error || 'ошибка'));
    return;
  }

  // Создание заявки идемпотентно, а загрузка фото продолжается с места сбоя.
  // Повторный тап не создаёт новую заявку и не дублирует уже сохранённые фото.
  state.referenceUploadRequestId = res.data.id;
  const existingCount = Array.isArray(res.data.references) ? res.data.references.length : 0;
  state.uploadedReferenceCount = Math.max(state.uploadedReferenceCount, existingCount);

  for (let index = state.uploadedReferenceCount; index < state.referenceFiles.length; index += 1) {
    const file = state.referenceFiles[index];
    const form = new FormData();
    form.append('image', file);
    let upload;
    try {
      upload = await apiUpload(`requests/${res.data.id}/references`, form);
    } catch (error) {
      upload = { ok: false };
    }
    if (!upload.ok) {
      state.uploadedReferenceCount = index;
      submitting = false;
      btn.textContent = original;
      btn.disabled = false;
      tgAlert(`Заявка сохранена, но фото ${index + 1} не загрузилось. Нажми «Отправить заявку» ещё раз.`);
      return;
    }
    state.uploadedReferenceCount = index + 1;
  }

  submitting = false;
  btn.textContent = original;
  btn.disabled = false;
  launchConfetti();
  document.getElementById('success-request-id').textContent = `Заявка #${res.data.id} отправлена!`;
  showScreen('screen-success');
  state.draft = null;
  state.requestIdempotencyKey = null;
  state.referenceUploadRequestId = null;
  state.uploadedReferenceCount = 0;
}

/* ===================================================
   MY REQUESTS
   =================================================== */

async function openMyRequests() {
  if (!requireTelegramAuth()) return;
  haptic('light');
  showScreen('screen-my-requests');

  const loading = document.getElementById('requests-loading');
  const empty = document.getElementById('requests-empty');
  const list = document.getElementById('requests-list');

  loading.classList.remove('hidden');
  empty.classList.add('hidden');
  list.innerHTML = '';

  const res = await apiGet('requests');
  loading.classList.add('hidden');

  if (!res.ok) {
    toast(res.error || 'Не удалось загрузить заявки');
    return;
  }

  state.requests = Array.isArray(res.data) ? res.data : [];

  if (state.requests.length === 0) {
    empty.classList.remove('hidden');
    return;
  }

  renderRequestsList();
}

function renderRequestsList() {
  const container = document.getElementById('requests-list');
  container.innerHTML = '';

  state.requests.forEach((req, index) => {
    const status = STATUS_MAP[req.status] || STATUS_MAP.new;

    const card = document.createElement('div');
    card.className = 'request-card';
    card.style.animationDelay = `${index * 50}ms`;

    // Внутренний HTML только с экранированием — описание вводит пользователь
    card.innerHTML = `
      <div class="request-card-header">
        <span class="request-id">📋 Заявка #${req.id}</span>
        <span class="status-badge ${status.cssClass}">${status.icon} ${status.text}</span>
      </div>
      <div class="request-card-body">
        <div class="meta-item">💬 ${escapeHtml((req.description || 'Нет описания').slice(0, 60))}…</div>
        <div class="meta-item">📍 ${escapeHtml(req.location || '—')}</div>
      </div>
      <div class="request-card-actions">
        <button class="btn btn-secondary open-detail" data-id="${req.id}">👁 Открыть</button>
      </div>`;

    card.querySelector('.open-detail').addEventListener('click', () => openRequestDetail(req.id));
    container.appendChild(card);
  });
}

async function openRequestDetail(requestId) {
  haptic('light');

  let req = state.requests.find((r) => r.id === requestId);
  if (!req) {
    const res = await apiGet(`requests/${requestId}`);
    if (!res.ok) {
      toast(res.error || 'Заявка не найдена');
      return;
    }
    req = res.data;
  }

  const status = STATUS_MAP[req.status] || STATUS_MAP.new;

  document.getElementById('detail-title').textContent = `Заявка #${req.id}`;
  document.getElementById('detail-status').className = `status-badge ${status.cssClass}`;
  document.getElementById('detail-status').textContent = `${status.icon} ${status.text}`;

  document.getElementById('detail-location').textContent = req.location || '—';
  document.getElementById('detail-size').textContent = req.size || '—';
  document.getElementById('detail-color').textContent = COLOR_LABELS[req.color_mode] || '—';
  document.getElementById('detail-urgency').textContent = req.is_urgent ? '⚡ Да' : 'Нет';
  document.getElementById('detail-description').textContent = req.description || '—';

  const referencesSection = document.getElementById('detail-references-section');
  const referencesContainer = document.getElementById('detail-references');
  const references = Array.isArray(req.references) ? req.references : [];
  updateClientOnlyControls();
  if (references.length && referencesContainer) {
    referencesSection.classList.remove('hidden');
    referencesContainer.innerHTML = references.map((reference, index) => `
      <button class="detail-reference-button" type="button" onclick="App.openRequestReference(${req.id}, ${reference.id}, 'Референс ${index + 1}')">
        <span class="detail-reference-placeholder">Референс ${index + 1}</span>
      </button>`).join('');
    loadReferenceThumbs(req.id, references);
  } else if (referencesSection) {
    referencesSection.classList.add('hidden');
  }

  // Дата сеанса (появляется только когда назначена)
  const dateRow = document.getElementById('detail-date-row');
  const appt = req.appointment;
  if (appt && appt.slot_date) {
    document.getElementById('detail-date').textContent = formatDateRu(appt.slot_date);
    dateRow.style.display = '';
  } else {
    dateRow.style.display = 'none';
  }

  // Анкета
  const briefSection = document.getElementById('detail-brief-section');
  const brief = req.brief_answers || {};
  const entries = Object.entries(brief).filter(([, v]) => v);

  if (entries.length === 0) {
    briefSection.classList.add('hidden');
  } else {
    briefSection.classList.remove('hidden');
    document.getElementById('detail-brief').innerHTML = entries
      .map(([key, value]) => {
        let display = value;
        if (key === 'preferred_style' && !BRIEF_VALUES.preferred_style[value]) display = value;
        else if (BRIEF_VALUES[key]) display = BRIEF_VALUES[key][value] || value;
        return `<div class="detail-brief-item">
          <span class="label">${escapeHtml(BRIEF_LABELS[key] || key)}</span>
          <span class="value">${escapeHtml(String(display))}</span>
        </div>`;
      })
      .join('');
  }

  // Причина отклонения
  const rejSection = document.getElementById('detail-rejection-section');
  if (req.rejection_reason) {
    document.getElementById('detail-reason').textContent = req.rejection_reason;
    rejSection.classList.remove('hidden');
  } else {
    rejSection.classList.add('hidden');
  }

  openModal('modal-request-detail');
}

async function openRequestReference(requestId, referenceId, caption) {
  const response = await fetch(`${API_BASE}requests/${requestId}/references/${referenceId}/image`, {
    headers: authHeader(),
  });
  if (!response.ok) {
    toast('Не удалось открыть референс');
    return;
  }
  const url = URL.createObjectURL(await response.blob());
  state.referenceObjectUrls.set(`server:${requestId}:${referenceId}`, url);
  openImagePreview(url, caption);
}

async function loadReferenceThumbs(requestId, references) {
  const buttons = document.querySelectorAll('#detail-references .detail-reference-button');
  await Promise.all(references.map(async (reference, index) => {
    if (!reference.has_uploaded_image || !buttons[index]) return;
    const response = await fetch(`${API_BASE}requests/${requestId}/references/${reference.id}/image`, {
      headers: authHeader(),
    });
    if (!response.ok) return;
    const url = URL.createObjectURL(await response.blob());
    state.referenceObjectUrls.set(`server:${requestId}:${reference.id}`, url);
    const image = document.createElement('img');
    image.src = url;
    image.alt = `Референс ${index + 1}`;
    buttons[index].replaceChildren(image);
  }));
}

/* ===================================================
   CALENDAR
   =================================================== */

function openCalendar() {
  if (!requireTelegramAuth()) return;
  haptic('light');
  showScreen('screen-calendar');
  renderCalendar();
  loadCalendarSlots();
}

function prevMonth() {
  haptic('light');
  state.calendarMonth -= 1;
  if (state.calendarMonth < 0) {
    state.calendarMonth = 11;
    state.calendarYear -= 1;
  }
  renderCalendar();
  loadCalendarSlots();
}

function nextMonth() {
  haptic('light');
  state.calendarMonth += 1;
  if (state.calendarMonth > 11) {
    state.calendarMonth = 0;
    state.calendarYear += 1;
  }
  renderCalendar();
  loadCalendarSlots();
}

function isoDate(y, m, d) {
  return `${y}-${String(m + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
}

function renderCalendar() {
  const year = state.calendarYear;
  const month = state.calendarMonth;

  const months = [
    'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
    'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь',
  ];

  document.getElementById('calendar-month-year').textContent = `${months[month]} ${year}`;

  const grid = document.getElementById('calendar-grid');
  grid.innerHTML = '';

  const firstDay = new Date(year, month, 1);
  let startDay = firstDay.getDay() - 1;
  if (startDay < 0) startDay = 6;

  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const today = new Date();
  const todayStr = isoDate(today.getFullYear(), today.getMonth(), today.getDate());

  for (let i = 0; i < startDay; i++) {
    const cell = document.createElement('div');
    cell.className = 'calendar-day empty';
    grid.appendChild(cell);
  }

  for (let day = 1; day <= daysInMonth; day++) {
    const cell = document.createElement('div');
    cell.className = 'calendar-day';
    cell.textContent = day;

    const dateStr = isoDate(year, month, day);
    cell.dataset.date = dateStr;
    if (dateStr === todayStr) cell.classList.add('today');

    const slot = state.calendarSlots[dateStr];
    if (slot?.is_booked) {
      cell.classList.add('busy');
    } else if (slot && !slot.is_blocked) {
      cell.classList.add('free');
    } else {
      cell.classList.add('closed');
    }
    if ([0, 6].includes(new Date(year, month, day).getDay())) {
      cell.classList.add('weekend');
    }

    // Мастер может открыть/закрыть день прямо в календаре.
    if (state.me?.is_admin) {
      cell.classList.add('clickable');
      cell.addEventListener('click', () => toggleCalendarDay(dateStr));
    } else {
      cell.addEventListener('click', () => explainCalendarDay(dateStr));
    }

    grid.appendChild(cell);
  }

  // Подсказка видна только мастеру
  const hint = document.getElementById('calendar-master-hint');
  if (hint) hint.classList.toggle('hidden', !state.me?.is_admin);

  const hasSlots = Object.keys(state.calendarSlots).length > 0;
  document.getElementById('calendar-empty').classList.toggle('hidden', hasSlots);
}

async function toggleCalendarDay(dateStr) {
  const slot = state.calendarSlots[dateStr];

  // Занятый день трогать нельзя: там реальная запись клиента.
  if (slot?.is_booked) {
    tgAlert('На этот день уже есть запись — сначала отмени её в заявке.');
    return;
  }

  haptic('medium');

  const res = await apiPost(`slots/${dateStr}/toggle`, {});
  if (!res.ok) {
    tgAlert(res.error || 'Не удалось изменить день');
    return;
  }

  toast(res.data?.is_blocked ? 'День закрыт 🔒' : 'День открыт 🔓');
  await loadCalendarSlots();
}

/** Клиент нажал на день: честно объясняем, как записаться. */
function explainCalendarDay(dateStr) {
  const slot = state.calendarSlots[dateStr];

  if (slot?.is_booked) {
    haptic('light');
    toast('Этот день уже занят. Выбери другой ✨');
    return;
  }

  if (slot?.is_blocked) {
    haptic('light');
    toast('Мастер закрыл этот день. Выбери другой ✨');
    return;
  }

  haptic('light');
  // Свободный день: запись идёт через заявку, а не по клику.
  toast('Чтобы записаться — оставь заявку, мастер предложит время 💬');
}

async function loadCalendarSlots() {
  const from = isoDate(state.calendarYear, state.calendarMonth, 1);
  const lastDay = new Date(state.calendarYear, state.calendarMonth + 1, 0).getDate();
  const to = isoDate(state.calendarYear, state.calendarMonth, lastDay);

  const res = await apiGet(`slots/availability?start_date=${from}&end_date=${to}`);

  state.calendarSlots = {};
  if (res.ok && res.data && Array.isArray(res.data.days)) {
    res.data.days.forEach((d) => {
      state.calendarSlots[d.date] = d;
    });
  }
  renderCalendar();
}

/* ===================================================
   MASTER CABINET
   =================================================== */

async function openMasterCabinet() {
  if (!requireTelegramAuth()) return;
  haptic('light');

  if (!state.me?.is_admin) {
    tgAlert('Кабинет доступен только мастеру.');
    return;
  }

  showScreen('screen-master');
  switchMasterTab('requests');

  const loading = document.getElementById('master-loading');
  const empty = document.getElementById('master-empty');
  const list = document.getElementById('master-list');
  const stats = document.getElementById('master-stats');

  loading.classList.remove('hidden');
  empty.classList.add('hidden');
  list.innerHTML = '';
  stats.innerHTML = '';

  const [dash, reqs, portfolio] = await Promise.all([
    apiGet('admin/dashboard'),
    apiGet('requests?limit=50'),
    apiGet('admin/portfolio'),
  ]);

  loading.classList.add('hidden');

  if (dash.ok && dash.data) {
    const d = dash.data;
    stats.innerHTML = `
      <h3>Сводка</h3>
      <div class="detail-item"><span class="detail-label">⏳ Новые</span><span class="detail-value">${d.new_count}</span></div>
      <div class="detail-item"><span class="detail-label">✅ Приняты</span><span class="detail-value">${d.accepted_count}</span></div>
      <div class="detail-item"><span class="detail-label">🖌 В работе</span><span class="detail-value">${d.in_progress_count}</span></div>
      <div class="detail-item"><span class="detail-label">📅 Записаны</span><span class="detail-value">${d.scheduled_count}</span></div>
      <div class="detail-item"><span class="detail-label">✨ Завершены</span><span class="detail-value">${d.completed_count}</span></div>`;
  }

  if (!reqs.ok) {
    toast(reqs.error || 'Не удалось загрузить заявки');
    return;
  }

  state.masterRequests = Array.isArray(reqs.data) ? reqs.data : [];

  if (portfolio.ok && Array.isArray(portfolio.data)) {
    state.adminPortfolio = portfolio.data;
    renderAdminPortfolio();
  }

  if (state.masterRequests.length === 0) {
    empty.classList.remove('hidden');
    return;
  }

  renderMasterList();
}

function switchMasterTab(tab) {
  document.querySelectorAll('.master-tab').forEach((button) => {
    button.classList.toggle('active', button.dataset.masterTab === tab);
  });
  document.getElementById('master-requests-panel')?.classList.toggle('hidden', tab !== 'requests');
  document.getElementById('master-portfolio-panel')?.classList.toggle('hidden', tab !== 'portfolio');
}

function resetPortfolioForm() {
  state.editingPortfolioId = null;
  document.getElementById('portfolio-form-title').textContent = 'Добавить работу';
  document.getElementById('portfolio-title').value = '';
  document.getElementById('portfolio-place').value = '';
  document.getElementById('portfolio-tags').value = '';
  document.getElementById('portfolio-image-url').value = '';
  document.getElementById('portfolio-sort').value = '0';
  document.getElementById('portfolio-published').checked = true;
  document.getElementById('portfolio-image').value = '';
  renderFolderSuggestions();
  document.getElementById('portfolio-form').classList.add('hidden');
}

function editPortfolioItem(item) {
  state.editingPortfolioId = item.id;
  document.getElementById('portfolio-form-title').textContent = 'Изменить работу';
  document.getElementById('portfolio-title').value = item.title || '';
  document.getElementById('portfolio-place').value = item.place || '';
  document.getElementById('portfolio-tags').value = (item.tags || []).join(', ');
  document.getElementById('portfolio-image-url').value = item.image_url || '';
  document.getElementById('portfolio-sort').value = item.sort_order ?? 0;
  document.getElementById('portfolio-published').checked = Boolean(item.is_published);
  document.getElementById('portfolio-image').value = '';
  document.getElementById('portfolio-form').classList.remove('hidden');
  renderFolderSuggestions();
}

function renderFolderSuggestions() {
  const container = document.getElementById('portfolio-folder-suggestions');
  const input = document.getElementById('portfolio-place');
  if (!container || !input) return;
  const folders = [...new Set(state.adminPortfolio.map((item) => item.place).filter(Boolean))];
  container.innerHTML = folders.map((folder) => `<button type="button" class="folder-chip" data-folder="${escapeHtml(folder)}">${escapeHtml(folder)}</button>`).join('');
  container.querySelectorAll('[data-folder]').forEach((button) => button.addEventListener('click', () => {
    input.value = button.dataset.folder || '';
  }));
}

async function savePortfolioItem(event) {
  event.preventDefault();
  const payload = {
    title: document.getElementById('portfolio-title').value.trim(),
    place: document.getElementById('portfolio-place').value.trim(),
    tags: document.getElementById('portfolio-tags').value.split(',').map((tag) => tag.trim()).filter(Boolean),
    image_url: document.getElementById('portfolio-image-url').value.trim() || null,
    sort_order: Number(document.getElementById('portfolio-sort').value || 0),
    is_published: document.getElementById('portfolio-published').checked,
  };
  const editing = state.editingPortfolioId;
  const res = editing
    ? await apiFetch(`admin/portfolio/${editing}`, { method: 'PATCH', body: JSON.stringify(payload) })
    : await apiPost('admin/portfolio', payload);
  if (!res.ok) {
    tgAlert(res.error || 'Не удалось сохранить работу');
    return;
  }
  const file = document.getElementById('portfolio-image').files[0];
  if (file) {
    const form = new FormData();
    form.append('image', file);
    const upload = await apiUpload(`admin/portfolio/${res.data.id}/image`, form);
    if (!upload.ok) {
      tgAlert(upload.error || 'Работа сохранена, но изображение не загрузилось');
    }
  }
  toast(editing ? 'Работа обновлена' : 'Работа добавлена');
  document.getElementById('portfolio-form').classList.add('hidden');
  await loadAdminPortfolio();
  await loadPortfolio(true);
  renderPortfolio();
}

async function loadAdminPortfolio() {
  const res = await apiGet('admin/portfolio');
  if (!res.ok) {
    tgAlert(res.error || 'Не удалось загрузить портфолио');
    return;
  }
  state.adminPortfolio = Array.isArray(res.data) ? res.data : [];
  renderAdminPortfolio();
}

function renderAdminPortfolio() {
  const list = document.getElementById('admin-portfolio-list');
  if (!list) return;
  list.innerHTML = state.adminPortfolio.map((item) => `
    <div class="admin-portfolio-row">
      <img src="${escapeHtml(portfolioImageUrl(item))}" alt="">
      <div class="admin-portfolio-copy"><b>${escapeHtml(item.title)}</b><span>${escapeHtml(item.place)} · ${escapeHtml((item.tags || []).join(', '))}</span><small>${item.is_published ? 'Опубликована' : 'Скрыта'}${item.has_uploaded_image ? ' · файл в БД' : ''}</small></div>
      <div class="admin-portfolio-actions"><button class="btn btn-secondary" data-portfolio-edit="${item.id}">Изменить</button><button class="btn btn-secondary" data-portfolio-toggle="${item.id}">${item.is_published ? 'Скрыть' : 'Опубликовать'}</button><button class="btn btn-danger" data-portfolio-delete="${item.id}">Удалить</button></div>
    </div>`).join('');
  list.querySelectorAll('[data-portfolio-edit]').forEach((button) => button.addEventListener('click', () => {
    const item = state.adminPortfolio.find((entry) => entry.id === Number(button.dataset.portfolioEdit));
    if (item) editPortfolioItem(item);
  }));
  list.querySelectorAll('[data-portfolio-toggle]').forEach((button) => button.addEventListener('click', () => togglePortfolioItem(Number(button.dataset.portfolioToggle))));
  list.querySelectorAll('[data-portfolio-delete]').forEach((button) => button.addEventListener('click', () => deletePortfolioItem(Number(button.dataset.portfolioDelete))));
  renderFolderSuggestions();
}

async function togglePortfolioItem(id) {
  const item = state.adminPortfolio.find((entry) => entry.id === id);
  if (!item) return;
  const res = await apiFetch(`admin/portfolio/${id}`, { method: 'PATCH', body: JSON.stringify({ is_published: !item.is_published }) });
  if (!res.ok) { tgAlert(res.error || 'Не удалось изменить публикацию'); return; }
  await loadAdminPortfolio();
  await loadPortfolio(true);
  renderPortfolio();
}

async function deletePortfolioItem(id) {
  if (!confirm('Удалить эту работу?')) return;
  const res = await apiFetch(`admin/portfolio/${id}`, { method: 'DELETE' });
  if (!res.ok) { tgAlert(res.error || 'Не удалось удалить работу'); return; }
  toast('Работа удалена');
  await loadAdminPortfolio();
  await loadPortfolio(true);
  renderPortfolio();
}

/** Строка «кто клиент» для карточки мастера. */
function masterClientLine(req) {
  const name = req.client_name || 'Клиент';
  const username = req.client_username ? ` · @${req.client_username}` : '';
  return `👤 ${name}${username}`;
}

function renderMasterList() {
  const container = document.getElementById('master-list');
  container.innerHTML = '';

  state.masterRequests.forEach((req, index) => {
    const status = STATUS_MAP[req.status] || STATUS_MAP.new;
    const queueRank = Number(req.queue_rank);
    const queueLabel = Number.isInteger(queueRank) && queueRank > 0
      ? `${['Первый', 'Второй', 'Третий', 'Четвёртый', 'Пятый'][queueRank - 1] || `${queueRank}-й`} в очереди`
      : null;

    const card = document.createElement('div');
    card.className = 'request-card';
    card.style.animationDelay = `${index * 40}ms`;

    card.innerHTML = `
      <div class="request-card-header">
        <span class="request-id">${queueLabel ? `${queueLabel} · ` : `Заявка #${req.id} · `}${escapeHtml(req.location || '')}</span>
        <span class="status-badge ${status.cssClass}">${status.icon} ${status.text}</span>
      </div>
      <div class="request-card-body">
        <div class="meta-item">${escapeHtml(masterClientLine(req))}</div>
        <div class="meta-item">💬 ${escapeHtml((req.description || '').slice(0, 80))}…</div>
        <div class="meta-item reference-summary">📎 Референсы: ${req.references?.length || 0}</div>
        ${req.references?.length ? `<div class="master-reference-strip" aria-label="Референсы заявки">
          ${req.references.map((reference, refIndex) => `<button type="button" class="master-reference-thumb" data-request-id="${req.id}" data-reference-id="${reference.id}" aria-label="Открыть референс ${refIndex + 1}"><span>Фото ${refIndex + 1}</span></button>`).join('')}
        </div>` : ''}
      </div>
      <div class="request-card-actions" id="actions-${req.id}"></div>`;

    const actions = card.querySelector(`#actions-${req.id}`);
    buildMasterActions(req, actions);

    card.querySelectorAll('.master-reference-thumb').forEach((thumb) => {
      const referenceId = Number(thumb.dataset.referenceId);
      thumb.addEventListener('click', () => openRequestReference(req.id, referenceId, `Референс ${referenceId}`));
      loadReferenceThumb(req.id, referenceId, thumb);
    });

    container.appendChild(card);
  });
}

async function loadReferenceThumb(requestId, referenceId, button) {
  const response = await fetch(`${API_BASE}requests/${requestId}/references/${referenceId}/image`, {
    headers: authHeader(),
  });
  if (!response.ok) return;
  const url = URL.createObjectURL(await response.blob());
  state.referenceObjectUrls.set(`server:${requestId}:${referenceId}`, url);
  const image = document.createElement('img');
  image.src = url;
  image.alt = 'Референс';
  button.replaceChildren(image);
}

function buildMasterActions(req, container) {
  const btn = (label, cls, fn) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = `btn ${cls}`;
    b.textContent = label;
    b.addEventListener('click', async () => {
      if (b.disabled) return;
      b.disabled = true;
      b.classList.add('is-loading');
      try {
        await fn();
      } finally {
        b.disabled = false;
        b.classList.remove('is-loading');
      }
    });
    container.appendChild(b);
  };

  const act = async (endpoint, body, confirmText) => {
    if (confirmText && !confirm(confirmText)) return;
    haptic('medium');
    const res = await apiPost(endpoint, body);
    if (!res.ok) {
      tgAlert(res.error || 'Не получилось');
      return;
    }
    toast('Готово ✨');
    await openMasterCabinet();
  };

  if (req.status === 'new') {
    btn('✅ Принять', 'btn-accent', () =>
      act(`requests/${req.id}/accept`, {}, 'Принять эту заявку?'));
    btn('❌ Отклонить', 'btn-secondary', () =>
      act(`requests/${req.id}/reject`, { reason: null }, 'Отклонить заявку?'));
  } else if (req.status === 'accepted') {
    btn('🖌 В работу', 'btn-accent', () =>
      act(`requests/${req.id}/proceed`, {}, 'Взять в работу?'));
    btn('❌ Отклонить', 'btn-secondary', () =>
      act(`requests/${req.id}/reject`, { reason: null }, 'Отклонить заявку?'));
  } else if (req.status === 'in_progress') {
    btn('📅 Назначить дату', 'btn-accent', () => promptSchedule(req.id));
  } else if (req.status === 'scheduled') {
    btn('✨ Завершить', 'btn-accent', () =>
      act(`requests/${req.id}/complete`, {}, 'Сеанс проведён?'));
    btn('🚫 Отменить', 'btn-secondary', () =>
      act(`requests/${req.id}/cancel`, {}, 'Отменить запись?'));
  } else if (req.status === 'rejected') {
    btn('↩️ Вернуть', 'btn-secondary', () =>
      act(`requests/${req.id}/reactivate`, {}, 'Вернуть заявку в очередь?'));
  }

  btn('👁 Открыть', 'btn-secondary', () => openRequestDetail(req.id));
}

async function promptSchedule(requestId) {
  // Дата выбирается в самом приложении: встроенный prompt() в Telegram
  // WebView на части устройств заблокирован, а руками набранную дату
  // легко перепутать. Свой календарь работает всегда и без опечаток.
  state.pendingScheduleId = requestId;

  const input = document.getElementById('schedule-date-input');
  const errEl = document.getElementById('schedule-error');

  if (input) {
    const now = new Date();
    const today = isoDate(now.getFullYear(), now.getMonth(), now.getDate());
    input.min = today;
    input.value = '';
  }
  if (errEl) errEl.textContent = '';

  openModal('modal-schedule');
}

async function confirmScheduleDate() {
  const input = document.getElementById('schedule-date-input');
  const errEl = document.getElementById('schedule-error');
  const value = (input?.value || '').trim();

  const showError = (msg) => {
    if (errEl) errEl.textContent = msg;
    tgAlert(msg);
  };

  if (!value) {
    showError('Выбери дату');
    return;
  }

  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    showError('Неверный формат даты');
    return;
  }

  const requestId = state.pendingScheduleId;
  if (!requestId) {
    closeModal('modal-schedule');
    return;
  }

  haptic('medium');
  const res = await apiPost(`requests/${requestId}/schedule`, { slot_date: value });

  if (!res.ok) {
    showError(res.error || 'Не получилось назначить дату');
    return;
  }

  state.pendingScheduleId = null;
  closeModal('modal-schedule');
  toast('Дата назначена 📅');
  openMasterCabinet();
}

/* ===================================================
   MODALS / CONTACT
   =================================================== */

function openModal(id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.remove('hidden');
  document.body.style.overflow = 'hidden';
}

function closeModal(id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.add('hidden');
  document.body.style.overflow = '';
}

function openMasterContact() {
  if (state.me?.is_admin) {
    toast('В мастерском режиме контакт с собой не нужен');
    return;
  }
  if (!requireTelegramAuth()) return;
  haptic('light');
  if (tg?.openTelegramLink) {
    tg.openTelegramLink(MASTER_TELEGRAM);
  } else {
    window.open(MASTER_TELEGRAM, '_blank');
  }
}

/* ===================================================
   UTILS
   =================================================== */

function escapeHtml(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function formatDateRu(iso) {
  // 'YYYY-MM-DD' -> 'DD.MM.YYYY'
  if (!iso) return '';
  const parts = String(iso).slice(0, 10).split('-');
  if (parts.length !== 3) return iso;
  return `${parts[2]}.${parts[1]}.${parts[0]}`;
}

function launchConfetti() {
  const canvas = document.getElementById('confetti-canvas');
  if (!canvas) return;

  canvas.classList.remove('hidden');
  canvas.width = window.innerWidth;
  canvas.height = window.innerHeight;

  const ctx = canvas.getContext('2d');
  const colors = ['#D4A24E', '#F5E6C8', '#4CAF50', '#E53935', '#FF9800', '#2196F3', '#FFFFFF'];
  const particles = [];

  for (let i = 0; i < 80; i++) {
    particles.push({
      x: Math.random() * canvas.width,
      y: -20 - Math.random() * 100,
      w: 4 + Math.random() * 6,
      h: 4 + Math.random() * 6,
      color: colors[Math.floor(Math.random() * colors.length)],
      vy: 2 + Math.random() * 3,
      vx: -1.5 + Math.random() * 3,
      rot: Math.random() * Math.PI,
      vr: -0.1 + Math.random() * 0.2,
    });
  }

  const start = performance.now();

  function frame(now) {
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    particles.forEach((p) => {
      p.x += p.vx;
      p.y += p.vy;
      p.rot += p.vr;

      ctx.save();
      ctx.translate(p.x, p.y);
      ctx.rotate(p.rot);
      ctx.fillStyle = p.color;
      ctx.fillRect(-p.w / 2, -p.h / 2, p.w, p.h);
      ctx.restore();
    });

    if (now - start < 3500) {
      requestAnimationFrame(frame);
    } else {
      canvas.classList.add('hidden');
      ctx.clearRect(0, 0, canvas.width, canvas.height);
    }
  }

  requestAnimationFrame(frame);
}

/* ===================================================
   PUBLIC API — вызывается из onclick в index.html
   =================================================== */

const App = {
  goHome,
  retryInit,
  startNewRequest,
  navNewRequest,
  hasDraftContent,
  cancelRequestForm,
  nextStep,
  prevStep,
  showEditOptions,
  addReferenceFiles,
  removeReference,
  submitRequest,
  openMyRequests,
  openRequestDetail,
  openCalendar,
  prevMonth,
  nextMonth,
  toggleCalendarDay,
  explainCalendarDay,
  applyUrgentPrice,
  openMasterCabinet,
  resetPortfolioForm,
  savePortfolioItem,
  openLastRequest,
  openMasterContact,
  openModal,
  closeModal,
  confirmScheduleDate,
  openPortfolio,
  openImagePreview,
  filterPortfolio,
  switchMasterTab,
  playIntro,
  closeIntro,
};

window.App = App;

/* ===================================================
   BOOT
   =================================================== */

document.addEventListener('DOMContentLoaded', () => {
  initFormControls();
  renderPortfolio();
  try {
    if (!sessionStorage.getItem('tatu.intro.seen')) setTimeout(playIntro, 180);
  } catch (e) { /* intro remains available from the quiet home link */ }
  init();
});

document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'hidden') {
    state.lastVisibleAt = Date.now();
    return;
  }

  if (Date.now() - state.lastVisibleAt >= RESUME_REFRESH_AFTER_MS) {
    refreshSessionOnResume();
  }
});

window.addEventListener('pageshow', (event) => {
  if (event.persisted || Date.now() - state.lastVisibleAt >= RESUME_REFRESH_AFTER_MS) {
    refreshSessionOnResume();
  }
});
