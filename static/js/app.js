/*
  I-Turn — student UI logic.

  Plain JavaScript, no framework, no build. It talks to the JSON API only.
  Everything is built with DOM nodes and textContent, never by parsing strings as
  HTML, so a student's message, a model reply or a server string can never inject
  markup.
*/
(() => {
  'use strict';

  const $ = (s, r = document) => r.querySelector(s);
  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  };
  const SVG = 'http://www.w3.org/2000/svg';
  const icon = name => {
    const s = document.createElementNS(SVG, 'svg');
    s.setAttribute('class', 'icon');
    s.setAttribute('aria-hidden', 'true');
    const u = document.createElementNS(SVG, 'use');
    u.setAttribute('href', '#i-' + name);
    s.append(u);
    return s;
  };
  const button = (label, cls, type = 'button') => {
    const b = el('button', cls, label);
    b.type = type;
    return b;
  };
  // Server text may contain **bold** and nothing else.
  const rich = (node, text) => {
    String(text).split(/(\*\*[^*]+\*\*)/g).forEach(part => {
      if (part.length > 4 && part.startsWith('**') && part.endsWith('**')) {
        node.append(el('strong', '', part.slice(2, -2)));
      } else if (part) {
        node.append(document.createTextNode(part));
      }
    });
    return node;
  };

  const state = {
    sid: null, mode: 'incognito', name: '', busy: false, halted: false,
    meta: null, card: null, dev: new URLSearchParams(location.search).has('dev'),
  };

  const gate = $('#gate'), chat = $('#chat'), thread = $('#thread'), composer = $('#composer');
  const input = $('#input'), sendBtn = $('#send'), jump = $('#jump');

  // --------------------------------------------------------------- announcing
  function announce(text, urgent) {
    const box = $(urgent ? '#alert-announcer' : '#announcer');
    box.textContent = '';
    setTimeout(() => { box.textContent = text; }, 50);
  }

  // -------------------------------------------------------------------- theme
  const themeBtn = $('#theme');
  const isDark = () => {
    const t = document.documentElement.dataset.theme;
    return t ? t === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
  };
  function paintTheme() {
    const dark = isDark();
    themeBtn.setAttribute('aria-label', dark ? 'Switch to light theme' : 'Switch to dark theme');
    themeBtn.querySelector('use').setAttribute('href', dark ? '#i-sun' : '#i-moon');
  }
  themeBtn.addEventListener('click', () => {
    const next = isDark() ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem('iturn-theme', next); } catch (e) { /* storage can be blocked */ }
    paintTheme();
  });
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', paintTheme);
  paintTheme();

  // ---------------------------------------------------------------------- api
  class ApiError extends Error {
    constructor(code, status, detail) {
      super(code);
      this.code = code; this.status = status; this.detail = detail || '';
    }
  }
  async function api(path, body) {
    let res;
    try {
      res = await fetch(path, {
        method: body === undefined ? 'GET' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch (e) {
      throw new ApiError('offline', 0, String(e));
    }
    let data = null;
    try { data = await res.json(); } catch (e) { /* not JSON */ }
    if (!res.ok) {
      const code = (data && data.error && data.error.code)
        || (res.status === 404 ? 'session_lost' : res.status === 422 ? 'bad_request' : 'server_error');
      throw new ApiError(code, res.status, data && data.detail);
    }
    return data;
  }

  // What a student reads when something goes wrong. Never technical, never blaming.
  const FRIENDLY = {
    offline: 'You seem to be offline. Your message is still here — try again when you’re back.',
    unavailable: 'I can’t reach my thinking part right now. Your message is still here — try again in a moment.',
    timeout: 'That’s taking longer than it should. Try again in a moment.',
    interrupted: 'The connection dropped for a second. Try again.',
    busy: 'I’m a bit busy right now. Give it a moment, then try again.',
    model_loading: 'I’m just getting ready — give me a minute.',
    model_error: 'Something’s wrong on my side, and it isn’t anything you did. Try again a little later.',
    out_of_memory: 'Something’s wrong on my side, and it isn’t anything you did. Try again a little later.',
    unauthorized: 'Something’s wrong on my side, and it isn’t anything you did. Try again a little later.',
    bad_url: 'Something’s wrong on my side, and it isn’t anything you did. Try again a little later.',
    bad_request: 'That didn’t go through. Please check it and try again.',
    invalid_response: 'I got a bit muddled. Try again.',
    server_error: 'Something went wrong on my side. Try again.',
  };
  const friendly = err => FRIENDLY[err.code] || FRIENDLY.server_error;

  // ------------------------------------------------------------ scroll / push
  const nearBottom = () => innerHeight + scrollY >= document.documentElement.scrollHeight - 160;
  function push(node, force) {
    const stick = force || nearBottom();
    thread.append(node);
    if (stick) {
      node.scrollIntoView({ block: 'end' });        // instant: smooth scrolling can lose a race with a fast reply
    } else {
      jump.hidden = false;
    }
    return node;
  }
  addEventListener('scroll', () => { if (!chat.hidden) jump.hidden = nearBottom(); }, { passive: true });
  jump.addEventListener('click', () => {
    scrollTo({ top: document.documentElement.scrollHeight });
    jump.hidden = true;
  });
  function syncComposerH() {
    document.documentElement.style.setProperty('--composer-h', composer.offsetHeight + 'px');
  }
  new ResizeObserver(syncComposerH).observe(composer);
  addEventListener('resize', syncComposerH);

  // ------------------------------------------------------------------ messages
  function say(who, text) {
    const wrap = el('div', 'msg ' + (who === 'me' ? 'msg--me' : 'msg--them'));
    if (who === 'me') {
      wrap.append(el('div', 'msg__body', text));
    } else {
      rich(wrap, text);
      announce(text);
    }
    return push(wrap, who === 'me');
  }
  function typing() {
    const n = el('div', 'typing');
    n.setAttribute('role', 'status');
    n.setAttribute('aria-label', 'I’m thinking');
    n.append(el('i'), el('i'), el('i'));
    return push(n, true);
  }
  function failure(err, retry) {
    if (err.code === 'session_lost' && err.status === 404) return sessionLost();
    const n = el('div', 'sys');
    n.setAttribute('role', 'alert');
    n.append(el('p', 'sys__text', friendly(err)));
    if (retry) {
      const acts = el('div', 'sys__actions');
      const b = button('Try again', 'btn btn--secondary btn--sm');
      b.addEventListener('click', () => { n.remove(); retry(); });
      acts.append(b);
      n.append(acts);
    }
    if (state.dev && (err.detail || err.code)) {          // technical detail: dev builds only
      const d = el('details');
      d.append(el('summary', '', 'Details'), el('pre', '', `${err.code} (${err.status})\n${err.detail}`));
      n.append(d);
    }
    push(n, true);
    return n;
  }
  function sessionLost() {
    lockComposer();
    const c = el('div', 'card');
    c.append(el('p', '', 'This conversation timed out on our side. Start a new one when you’re ready.'));
    const acts = el('div', 'card__actions');
    const b = button('Start a new conversation', 'btn btn--primary');
    b.addEventListener('click', () => location.reload());
    acts.append(b); c.append(acts);
    push(c, true);
    return c;
  }
  function lockComposer() { composer.hidden = true; state.sid = null; }

  // ------------------------------------------------------------------ composer
  function autosize() {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 144) + 'px';
    input.style.overflowY = input.scrollHeight > 144 ? 'auto' : 'hidden';
    updateSend();
    syncComposerH();
    const c = $('#count'), n = input.value.length;
    c.hidden = n < 3500;
    if (!c.hidden) c.textContent = n.toLocaleString() + ' / 4,000';
  }
  const canSend = () => !state.busy && !!state.sid && input.value.trim().length > 0;
  const updateSend = () => { sendBtn.disabled = !canSend(); };
  function setBusy(b) {
    state.busy = b;
    thread.setAttribute('aria-busy', String(b));
    updateSend();
  }
  input.addEventListener('input', autosize);
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      if (canSend()) composer.requestSubmit();
    }
  });
  composer.addEventListener('submit', e => {
    e.preventDefault();
    if (!canSend()) return;
    const text = input.value.trim();
    input.value = '';
    autosize();
    say('me', text);
    sendTurn(text);
  });

  async function sendTurn(text) {
    setBusy(true);
    const dots = typing();
    try {
      const res = await api('/api/turn', { session_id: state.sid, text });
      dots.remove();
      handle(res);
    } catch (err) {
      dots.remove();
      failure(err, () => sendTurn(text));
    } finally {
      setBusy(false);
      if (state.sid && !state.halted) input.focus({ preventScroll: true });   // in a crisis, focus stays on the panel
    }
  }

  // ---------------------------------------------------- the one dispatcher
  function handle(res) {
    if (res.session_halted && res.resources) return showCare(res);
    if (res.result) return renderResult(res);
    if (res.message) say('them', res.message);
    if (res.offer) renderOffer(res.offer);
    if (res.item) renderItem(res.item, { suggested: res.suggested });
    else if (res.items && res.items.length) renderItem(res.items[0], { progress: res.progress });
  }

  // -------------------------------------------------------------- the offer
  function record(text) { return el('p', 'card__record', text); }
  function renderOffer(offer) {
    const card = el('div', 'card');
    card.append(el('p', '', offer.prompt));
    const acts = el('div', 'card__actions');
    const yes = button((offer.actions && offer.actions[0]) || 'Sure', 'btn btn--secondary');
    const no = button((offer.actions && offer.actions[1]) || 'Not now', 'btn btn--secondary');   // equal weight, on purpose
    acts.append(yes, no); card.append(acts);
    const choose = async which => {
      acts.querySelectorAll('button').forEach(b => { b.disabled = true; });
      try {
        const res = await api('/api/instrument/' + which, { session_id: state.sid });
        acts.replaceWith(record(which === 'accept' ? 'Starting the questionnaire.'
          : 'You chose to skip. It’s here if you change your mind.'));
        handle(res);
      } catch (err) {
        acts.querySelectorAll('button').forEach(b => { b.disabled = false; });
        failure(err, () => choose(which));
      }
    };
    yes.addEventListener('click', () => choose('accept'));
    no.addEventListener('click', () => choose('decline'));
    push(card, true);
  }

  // ---------------------------------------------------------- the questionnaire
  const TOTAL = 21;
  const cap = s => s.charAt(0).toUpperCase() + s.slice(1);
  function renderItem(item, opts = {}) {
    if (state.card && state.card.isConnected) state.card.remove();   // one live statement at a time
    const card = el('div', 'card');
    const id = 'stmt-' + item.number;
    card.append(el('p', 'q__frame', `${cap(item.time_frame || 'over the past week')} — statement ${item.number} of ${TOTAL}`));
    const stmt = el('p', 'q__stmt', item.text);
    stmt.id = id;
    card.append(stmt);
    const group = el('div', 'answers');
    group.setAttribute('role', 'group');
    group.setAttribute('aria-labelledby', id);
    Object.entries(item.anchors).forEach(([v, label]) => {
      const b = button('', 'answer');
      b.append(el('span', 'answer__n', v), el('span', '', label));
      if (opts.suggested !== undefined && String(opts.suggested) === v) {
        b.classList.add('answer--suggested');
        b.setAttribute('aria-description', 'Suggested from what you wrote — tap to confirm');
      }
      b.addEventListener('click', () => answer(card, group, item, Number(v), label));
      group.append(b);
    });
    card.append(group);

    const foot = el('div', 'q__foot');
    const prog = el('div', 'q__progress');
    const bar = el('div', 'bar');
    bar.setAttribute('role', 'progressbar');
    bar.setAttribute('aria-label', 'Questionnaire progress');
    bar.setAttribute('aria-valuemin', '0');
    bar.setAttribute('aria-valuemax', String(TOTAL));
    bar.setAttribute('aria-valuenow', String(item.number - 1));
    const fill = el('span'); fill.style.width = (((item.number - 1) / TOTAL) * 100).toFixed(1) + '%';
    bar.append(fill); prog.append(bar);
    const stop = button('Stop for now', 'btn btn--link');
    stop.addEventListener('click', () => stopQuestionnaire(card));
    foot.append(prog, stop); card.append(foot);

    state.card = card;
    push(card, true);
  }
  async function answer(card, group, item, value, label) {
    group.querySelectorAll('button').forEach(b => { b.disabled = true; });
    try {
      const res = await api('/api/instrument/answer', { session_id: state.sid, item: item.number, value });
      const done = el('p', 'q--done', `Statement ${item.number} — you answered ${value}: ${label}`);
      card.replaceWith(done);
      state.card = null;
      handle(res);
    } catch (err) {
      group.querySelectorAll('button').forEach(b => { b.disabled = false; });
      failure(err, () => answer(card, group, item, value, label));
    }
  }
  async function stopQuestionnaire(card) {
    try {
      const res = await api('/api/instrument/stop', { session_id: state.sid });
      card.replaceWith(el('p', 'q--done', 'You paused the questionnaire.'));
      state.card = null;
      handle(res);
    } catch (err) {
      failure(err, () => stopQuestionnaire(card));
    }
  }

  // ------------------------------------------------------------------- results
  const LEVELS = ['Normal', 'Mild', 'Moderate', 'Severe', 'Extremely severe'];
  // Display names for the three areas live here so the clinical team can soften them in one place.
  const AREAS = [['depression', 'Depression'], ['anxiety', 'Anxiety'], ['stress', 'Stress']];
  function bandRows(bands) {
    const wrap = el('div', 'bands');
    AREAS.forEach(([key, name]) => {
      if (!bands[key]) return;
      const row = el('div', 'band');
      row.append(el('span', 'band__name', name), el('span', 'band__word', bands[key]));
      const scale = el('div', 'scale');
      scale.setAttribute('aria-hidden', 'true');           // the word carries the meaning
      const at = LEVELS.indexOf(bands[key]);
      LEVELS.forEach((_, i) => scale.append(el('i', i <= at ? 'on' : '')));
      row.append(scale); wrap.append(row);
    });
    return wrap;
  }
  function renderResult(res) {
    const card = el('div', 'card');
    card.append(el('p', '', res.message || 'That’s all 21. These are screening bands, not a diagnosis — they describe the past week, not you.'));
    card.append(bandRows(res.result.bands));
    card.append(el('p', 'card__note', 'If you’d like to talk about how that felt, I’m here.'));
    push(card, true);
    announce('Questionnaire complete.');
    if (res.offer_referral) {
      const ref = el('div', 'card card--soft');
      ref.append(el('p', '', 'You can talk to a counsellor without explaining yourself first.'));
      const acts = el('div', 'card__actions');
      const b = button('See how to reach someone', 'btn btn--secondary');
      b.addEventListener('click', openHelp);
      acts.append(b); ref.append(acts);
      push(ref, true);
    }
  }

  // ------------------------------------------------- help / crisis resources
  // If /api/meta can't be loaded, help must still work.
  const FALLBACK = { national: { name: 'Tele-MANAS (Govt. of India, 24x7, 20 languages)', numbers: ['14416', '1-800-891-4416'] } };
  const real = s => !!s && !String(s).includes('<<');           // never show a "fill in" placeholder
  const telHref = n => 'tel:' + String(n).replace(/[^\d+]/g, '');

  function copyText(text) {
    const done = () => announce('Copied ' + text);
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done, () => legacyCopy(text, done));
    } else {
      legacyCopy(text, done);
    }
  }
  function legacyCopy(text, done) {
    const t = el('textarea'); t.value = text; t.style.position = 'fixed'; t.style.opacity = '0';
    document.body.append(t); t.select();
    try { document.execCommand('copy'); done(); } catch (e) { /* nothing more we can do */ }
    t.remove();
  }
  function callRow(label, number, spoken = label) {
    const row = el('div', 'res');
    const a = el('a', 'res__call');
    a.href = telHref(number);
    a.setAttribute('aria-label', `Call ${spoken}: ${number}`);
    const txt = el('span');
    txt.append(el('span', 'res__label', label), el('span', 'res__num', number));
    a.append(icon('phone'), txt);
    const cp = button('', 'res__copy');
    cp.append(icon('copy'), document.createTextNode('Copy'));
    cp.setAttribute('aria-label', `Copy ${number}`);
    cp.addEventListener('click', () => copyText(number));
    row.append(a, cp);
    return row;
  }
  function noteRow(text) {
    const n = el('div', 'res--note');
    n.append(icon('users'), el('span', '', text));
    return n;
  }
  function resourceRows(resources) {
    const r = resources || FALLBACK;
    const list = el('div', 'resources');
    const nat = r.national || FALLBACK.national;
    const shortName = String(nat.name).replace(/\s*\(.*\)\s*$/, '') || nat.name;
    (nat.numbers || []).filter(real).forEach((n, i) => list.append(callRow(i === 0 ? nat.name : shortName, n, shortName)));
    const campus = r.campus;
    if (campus) {
      const nums = (campus.numbers || []).filter(real);
      const label = campus.name + (real(campus.hours) ? ' · ' + campus.hours : '');
      nums.forEach(n => list.append(callRow(label, n)));                // omitted entirely until configured
    }
    list.append(callRow('If you’re in immediate danger', '112', 'emergency services'));
    list.append(noteRow('Someone you trust who is physically near you — a friend, a warden, family'));
    return list;
  }
  const helpDlg = $('#help');
  function buildHelp() {
    const box = $('#help-rows');
    box.replaceChildren(...resourceRows(state.meta && state.meta.crisis_resources).children);
  }
  function openHelp() { helpDlg.showModal(); }
  $('#help-open').addEventListener('click', openHelp);
  document.addEventListener('click', e => {
    const close = e.target.closest('[data-close]');
    if (close) { const d = close.closest('dialog'); if (d) d.close(); return; }
    if (e.target instanceof HTMLDialogElement) e.target.close();       // click on the backdrop
  });

  // -------------------------------------------------------------- crisis panel
  function showCare(res) {
    state.halted = true;
    const care = el('section', 'care');
    care.tabIndex = -1;
    care.setAttribute('aria-label', 'Support');
    let rowsDone = false;
    String(res.message || '').split(/\n\s*\n/).forEach(block => {
      const lines = block.split('\n').map(s => s.trim()).filter(Boolean);
      if (lines.length && lines.every(l => l.startsWith('•'))) {
        // The bullet list becomes big tappable rows (structured data, never the placeholder text).
        if (!rowsDone) { care.append(resourceRows(res.resources)); rowsDone = true; }
        return;
      }
      if (rowsDone && /\b112\b/.test(block)) return;                    // the 112 row already covers it
      care.append(rich(el('p'), block));
    });
    if (!rowsDone) care.append(resourceRows(res.resources));
    push(care, true);
    care.focus({ preventScroll: true });
    announce((res.message || '').split('\n')[0], true);
    input.placeholder = 'You can write here if you want. You don’t have to.';
    composer.classList.add('composer--care');       // room for the longer placeholder
  }

  // ------------------------------------------------------------------- summary
  const doneBtn = $('#done'), finishDlg = $('#finish');
  doneBtn.addEventListener('click', () => {
    if (!state.sid) return;
    $('#finish-text').textContent = state.mode === 'incognito'
      ? 'You’re in Incognito, so nothing is kept — the summary is the only copy.'
      : 'I’ll show you a short summary. Your conversation stays saved under your name.';
    finishDlg.showModal();
  });
  // Act on the click itself rather than waiting for the dialog's close event.
  $('#finish-yes').addEventListener('click', () => { finishDlg.close(); endSession(); });

  async function endSession() {
    try {
      const res = await api('/api/end', { session_id: state.sid });
      lockComposer();
      renderSummary(res.report || {}, res.mode);
    } catch (err) {
      failure(err, endSession);
    }
  }
  function summaryText(r, mode) {
    const out = ['I-Turn — summary', r.length ? 'Length: ' + r.length : ''];
    (r.you_talked_about || []).forEach(x => out.push(`${x.about}: “${x.you_said}”`));
    if (r.screening_bands) AREAS.forEach(([k, n]) => r.screening_bands[k] && out.push(`${n}: ${r.screening_bands[k]}`));
    if (r.screening_note) out.push(r.screening_note);
    return out.filter(Boolean).join('\n');
  }
  function renderSummary(r, mode) {
    const s = el('section', 'summary');
    s.tabIndex = -1;
    s.setAttribute('aria-labelledby', 'sum-title');
    const h = el('h2', '', 'That’s where we’ll leave it.');
    h.id = 'sum-title';
    s.append(h);
    s.append(el('p', 'summary__meta', [r.length, r.ephemeral ? 'nothing was kept' : ''].filter(Boolean).join(' · ')));

    const said = r.you_talked_about || [];
    if (said.length) {
      s.append(el('h3', '', 'You talked about'));
      said.forEach(x => {
        const q = el('blockquote', 'quote');
        q.append(el('div', 'quote__about', x.about), el('div', 'quote__said', x.you_said));
        s.append(q);
      });
    }
    if (r.screening_bands) s.append(bandRows(r.screening_bands));
    if (r.screening_note) s.append(el('p', 'summary__note', r.screening_note));
    if (r.ephemeral || mode === 'incognito') {
      s.append(el('p', 'summary__keep', 'This is the only time you’ll see this. Copy or print it now if you want to keep it.'));
    }
    if (r.next && r.next.length) {
      const ul = el('ul');
      r.next.forEach(t => ul.append(el('li', '', t)));
      s.append(ul);
    }
    const acts = el('div', 'summary__actions');
    const cp = button('', 'btn btn--secondary');
    cp.append(icon('copy'), document.createTextNode('Copy summary'));
    cp.addEventListener('click', () => copyText(summaryText(r, mode)));
    const pr = button('', 'btn btn--secondary');
    pr.append(icon('printer'), document.createTextNode('Print'));
    pr.addEventListener('click', () => print());
    const again = button('Start a new conversation', 'btn btn--primary');
    again.addEventListener('click', () => location.reload());
    acts.append(cp, pr, again); s.append(acts);
    push(s, false);
    s.scrollIntoView({ block: 'start' });
    s.focus({ preventScroll: true });
    announce('Summary ready.');
  }

  // --------------------------------------------------------------- the gate
  const pseudo = $('#pseudonym'), begin = $('#begin'), beginLabel = $('#begin-label');
  const consentBox = $('#consent'), consentCheck = $('#consent-check'), consentErr = $('#consent-err');
  const gateErr = $('#gate-error');
  const WORDS = ['Willow', 'Juniper', 'Marigold', 'Sparrow', 'Cedar', 'Larkspur', 'Heron', 'Ember', 'Moss',
    'Tern', 'Aster', 'Wren', 'Fern', 'Linden', 'Sorrel', 'Plover', 'Alder', 'Clover', 'Birch', 'Thistle'];
  function suggestName() {
    const a = new Uint32Array(2);
    crypto.getRandomValues(a);
    // a short number keeps two students from landing on the same name (matters in Story mode)
    return WORDS[a[0] % WORDS.length] + '-' + String(1000 + (a[1] % 9000));
  }
  pseudo.value = suggestName();
  $('#shuffle').addEventListener('click', () => {
    pseudo.value = suggestName();
    pseudo.removeAttribute('aria-invalid');
    $('#name-hint').textContent = 'Use 3–40 characters. Not your real name.';
    announce('New name: ' + pseudo.value);
    pseudo.focus();
  });
  document.querySelectorAll('input[name="mode"]').forEach(r => r.addEventListener('change', () => {
    state.mode = r.value;
    consentBox.hidden = r.value !== 'story';
    consentErr.hidden = true;
  }));

  function renderNotice(text) {
    const body = $('#notice-body');
    body.replaceChildren();
    String(text).split(/\n\s*\n/).forEach(p => {
      const para = rich(el('p'), p.trim());
      if (/^One exception/i.test(p.trim())) para.className = 'notice__exception';
      body.append(para);
    });
  }
  async function loadMeta() {
    try {
      state.meta = await api('/api/meta');
      renderNotice(state.meta.privacy_notice);
      begin.disabled = false;
    } catch (err) {
      // Don't let anyone start without seeing what is kept.
      renderNotice('I couldn’t load the privacy notice, so I can’t start yet. Please refresh the page.');
      begin.disabled = true;
    }
    buildHelp();
  }
  begin.disabled = true;

  $('#gate-form').addEventListener('submit', async e => {
    e.preventDefault();
    gateErr.hidden = true; consentErr.hidden = true;
    pseudo.removeAttribute('aria-invalid');
    const name = pseudo.value.trim();
    if (name.length < 3 || name.length > 40) {
      pseudo.setAttribute('aria-invalid', 'true');
      $('#name-hint').textContent = 'Please use between 3 and 40 characters.';
      pseudo.focus();
      return;
    }
    if (state.mode === 'story' && !consentCheck.checked) {
      consentErr.hidden = false;
      consentCheck.focus();
      return;
    }
    begin.disabled = true; begin.setAttribute('aria-busy', 'true'); beginLabel.textContent = 'Starting…';
    try {
      const res = await api('/api/start', { pseudonym: name, mode: state.mode, language: 'English' });
      state.sid = res.session_id; state.name = name;
      enterChat(res);
    } catch (err) {
      gateErr.textContent = err.code === 'bad_request' ? friendly(err) : 'Couldn’t start. Try again in a moment.';
      gateErr.hidden = false;
    } finally {
      begin.disabled = false; begin.removeAttribute('aria-busy'); beginLabel.textContent = 'Start talking';
    }
  });

  function enterChat(res) {
    gate.hidden = true;
    chat.hidden = false;
    composer.hidden = false;
    syncComposerH();
    $('#pilot-chip').hidden = true;
    $('#modeline').textContent = state.mode === 'incognito'
      ? 'Incognito — nothing is kept.'
      : `Story — remembered under “${state.name}”.`;
    say('them', res.returning ? 'Good to see you again. Where did we leave things?' : 'I’m listening. Take your time.');
    autosize();
    input.focus();
    scrollTo({ top: 0 });
  }

  // ------------------------------------------------------ offline + dev status
  const offline = $('#offline');
  const paintOnline = () => { offline.hidden = navigator.onLine; };
  addEventListener('online', paintOnline); addEventListener('offline', paintOnline);
  paintOnline();

  if (state.dev) {
    const dot = $('#dev-dot');
    dot.hidden = false;
    const poll = async () => {
      try {
        const r = await fetch('/api/ai/health');
        const j = await r.json();
        dot.dataset.s = j.status === 'ok' ? 'ok' : j.status === 'loading' ? 'loading' : 'down';
        dot.title = 'AI server: ' + j.status + (j.model ? ' (' + j.model + ')' : '');
      } catch (e) { dot.dataset.s = 'down'; }
    };
    poll(); setInterval(poll, 30000);
  }

  loadMeta();
})();
