/* ===================================================
   TATU BOT — Telegram Mini App (app.js)
   Production-ready vanilla JS, no dependencies.
   =================================================== */

/* ===================================================
   CONFIG
   =================================================== */

/*
 * API_BASE — относительный путь к API.
 * Работает и на Render, и локально, и при открытии в браузере.
 */
const API_BASE = '/api/v1/';

const STATUS_MAP = {
  new:        { text: 'В очереди',   icon: '⏳', cssClass: 'new' },
  accepted:   { text: 'Принята',     icon: '✅', cssClass: 'accepted' },
  in_progress:{ text: 'Создаётся',  icon: '🖌',  cssClass: 'in_progress' },
  scheduled:  { text: 'Записана',    icon: '📅', cssClass: 'scheduled' },
  completed:  { text: 'Завершена',   icon: '✨', cssClass: 'completed' },
  rejected:   { text: 'Отклонена',   icon: '❌', cssClass: 'rejected' },
};

const BRIEF_LABELS = {
  experience_level: 'Опыт',
  preferred_style: 'Стиль',
  inspiration_source: 'Вдохновение',
  importance: 'Важнее всего',
};

const COLOR_LABELS = { bw: 'Чёрно-белая', color: 'Цветная' };
const URGENCY_LABELS = { yes: 'Да, срочно', no: 'Нет, обычная очередь' };

/* ===================================================
   STATE — FSM data
   =================================================== */
const state = {
  user: null,           // TG user data
  settings: null,       // bot settings
  requests: [],         // user requests list
  currentStep: 1,       // 1–8
  draft: {
    description: '',
    references: [],          // {fileId, dataUrl}
    location: '',
    size: '',
    colorMode: '',           // 'bw' | 'color'
    isUrgent: '',            // 'yes' | 'no' | ''
    urgentSurcharge: 0,
    brief: {
      experience_level: '',
      preferred_style: '',
      otherStyle: '',
      inspiration_source: '',
      importance: '',
    },
  },
  calendarYear: new Date().getFullYear(),
  calendarMonth: new Date().getMonth(), // 0-indexed
  calendarSlots: {}, // { 'YYYY-MM-DD': { is_blocked, ... } }
  editingRequestId: null,
};

/* ===================================================
   TELEGRAM WEBAPP HELPERS
   =================================================== */
const tg = window.Telegram?.WebApp;

function initTelegram() {
  if (!tg) {
    console.warn('Telegram WebApp not available');
    return;
  }
  tg.ready();
  tg.expand();

  // Apply telegram theme if available
  if (tg.themeParams.bg_color) {
    document.body.style.backgroundColor = tg.themeParams.bg_color || '#F8F8FA';
  }

  // Parse user data
  const initData = tg.initDataUnsafe || {};
  const user = initData.user || initData.query_id;

  if (user) {
    state.user = {
      id: user.id,
      tg_id: user.id,
      first_name: user.first_name || 'Клиент',
      last_name: user.last_name || '',
      username: user.username || '',
      display_name: [user.first_name, user.last_name].filter(Boolean).join(' ') || 'Клиент',
    };
  }

  // Save to localStorage as fallback
  if (state.user) {
    localStorage.setItem('tatu_user', JSON.stringify(state.user));
  }
}

function gettgId() {
  return state.user?.tg_id || localStorage.getItem('tatu_user') ? JSON.parse(localStorage.getItem('tatu_user')).tg_id : null;
}

function haptic(type) {
  if (tg?.HapticFeedback) {
    try {
      const impactMap = {
        light: 'lightImpact',
        medium: 'mediumImpact',
        heavy: 'heavyImpact',
      };
      tg.HapticFeedback.impactOccurred(impactMap[type] || 'light');
    } catch (e) {
      // Fallback
    }
  }
}

/* ===================================================
   API CLIENT
   =================================================== */
async function apiGet(endpoint) {
  try {
    const res = await fetch(API_BASE + endpoint, {
      headers: { 'Content-Type': 'application/json' },
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (err) {
    console.error('API GET error:', err);
    return null;
  }
}

async function apiPost(endpoint, body) {
  try {
    const res = await fetch(API_BASE + endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (err) {
    console.error('API POST error:', err);
    return null;
  }
}

async function apiPatch(endpoint, body) {
  try {
    const res = await fetch(API_BASE + endpoint, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (err) {
    console.error('API PATCH error:', err);
    return null;
  }
}

/* ===================================================
   NAVIGATION — Screen routing
   =================================================== */
function showScreen(screenId) {
  // Hide all screens
  document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
  // Show target
  const target = document.getElementById('screen-' + screenId);
  if (target) {
    target.classList.add('active');
    // Scroll to top
    window.scrollTo(0, 0);
  }

  // Show/hide bottom nav
  const hideNavScreens = ['screen-request-form', 'screen-loading'];
  const bottomNav = document.getElementById('bottom-nav');
  if (hideNavScreens.includes('screen-' + screenId)) {
    bottomNav?.classList.add('hidden');
  } else {
    bottomNav?.classList.remove('hidden');
  }
}

/* ===================================================
   HOME SCREEN
   =================================================== */
async function initHome() {
  showScreen('home');
  updateBottomNav('screen-home');

  // Greeting
  const name = state.user?.display_name || state.user?.first_name || 'Клиент';
  document.getElementById('greeting-text').textContent = `✨ Привет, ${name}!`;
  document.getElementById('home-subtitle').textContent =
    'Добро пожаловать в мой личный бот. Здесь ты можешь оставить заявку на эскиз.';

  // Fetch settings
  if (!state.settings) {
    state.settings = await apiGet('settings');
  }

  // Fetch user requests to show last one
  const userId = gettgId();
  if (userId) {
    const reqs = await apiGet(`requests?user_id=${userId}&limit=1`);
    if (reqs && reqs.length > 0) {
      const last = reqs[0];
      showLastRequest(last);
    }
  }
}

function showLastRequest(req) {
  const card = document.getElementById('home-last-request');
  const statusEl = document.getElementById('last-request-status');
  const infoEl = document.getElementById('last-request-info');

  const status = STATUS_MAP[req.status] || STATUS_MAP.new;
  statusEl.className = `status-badge ${status.cssClass}`;
  statusEl.textContent = `${status.icon} ${status.text}`;

  infoEl.textContent = `#${req.id} — ${req.description?.substring(0, 40) || 'Заявка'}...`;

  card.classList.remove('hidden');
}

/* ===================================================
   REQUEST FORM — FSM (8 steps)
   =================================================== */
function startNewRequest() {
  haptic('light');
  resetDraft();
  state.currentStep = 1;
  renderStep();
  showScreen('request-form');
  updateBottomNav(null);
}

function resetDraft() {
  state.draft = {
    description: '',
    references: [],
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
  };
  state.currentStep = 1;

  // Clear form fields
  document.getElementById('field-description').value = '';
  document.getElementById('desc-count').textContent = '0';
  document.getElementById('field-location').value = '';
  document.getElementById('field-size').value = '';
  document.getElementById('references-preview').innerHTML = '';
  document.getElementById('ref-counter').textContent = 'Принято: 0 из 5';

  // Clear selections
  document.querySelectorAll('.color-option, .urgency-option, .chip, .brief-option').forEach(el => {
    el.classList.remove('selected');
  });

  // Hide brief questions
  for (let i = 1; i <= 4; i++) {
    const el = document.getElementById(`brief-q${i}`);
    if (el) el.classList.add('hidden');
  }
  document.getElementById('brief-other-field').classList.add('hidden');
}

function renderStep() {
  const step = state.currentStep;
  const totalSteps = 8;

  // Update progress
  document.getElementById('step-label').textContent = `Шаг ${step} из ${totalSteps}`;
  document.getElementById('progress-fill').style.width = `${(step / totalSteps) * 100}%`;

  // Show/hide steps
  document.querySelectorAll('.form-step').forEach(s => s.classList.remove('active'));
  const stepEl = document.getElementById(`step-${step}`);
  if (stepEl) stepEl.classList.add('active');

  // Nav buttons
  const btnBack = document.getElementById('btn-back');
  const btnNext = document.getElementById('btn-next');

  if (step === 1) {
    btnBack.disabled = true;
    btnBack.style.opacity = '0.4';
  } else {
    btnBack.disabled = false;
    btnBack.style.opacity = '1';
  }

  // Update next button text
  if (step === 8) {
    btnNext.textContent = '✉️ Отправить заявку';
    btnNext.classList.add('btn-accent');
  } else if (step === 7) {
    btnNext.textContent = 'Далее →';
  } else {
    btnNext.textContent = 'Далее →';
  }

  // Load urgent price
  const urgentLabel = document.getElementById('urgent-price-label');
  const surchargeEl = document.getElementById('surcharge-amount');
  if (state.settings?.urgent_price) {
    urgentLabel.textContent = `${state.settings.urgent_price} ₽`;
    surchargeEl.textContent = `${state.settings.urgent_price} ₽`;
  }
}

async function nextStep() {
  haptic('light');

  // Validate current step before advancing
  if (!validateCurrentStep()) return;

  // Save draft between steps
  saveDraftToStorage();

  if (state.currentStep === 7) {
    // Step 7 is brief — auto-advance through brief questions
    await renderBriefAutoAdvance();
    return;
  }

  state.currentStep = Math.min(state.currentStep + 1, 8);
  renderStep();
}

function prevStep() {
  haptic('light');

  if (state.currentStep <= 1) return;

  // If we're in brief questions, go back to step 7
  if (state.currentStep === 7) {
    state.currentStep = 6;
    renderStep();
    return;
  }

  state.currentStep--;
  renderStep();
}

function validateCurrentStep() {
  const step = state.currentStep;
  let valid = true;

  // Hide all errors first
  document.querySelectorAll('.error-message').forEach(el => el.classList.add('hidden'));

  switch (step) {
    case 1: {
      const desc = document.getElementById('field-description').value.trim();
      if (desc.length < 10) {
        showError('description', 'Расскажи чуть подробнее, это поможет мастеру понять твою идею');
        shakeField('field-description');
        valid = false;
      } else {
        state.draft.description = desc;
      }
      break;
    }
    case 2: {
      // References are optional but recommended
      break;
    }
    case 3: {
      const loc = document.getElementById('field-location').value.trim();
      if (loc.length < 3) {
        showError('location', 'Укажи место — минимум 3 символа');
        shakeField('field-location');
        valid = false;
      } else {
        state.draft.location = loc;
      }
      break;
    }
    case 4: {
      const size = document.getElementById('field-size').value.trim();
      if (!size) {
        showError('size', 'Укажи размер татуировки');
        shakeField('field-size');
        valid = false;
      } else {
        state.draft.size = size;
      }
      break;
    }
    case 5: {
      if (!state.draft.colorMode) {
        showError('color', 'Выбери цветовой вариант');
        valid = false;
      }
      break;
    }
    case 6: {
      if (!state.draft.isUrgent) {
        showError('urgency', 'Выбери вариант срочности');
        valid = false;
      } else {
        state.draft.urgentSurcharge = state.draft.isUrgent === 'yes' && state.settings?.urgent_price
          ? Number(state.settings.urgent_price) : 0;
        const surchargeEl = document.getElementById('urgent-surcharge');
        if (state.draft.isUrgent === 'yes') {
          surchargeEl.classList.remove('hidden');
        } else {
          surchargeEl.classList.add('hidden');
        }
      }
      break;
    }
    case 7: {
      // Brief — any combination is acceptable, skipping validation
      break;
    }
    case 8: {
      // Review step — no validation needed
      renderReviewCard();
      break;
    }
  }

  return valid;
}

function showError(fieldId, message) {
  const errorEl = document.getElementById(`error-${fieldId}`);
  if (errorEl) {
    errorEl.textContent = message;
    errorEl.classList.remove('hidden');
  }
}

function shakeField(fieldId) {
  const field = document.getElementById(fieldId);
  if (field) {
    field.classList.add('shake');
    setTimeout(() => field.classList.remove('shake'), 500);
  }
}

/* ===================================================
   BRIEF — Auto-advance through 4 questions
   =================================================== */
async function renderBriefAutoAdvance() {
  const brief = state.draft.brief;
  const questions = ['brief-q1', 'brief-q2', 'brief-q3', 'brief-q4'];

  // Show first question
  let qIndex = 0;

  function showQuestion(idx) {
    // Hide all questions
    questions.forEach(q => {
      const el = document.getElementById(q);
      if (el) el.classList.add('hidden');
    });

    if (idx >= questions.length) {
      // All questions answered, move to step 8
      state.currentStep = 8;
      renderStep();
      return;
    }

    const qEl = document.getElementById(questions[idx]);
    if (qEl) qEl.classList.remove('hidden');
  }

  showQuestion(0);

  // Attach click handlers dynamically
  const attachHandlers = () => {
    questions.forEach((qId, idx) => {
      const qEl = document.getElementById(qId);
      if (!qEl) return;

      const options = qEl.querySelectorAll('.brief-option');
      options.forEach(opt => {
        // Remove old listeners (remove all cloned children, re-attach)
        opt.replaceWith(opt.cloneNode(true));
      });

      // Re-query after cloning
      const freshOptions = qEl.querySelectorAll('.brief-option');
      freshOptions.forEach(opt => {
        opt.addEventListener('click', () => {
          haptic('light');
          const value = opt.dataset.value;

          // Selected state
          freshOptions.forEach(o => o.classList.remove('selected'));
          opt.classList.add('selected');

          // Save answer
          if (qId === 'brief-q1') {
            brief.experience_level = value;
          } else if (qId === 'brief-q2') {
            if (value === 'other') {
              const otherField = document.getElementById('brief-other-field');
              otherField.classList.remove('hidden');
              document.getElementById('field-brief-other').focus();
              return; // Don't advance, wait for input
            } else {
              brief.preferred_style = value;
            }
          } else if (qId === 'brief-q3') {
            brief.inspiration_source = value;
          } else if (qId === 'brief-q4') {
            brief.importance = value;
          }

          // Auto-advance after short delay
          setTimeout(() => {
            showQuestion(idx + 1);
          }, 250);
        });
      });
    });
  };

  attachHandlers();

  // Handle "other" style input
  const otherInput = document.getElementById('field-brief-other');
  otherInput.addEventListener('input', () => {
    brief.otherStyle = otherInput.value.trim();
  });

  // Check if "other" was already filled, auto-advance when user types
  otherInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && otherInput.value.trim()) {
      haptic('light');
      brief.preferred_style = 'other';
      brief.otherStyle = otherInput.value.trim();
      setTimeout(() => showQuestion(2), 250);
    }
  });
}

/* ===================================================
   REFERENCES (Step 2)
   =================================================== */
function initReferences() {
  const dropZone = document.getElementById('drop-zone');
  const fileInput = document.getElementById('file-input');

  // Click to upload
  dropZone.addEventListener('click', (e) => {
    if (e.target.closest('.remove-ref')) return;
    fileInput.click();
  });

  fileInput.addEventListener('change', (e) => {
    handleFiles(e.target.files);
    fileInput.value = '';
  });

  // Drag & drop
  dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropZone.classList.add('dragover');
  });

  dropZone.addEventListener('dragleave', () => {
    dropZone.classList.remove('dragover');
  });

  dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.classList.remove('dragover');
    handleFiles(e.dataTransfer.files);
  });
}

function handleFiles(files) {
  const maxFiles = 5;
  const remaining = maxFiles - state.draft.references.length;

  if (remaining <= 0) {
    showToast('Максимум 5 референсов');
    return;
  }

  Array.from(files).slice(0, remaining).forEach(file => {
    if (!file.type.startsWith('image/')) return;

    const reader = new FileReader();
    reader.onload = (e) => {
      const ref = {
        fileId: null, // will be set after upload
        dataUrl: e.target.result,
        name: file.name,
      };
      state.draft.references.push(ref);
      renderReferences();
      haptic('light');
    };
    reader.readAsDataURL(file);
  });
}

function renderReferences() {
  const container = document.getElementById('references-preview');
  const refs = state.draft.references;

  container.innerHTML = refs.map((ref, i) => `
    <div class="reference-thumb" data-index="${i}">
      <img src="${ref.dataUrl}" alt="Референс ${i + 1}">
      <button class="remove-ref" data-index="${i}" title="Удалить">×</button>
    </div>
  `).join('');

  document.getElementById('ref-counter').textContent = `Принято: ${refs.length} из 5`;

  // Attach remove handlers
  container.querySelectorAll('.remove-ref').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const idx = parseInt(btn.dataset.index);
      state.draft.references.splice(idx, 1);
      renderReferences();
      haptic('medium');
    });
  });
}

/* ===================================================
   QUICK BUTTONS (chips)
   =================================================== */
function initQuickButtons() {
  document.querySelectorAll('.quick-buttons .chip').forEach(chip => {
    chip.addEventListener('click', () => {
      haptic('light');
      const value = chip.dataset.value;

      // Toggle selection within group
      chip.closest('.quick-buttons').querySelectorAll('.chip').forEach(c => c.classList.remove('selected'));
      chip.classList.add('selected');

      // Fill the associated input
      const fieldId = chip.closest('.form-step').querySelector('input[type="text"]')?.id;
      if (fieldId) {
        document.getElementById(fieldId).value = value;
      }
    });
  });

  // Color options
  document.querySelectorAll('.color-option').forEach(btn => {
    btn.addEventListener('click', () => {
      haptic('light');
      state.draft.colorMode = btn.dataset.value;
      document.querySelectorAll('.color-option').forEach(b => b.classList.remove('selected'));
      btn.classList.add('selected');
    });
  });

  // Urgency options
  document.querySelectorAll('.urgency-option').forEach(btn => {
    btn.addEventListener('click', () => {
      haptic('light');
      state.draft.isUrgent = btn.dataset.value;
      document.querySelectorAll('.urgency-option').forEach(b => b.classList.remove('selected'));
      btn.classList.add('selected');

      const surchargeEl = document.getElementById('urgent-surcharge');
      if (btn.dataset.value === 'yes') {
        surchargeEl.classList.remove('hidden');
      } else {
        surchargeEl.classList.add('hidden');
      }
    });
  });
}

/* ===================================================
   REVIEW CARD (Step 8)
   =================================================== */
function renderReviewCard() {
  const draft = state.draft;

  document.getElementById('review-description').textContent = draft.description;

  // References
  const refContainer = document.getElementById('review-references');
  if (draft.references.length > 0) {
    refContainer.innerHTML = draft.references
      .map(r => `<img src="${r.dataUrl}" alt="Референс">`)
      .join('');
    document.getElementById('review-ref-section').classList.remove('hidden');
  } else {
    document.getElementById('review-ref-section').classList.add('hidden');
  }

  // Basic info
  document.getElementById('review-location').textContent = draft.location;
  document.getElementById('review-size').textContent = draft.size;
  document.getElementById('review-color').textContent = COLOR_LABELS[draft.colorMode] || 'Не указано';
  document.getElementById('review-urgency').textContent = URGENCY_LABELS[draft.isUrgent] || 'Не указано';

  // Brief
  const briefSection = document.getElementById('review-brief-section');
  const briefContainer = document.getElementById('review-brief');
  const brief = draft.brief;

  const briefItems = [
    { key: 'experience_level', label: 'Опыт' },
    { key: 'preferred_style', label: 'Стиль' },
    { key: 'inspiration_source', label: 'Вдохновение' },
    { key: 'importance', label: 'Важнее всего' },
  ];

  const filledItems = briefItems.filter(item => {
    const val = brief[item.key];
    return val && val !== '' && val !== 'other';
  });

  if (filledItems.length > 0) {
    briefSection.classList.remove('hidden');
    briefContainer.innerHTML = filledItems.map(item => {
      let value = brief[item.key];
      if (item.key === 'preferred_style' && value === 'other') {
        value = brief.otherStyle || 'Другое';
      }
      return `<div class="review-brief-item">
        <span class="label">${item.label}</span>
        <span class="value">${value}</span>
      </div>`;
    }).join('');
  } else {
    briefSection.classList.add('hidden');
  }
}

/* ===================================================
   EDIT OPTIONS (for step 8)
   =================================================== */
function showEditOptions() {
  haptic('light');

  const overlay = document.createElement('div');
  overlay.className = 'edit-options-overlay';
  overlay.innerHTML = `
    <div class="edit-options-backdrop" onclick="this.closest('.edit-options-overlay').remove()"></div>
    <div class="edit-options-panel">
      <h3>Изменить шаг</h3>
      ${[1,2,3,4,5,6,7].map(i => `
        <button class="edit-option-btn" data-step="${i}">
          <span class="step-num">${i}</span>
          <span>Шаг ${i}</span>
        </button>
      `).join('')}
    </div>
  `;

  document.body.appendChild(overlay);

  // Attach handlers
  overlay.querySelectorAll('.edit-option-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const step = parseInt(btn.dataset.step);
      overlay.remove();
      state.currentStep = step;
      renderStep();
      haptic('medium');
    });
  });
}

/* ===================================================
   SUBMIT REQUEST
   =================================================== */
async function submitRequest() {
  if (!validateCurrentStep()) return;

  haptic('heavy');

  // Show loading
  const btnNext = document.getElementById('btn-next');
  const originalText = btnNext.textContent;
  btnNext.textContent = 'Отправка...';
  btnNext.disabled = true;

  const userId = gettgId();
  if (!userId) {
    showToast('Ошибка: пользователь не найден');
    btnNext.textContent = originalText;
    btnNext.disabled = false;
    return;
  }

  // Build payload
  const payload = {
    user_id: userId,
    description: state.draft.description,
    location: state.draft.location,
    size: state.draft.size,
    color_mode: state.draft.colorMode,
    is_urgent: state.draft.isUrgent === 'yes',
    urgent_surcharge: state.draft.urgentSurcharge,
    brief_answers: state.draft.brief,
  };

  // Step 1: Create draft
  const draft = await apiPost('requests', payload);
  if (!draft) {
    showToast('Не удалось создать заявку. Проверьте соединение.');
    btnNext.textContent = originalText;
    btnNext.disabled = false;
    return;
  }

  // Step 2: Finalize (draft → new)
  const finalized = await apiPost(`requests/${draft.id}/finalize`, {});
  if (!finalized) {
    showToast('Не удалось отправить заявку. Попробуйте ещё раз.');
    btnNext.textContent = originalText;
    btnNext.disabled = false;
    return;
  }

  // Save draft to storage
  saveDraftToStorage();

  // Show success
  btnNext.textContent = originalText;
  btnNext.disabled = false;

  // Confetti!
  launchConfetti();

  // Show success screen
  document.getElementById('success-request-id').textContent = `Заявка #${draft.id} отправлена!`;
  showScreen('success');
  updateBottomNav(null);
}

/* ===================================================
   SAVE / LOAD DRAFT (localStorage fallback)
   =================================================== */
function saveDraftToStorage() {
  try {
    localStorage.setItem('tatu_draft', JSON.stringify({
      step: state.currentStep,
      draft: state.draft,
    }));
  } catch (e) {
    // Storage full or unavailable
  }
}

function loadDraftFromStorage() {
  try {
    const saved = localStorage.getItem('tatu_draft');
    if (saved) {
      const parsed = JSON.parse(saved);
      state.currentStep = parsed.step || 1;
      Object.assign(state.draft, parsed.draft || {});
      return true;
    }
  } catch (e) {
    // Invalid data
  }
  return false;
}

function clearDraftFromStorage() {
  try {
    localStorage.removeItem('tatu_draft');
  } catch (e) { /* ignore */ }
}

/* ===================================================
   MY REQUESTS
   =================================================== */
async function openMyRequests() {
  haptic('light');
  showScreen('my-requests');
  updateBottomNav('screen-my-requests');

  document.getElementById('requests-loading').classList.remove('hidden');
  document.getElementById('requests-empty').classList.add('hidden');
  document.getElementById('requests-list').innerHTML = '';

  const userId = gettgId();
  if (!userId) {
    showEmptyRequests();
    return;
  }

  const requests = await apiGet(`requests?user_id=${userId}`);
  state.requests = requests || [];

  document.getElementById('requests-loading').classList.add('hidden');

  if (!state.requests || state.requests.length === 0) {
    showEmptyRequests();
    return;
  }

  renderRequestsList();
}

function showEmptyRequests() {
  document.getElementById('requests-empty').classList.remove('hidden');
}

function renderRequestsList() {
  const container = document.getElementById('requests-list');
  container.innerHTML = '';

  state.requests.forEach((req, index) => {
    const status = STATUS_MAP[req.status] || STATUS_MAP.new;
    const card = document.createElement('div');
    card.className = 'request-card';
    card.style.animationDelay = `${index * 50}ms`;

    card.innerHTML = `
      <div class="request-card-header">
        <span class="request-id">📋 Заявка #${req.id}</span>
        <span class="status-badge ${status.cssClass}">${status.icon} ${status.text}</span>
      </div>
      <div class="request-card-body">
        <div class="meta-item">💬 ${req.description?.substring(0, 60) || 'Нет описания'}...</div>
        <div class="meta-item">📍 ${req.location || '—'}</div>
        ${req.size ? `<div class="meta-item">📏 ${req.size}</div>` : ''}
      </div>
      <div class="request-card-actions">
        <button class="btn btn-secondary" onclick="App.openRequestDetail(${req.id})">👁 Открыть</button>
      </div>
    `;

    container.appendChild(card);
  });
}

async function openRequestDetail(requestId) {
  haptic('light');

  let req;
  if (state.requests.find(r => r.id === requestId)) {
    req = state.requests.find(r => r.id === requestId);
  } else {
    req = await apiGet(`requests/${requestId}`);
  }

  if (!req) {
    showToast('Заявка не найдена');
    return;
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

  // References
  const refContainer = document.getElementById('detail-references');
  if (req.references?.length > 0) {
    refContainer.innerHTML = req.references
      .map(r => `<img src="${r.thumbnail_url || r.data_url || ''}" alt="Референс">`)
      .join('');
    document.getElementById('detail-ref-section').classList.remove('hidden');
  } else {
    document.getElementById('detail-ref-section').classList.add('hidden');
  }

  // Brief
  if (req.brief_answers) {
    const briefSection = document.getElementById('detail-brief-section');
    const briefContainer = document.getElementById('detail-brief');
    briefSection.classList.remove('hidden');

    briefContainer.innerHTML = Object.entries(req.brief_answers).map(([key, val]) => {
      let displayVal = val;
      if (key === 'experience_level') {
        displayVal = { none: 'Нет, первая', few: 'Была 1–2', many: 'Было 3+' }[val] || val;
      } else if (key === 'preferred_style') {
        displayVal = {
          realism: 'Реализм', graphics: 'Графика', watercolor: 'Акварель',
          geometry: 'Геометрия', other: val
        }[val] || val;
      } else if (key === 'color_mode') {
        displayVal = COLOR_LABELS[val] || val;
      } else if (key === 'inspiration_source') {
        displayVal = { pinterest: 'Pinterest', instagram: 'Instagram', own: 'Свои референсы', dontknow: 'Не знаю' }[val] || val;
      } else if (key === 'importance') {
        displayVal = { aesthetics: 'Эстетика', meaning: 'Смысл', safety: 'Безопасность' }[val] || val;
      }
      return `<div class="detail-brief-item">
        <span class="label">${BRIEF_LABELS[key] || key}</span>
        <span class="value">${displayVal}</span>
      </div>`;
    }).join('');
  } else {
    document.getElementById('detail-brief-section').classList.add('hidden');
  }

  // Rejection reason
  if (req.rejection_reason) {
    document.getElementById('detail-reason').textContent = req.rejection_reason;
    document.getElementById('detail-rejection-section').classList.remove('hidden');
  } else {
    document.getElementById('detail-rejection-section').classList.add('hidden');
  }

  openModal('modal-request-detail');
}

/* ===================================================
   LAST REQUEST (from home)
   =================================================== */
function openLastRequest() {
  haptic('light');
  const card = document.getElementById('home-last-request');
  const infoEl = document.getElementById('last-request-info');
  const text = infoEl.textContent;
  const match = text.match(/#(\d+)/);
  if (match) {
    openRequestDetail(parseInt(match[1]));
  }
}

/* ===================================================
   CALENDAR
   =================================================== */
async function openCalendar() {
  haptic('light');
  showScreen('calendar');
  updateBottomNav('screen-calendar');
  renderCalendar();
  await loadCalendarSlots();
}

function prevMonth() {
  haptic('light');
  state.calendarMonth--;
  if (state.calendarMonth < 0) {
    state.calendarMonth = 11;
    state.calendarYear--;
  }
  renderCalendar();
}

function nextMonth() {
  haptic('light');
  state.calendarMonth++;
  if (state.calendarMonth > 11) {
    state.calendarMonth = 0;
    state.calendarYear++;
  }
  renderCalendar();
}

function renderCalendar() {
  const year = state.calendarYear;
  const month = state.calendarMonth;

  const monthNames = [
    'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
    'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь'
  ];

  document.getElementById('calendar-month-year').textContent = `${monthNames[month]} ${year}`;

  const grid = document.getElementById('calendar-grid');
  grid.innerHTML = '';

  const firstDay = new Date(year, month, 1);
  // JS: Sunday=0, Monday=1... We want Monday=0
  let startDay = firstDay.getDay() - 1;
  if (startDay < 0) startDay = 6;

  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const today = new Date();
  const todayStr = formatDate(today);

  // Empty cells before first day
  for (let i = 0; i < startDay; i++) {
    const cell = document.createElement('div');
    cell.className = 'calendar-day empty';
    grid.appendChild(cell);
  }

  // Day cells
  for (let day = 1; day <= daysInMonth; day++) {
    const cell = document.createElement('div');
    cell.className = 'calendar-day';
    cell.textContent = day;

    const dateStr = `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;

    if (dateStr === todayStr) {
      cell.classList.add('today');
    }

    const slot = state.calendarSlots[dateStr];
    if (slot) {
      if (slot.is_blocked) {
        cell.classList.add('busy');
      } else {
        cell.classList.add('free');
      }
    } else {
      // No slot data — default to free
      cell.classList.add('free');
    }

    cell.addEventListener('click', () => {
      haptic('light');
      // Could open a detail view for the date
    });

    grid.appendChild(cell);
  }

  // Hide/show empty state
  const hasSlots = Object.keys(state.calendarSlots).length > 0;
  document.getElementById('calendar-empty').classList.toggle('hidden', hasSlots);
}

async function loadCalendarSlots() {
  const from = formatDate(new Date(state.calendarYear, state.calendarMonth, 1));
  const to = formatDate(new Date(state.calendarYear, state.calendarMonth + 1, 0));

  const slots = await apiGet(`slots?from=${from}&to=${to}`);
  if (slots) {
    state.calendarSlots = {};
    slots.forEach(slot => {
      state.calendarSlots[slot.slot_date] = slot;
    });
  } else {
    // Fallback: mock data if API is down
    generateMockSlots();
  }
}

function generateMockSlots() {
  // Generate some mock busy dates for demo
  const year = state.calendarYear;
  const month = state.calendarMonth;
  const today = new Date();

  // Block some dates randomly for demo
  const busyDays = [3, 7, 10, 14, 18, 22, 25, 28];

  busyDays.forEach(day => {
    if (day <= new Date(year, month + 1, 0).getDate()) {
      const dateStr = `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
      state.calendarSlots[dateStr] = {
        slot_date: dateStr,
        is_blocked: true,
      };
    }
  });
}

/* ===================================================
   MASTER CONTACT
   =================================================== */
function openMasterContact() {
  haptic('light');
  // Open master's Telegram profile
  if (tg) {
    tg.openTelegramLink('https://t.me/aritu_tattoo'); // Replace with actual username
  } else {
    window.open('https://t.me/aritu_tattoo', '_blank');
  }
}

/* ===================================================
   CLOSE REQUEST FORM
   =================================================== */
function cancelRequestForm() {
  haptic('light');
  if (state.currentStep === 1 || confirm('Отменить создание заявки?')) {
    clearDraftFromStorage();
    initHome();
  }
}

/* ===================================================
   MODALS
   =================================================== */
function openModal(modalId) {
  const modal = document.getElementById(modalId);
  if (modal) {
    modal.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
  }
}

function closeModal(modalId) {
  const modal = document.getElementById(modalId);
  if (modal) {
    modal.classList.add('hidden');
    document.body.style.overflow = '';
  }
}

/* ===================================================
   BOTTOM NAV
   =================================================== */
function updateBottomNav(activeScreen) {
  const nav = document.getElementById('bottom-nav');
  if (!nav) return;

  nav.querySelectorAll('.nav-item').forEach(item => {
    item.classList.toggle('active', item.dataset.screen === activeScreen);
  });
}

function goHome() {
  haptic('light');
  initHome();
}

/* ===================================================
   CONFETTI
   =================================================== */
function launchConfetti() {
  const canvas = document.getElementById('confetti-canvas');
  canvas.classList.remove('hidden');
  const ctx = canvas.getContext('2d');
  canvas.width = window.innerWidth;
  canvas.height = window.innerHeight;

  const particles = [];
  const colors = ['#D4A24E', '#F5E6C8', '#4CAF50', '#E53935', '#FF9800', '#2196F3', '#FFFFFF'];

  for (let i = 0; i < 80; i++) {
    particles.push({
      x: Math.random() * canvas.width,
      y: -20 - Math.random() * 100,
      w: 4 + Math.random() * 6,
      h: 4 + Math.random() * 6,
      color: colors[Math.floor(Math.random() * colors.length)],
      vx: (Math.random() - 0.5) * 4,
      vy: 2 + Math.random() * 4,
      rotation: Math.random() * 360,
      rotationSpeed: (Math.random() - 0.5) * 10,
      opacity: 1,
    });
  }

  let frame = 0;
  const maxFrames = 120;

  function animate() {
    if (frame > maxFrames) {
      canvas.classList.add('hidden');
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      return;
    }

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    particles.forEach(p => {
      p.x += p.vx;
      p.y += p.vy;
      p.vy += 0.1; // gravity
      p.rotation += p.rotationSpeed;

      if (frame > maxFrames - 30) {
        p.opacity -= 0.03;
      }

      ctx.save();
      ctx.translate(p.x, p.y);
      ctx.rotate((p.rotation * Math.PI) / 180);
      ctx.globalAlpha = Math.max(0, p.opacity);
      ctx.fillStyle = p.color;
      ctx.fillRect(-p.w / 2, -p.h / 2, p.w, p.h);
      ctx.restore();
    });

    frame++;
    requestAnimationFrame(animate);
  }

  animate();
}

/* ===================================================
   TOAST NOTIFICATIONS
   =================================================== */
function showToast(message, duration = 3000) {
  // Remove existing toast
  const existing = document.querySelector('.toast');
  if (existing) existing.remove();

  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.textContent = message;
  toast.style.cssText = `
    position: fixed;
    top: 20px;
    left: 50%;
    transform: translateX(-50%);
    background: var(--primary);
    color: #fff;
    padding: 12px 24px;
    border-radius: 8px;
    font-size: 13px;
    z-index: 300;
    animation: slideUp 0.3s ease-out;
    max-width: 90vw;
    text-align: center;
    box-shadow: 0 4px 12px rgba(0,0,0,0.3);
  `;
  document.body.appendChild(toast);

  setTimeout(() => {
    toast.style.animation = 'fadeOut 0.3s ease-in';
    setTimeout(() => toast.remove(), 300);
  }, duration);
}

/* ===================================================
   RIPPLE EFFECT ON BUTTONS
   =================================================== */
function initRipple() {
  document.addEventListener('click', (e) => {
    const btn = e.target.closest('.btn, .menu-btn, .nav-item');
    if (!btn) return;

    const rect = btn.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;

    btn.style.setProperty('--ripple-x', `${(x / rect.width) * 100}%`);
    btn.style.setProperty('--ripple-y', `${(y / rect.height) * 100}%`);

    btn.classList.add('ripple');
    setTimeout(() => btn.classList.remove('ripple'), 600);
  });
}

/* ===================================================
   TEXTAREA COUNTER
   =================================================== */
function initTextareaCounter() {
  const textarea = document.getElementById('field-description');
  const counter = document.getElementById('desc-count');

  if (textarea && counter) {
    textarea.addEventListener('input', () => {
      counter.textContent = textarea.value.length;
    });
  }
}

/* ===================================================
   INITIALIZATION
   =================================================== */
async function init() {
  // Show loading
  showScreen('loading');

  // Initialize Telegram
  initTelegram();

  // Initialize UI helpers
  initReferences();
  initQuickButtons();
  initTextareaCounter();
  initRipple();

  // Load saved draft if exists
  const hasDraft = loadDraftFromStorage();

  // Show home
  await initHome();

  // If there's a draft in progress, offer to continue
  if (hasDraft && state.currentStep > 1) {
    // Optional: show a banner "Продолжить черновик?"
    // For now, we just keep the draft in localStorage
  }
}

/* ===================================================
   GLOBAL EXPORT
   =================================================== */
window.App = {
  // Navigation
  goHome,
  startNewRequest,
  openMyRequests,
  openCalendar,
  openMasterContact,
  cancelRequestForm,

  // Request form
  nextStep,
  prevStep,
  showEditOptions,
  submitRequest,

  // Requests
  openLastRequest,
  openRequestDetail,

  // Calendar
  prevMonth,
  nextMonth,

  // Modals
  openModal,
  closeModal,
};

// Start app when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
