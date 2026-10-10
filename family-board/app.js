(() => {
  const PALETTE = ['#FF8FA3', '#7BD3B9', '#FFC857', '#9C8CFF', '#6EC1FF', '#FF9F68', '#9BE07A', '#F78CD9'];
  const EMOJI = ['🦊', '🐻', '🐼', '🐨', '🦁', '🐯', '🐸', '🐵', '🦄', '🐙', '🐢', '🐝', '🌸', '⭐', '🚀', '⚽', '🎸', '🧁'];
  const DOW = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  const CHEERS = ['Nice work', 'Woohoo', 'Way to go', 'Superstar', 'Awesome', 'High five', 'Nailed it'];
  const MEALS = [['breakfast', '🥞', 'Breakfast'], ['lunch', '🥪', 'Lunch'], ['dinner', '🍝', 'Dinner'], ['snack', '🍎', 'Snack']];
  const PERIODS = [['morning', '🌅', 'Morning'], ['afternoon', '🌤️', 'Afternoon'], ['evening', '🌙', 'Evening']];
  const LEGACY_VIEWS = { week: 'calendar', groceries: 'lists', stars: 'rewards' };
  const VIEWS = ['calendar', 'today', 'routines', 'meals', 'lists', 'rewards'];

  const $ = (s) => document.querySelector(s);
  const params = new URLSearchParams(location.search);
  const KIOSK = params.has('kiosk');
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (_) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (_) {} },
    del(k) { try { localStorage.removeItem(k); } catch (_) {} },
  };
  const savedView = LEGACY_VIEWS[store.get('view')] || store.get('view');

  const state = {
    familyId: params.get('family') || store.get('familyId'),
    family: { name: '', members: [], reward: null, weather: null, pinHash: '', sleep: null, saver: null },
    tasks: [], chores: [], completions: {}, meals: {}, groceries: [], events: [],
    rewards: [], redemptions: [], lists: [], listItems: [], countdowns: [], recipes: [], photos: [],
    weather: null,
    view: KIOSK ? 'today' : (VIEWS.includes(savedView) ? savedView : 'calendar'),
    calMode: ['week', 'month', 'schedule'].includes(store.get('calMode')) ? store.get('calMode') : 'week',
    routinePeriod: null, activeList: store.get('activeList') || 'groceries',
    filter: 'all', offset: 0, lastDay: '', redeeming: null, editingGoal: false,
  };
  let db = null;
  let unsubs = [];

  // ---------- Helpers ----------
  const pad = (n) => String(n).padStart(2, '0');
  const dayKey = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const parseKey = (k) => { const [y, m, d] = k.split('-').map(Number); return new Date(y, m - 1, d); };
  const today0 = () => { const d = new Date(); d.setHours(0, 0, 0, 0); return d; };
  const addDays = (d, n) => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };
  const mondayOf = (d) => addDays(d, -((d.getDay() + 6) % 7));
  const weekKeys = (start) => [...Array(7)].map((_, i) => dayKey(addDays(start, i)));
  const daysBetween = (a, b) => Math.round((b - a) / 864e5);
  const nowHM = () => { const d = new Date(); return `${pad(d.getHours())}:${pad(d.getMinutes())}`; };
  const fmtTime = (t) => {
    if (!t) return '';
    const [h, m] = t.split(':').map(Number);
    const d = new Date(); d.setHours(h, m, 0, 0);
    return d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
  };
  const fmtDay = (d, opts = { weekday: 'short', month: 'short', day: 'numeric' }) => d.toLocaleDateString(undefined, opts);
  const pick = (arr) => arr[Math.floor(Math.random() * arr.length)];
  const safeColor = (c, fallback = 'var(--line)') => (/^#[0-9a-fA-F]{6}$/.test(c || '') ? c : fallback);
  const currentPeriod = () => { const h = new Date().getHours(); return h < 12 ? 'morning' : h < 17 ? 'afternoon' : 'evening'; };

  function el(tag, props = {}, ...kids) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(props)) {
      if (v == null || v === false) continue;
      if (k === 'class') n.className = v;
      else if (k === 'text') n.textContent = v;
      else if (k === 'style') n.style.cssText = v;
      else if (k.startsWith('on')) n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v === true ? '' : v);
    }
    for (const c of kids.flat()) if (c != null && c !== false) n.append(c);
    return n;
  }
  const btn = (text, onclick, cls = 'btn soft small', extra = {}) => el('button', { class: cls, type: 'button', text, onclick, ...extra });

  const famRef = () => db.collection('families').doc(state.familyId);
  const col = (name) => famRef().collection(name);

  function normMembers(raw) {
    return (raw || []).map((m, i) => typeof m === 'string'
      ? { id: m, name: m, emoji: EMOJI[i % EMOJI.length], color: PALETTE[i % PALETTE.length] }
      : m);
  }
  const memberById = (id) => state.family.members.find((m) => m.id === id);
  const memberIdFromTask = (t) => t.memberId || (state.family.members.find((m) => m.name === t.member) || {}).id || '';
  const avatar = (m, size = '') => el('span', { class: 'avatar ' + size, style: `--c:${m ? safeColor(m.color) : 'var(--line)'}`, 'aria-hidden': 'true', text: m ? m.emoji : '🙂' });

  function toast(msg) {
    const t = $('#toast');
    t.textContent = msg;
    t.classList.add('show');
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => t.classList.remove('show'), 2800);
  }
  function showError(msg) { const e = $('#error'); e.textContent = msg || ''; e.hidden = !msg; }
  const fail = (e) => { console.error(e); showError('That change did not save. Check your internet connection and try again.'); };

  // ---------- Items: one-off tasks, repeating chores/routines, own events, Google events ----------
  function repeatsOn(c, dow) {
    if (c.repeat === 'daily') return true;
    if (c.repeat === 'weekdays') return dow >= 1 && dow <= 5;
    if (c.repeat === 'weekly') return (c.days || []).includes(dow);
    return false;
  }
  const taskToItem = (t) => {
    const ev = t.type === 'event';
    return { kind: ev ? 'myevent' : 'task', src: 'tasks', id: t.id, title: t.title, memberId: memberIdFromTask(t), time: t.time || '',
      endTime: t.endTime || '', points: ev ? 0 : Number(t.points) || 1, done: !ev && !!t.done, date: t.date, routine: '' };
  };
  const choreToItem = (c, key) => {
    const ev = c.type === 'event'; const cid = `${c.id}_${key}`;
    return { kind: ev ? 'myevent' : 'chore', src: 'chores', id: c.id, cid, title: c.title, memberId: c.memberId, time: c.time || '',
      endTime: c.endTime || '', points: ev ? 0 : Number(c.points) || 1, done: !ev && !!(state.completions[cid] && state.completions[cid].done),
      date: key, repeat: c.repeat, routine: c.routine || '' };
  };
  const isTodo = (i) => i.kind === 'task' || i.kind === 'chore';
  const sortTime = (i) => (i.allDay ? '00:00' : i.time || '99');

  // mode 'board': everything except routine chores; 'routines': routine chores only.
  function itemsFor(key, memberFilter = state.filter, mode = 'board') {
    const dow = parseKey(key).getDay();
    let out = [];
    if (mode === 'board') {
      out.push(...state.tasks.filter((t) => t.date === key).map(taskToItem));
      out.push(...state.events.filter((e) => e.date === key).map((e) => ({
        kind: 'event', id: e.id, title: e.title, memberId: e.memberId, time: e.time || '', endTime: e.endTime || '',
        allDay: !!e.allDay, points: 0, done: false, date: key,
      })));
    }
    out.push(...state.chores
      .filter((c) => (!c.start || c.start <= key) && repeatsOn(c, dow) && (mode === 'routines' ? !!c.routine : !c.routine))
      .map((c) => choreToItem(c, key)));
    return out
      .filter((i) => memberFilter === 'all' || i.memberId === memberFilter)
      .sort((a, b) => (a.done - b.done) || (sortTime(a) < sortTime(b) ? -1 : sortTime(a) > sortTime(b) ? 1 : 0) || String(a.title).localeCompare(String(b.title)));
  }

  // Stars: weekly points (leaderboard, family goal), all-time balance (reward shop), and streaks.
  function scoreboard() {
    const keys = new Set(weekKeys(mondayOf(today0())));
    const week = {}; const earned = {}; const spent = {}; const doneDays = {};
    const add = (memberId, points, date) => {
      if (!memberId) return;
      (doneDays[memberId] = doneDays[memberId] || new Set()).add(date);
      earned[memberId] = (earned[memberId] || 0) + points;
      if (keys.has(date)) week[memberId] = (week[memberId] || 0) + points;
    };
    for (const t of state.tasks) if (t.done && t.type !== 'event') add(memberIdFromTask(t), Number(t.points) || 1, t.date);
    for (const c of Object.values(state.completions)) if (c.done) add(c.memberId, Number(c.points) || 1, c.date);
    for (const r of state.redemptions) spent[r.memberId] = (spent[r.memberId] || 0) + (Number(r.cost) || 0);
    const streak = (id) => {
      const days = doneDays[id] || new Set();
      let d = today0();
      if (!days.has(dayKey(d))) d = addDays(d, -1);
      let n = 0;
      while (days.has(dayKey(d))) { n++; d = addDays(d, -1); }
      return n;
    };
    const rows = state.family.members.map((m) => ({
      m, points: week[m.id] || 0, streak: streak(m.id), balance: Math.max(0, (earned[m.id] || 0) - (spent[m.id] || 0)),
    })).sort((a, b) => b.points - a.points || b.streak - a.streak);
    return { rows, total: rows.reduce((s, r) => s + r.points, 0), balance: (id) => (rows.find((r) => r.m.id === id) || {}).balance || 0 };
  }

  // ---------- Parent PIN (kid lock) ----------
  let pinResolve = null;
  async function sha256(s) {
    const b = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(s));
    return [...new Uint8Array(b)].map((x) => x.toString(16).padStart(2, '0')).join('');
  }
  const pinKey = () => `pinOk:${state.familyId}`;
  const pinUnlocked = () => { try { return Number(sessionStorage.getItem(pinKey()) || 0) > Date.now(); } catch (_) { return false; } };
  function requirePin() {
    if (!state.family.pinHash || pinUnlocked()) return Promise.resolve(true);
    return new Promise((resolve) => {
      pinResolve = resolve;
      $('#pinInput').value = '';
      $('#pinMsg').textContent = '';
      $('#pinSheet').showModal();
      $('#pinInput').focus();
    });
  }
  async function submitPin(e) {
    e.preventDefault();
    const ok = (await sha256(`${state.familyId}:${$('#pinInput').value}`)) === state.family.pinHash;
    if (!ok) { $('#pinMsg').textContent = 'That PIN is not right. Try again.'; $('#pinInput').value = ''; return; }
    try { sessionStorage.setItem(pinKey(), String(Date.now() + 15 * 60000)); } catch (_) {}
    const r = pinResolve; pinResolve = null;
    $('#pinSheet').close();
    if (r) r(true);
  }

  // ---------- Writes ----------
  async function toggleItem(item, done, node) {
    try {
      if (item.kind === 'task') await col('tasks').doc(item.id).update({ done, doneAt: done ? Date.now() : null });
      else if (done) await col('completions').doc(item.cid).set({ done: true, choreId: item.id, memberId: item.memberId || '', points: item.points, date: item.date, at: Date.now() });
      else await col('completions').doc(item.cid).delete();
      if (!done) return;
      celebrate(item, node);
      // Finished everything for today (or this routine)? Throw a bigger party.
      if (item.date === dayKey(today0()) && item.memberId) {
        const same = (i) => i.id === item.id && (i.cid || '') === (item.cid || '');
        const pool = item.routine
          ? itemsFor(item.date, item.memberId, 'routines').filter((i) => i.routine === item.routine)
          : itemsFor(item.date, item.memberId, 'board');
        const left = pool.filter((i) => isTodo(i) && !i.done && !same(i));
        const m = memberById(item.memberId);
        if (!left.length && m) setTimeout(() => bigCelebrate(m, item.routine ? `🎉 ${m.name} finished the ${item.routine} routine!` : `🎉 ${m.name} finished everything today!`), 700);
      }
    } catch (e) { fail(e); }
  }

  async function deleteItem(item) {
    const msg = item.src === 'chores' ? `Remove "${item.title}" from every day?` : `Delete "${item.title}"?`;
    if (!confirm(msg)) return false;
    try { await col(item.src).doc(item.id).delete(); return true; } catch (e) { fail(e); return false; }
  }

  async function saveMembers(members) {
    try { await famRef().update({ members }); } catch (e) { fail(e); }
  }

  // ---------- Celebration ----------
  const confetti = { parts: [], running: false };
  function burst(x, y, colors, n = 70) {
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    for (let i = 0; i < n; i++) {
      const a = Math.random() * Math.PI * 2, s = 3 + Math.random() * 6;
      confetti.parts.push({ x, y, vx: Math.cos(a) * s, vy: Math.sin(a) * s - 4, r: 3 + Math.random() * 4, c: pick(colors), life: 60 + Math.random() * 30, rot: Math.random() * 6 });
    }
    if (!confetti.running) { confetti.running = true; requestAnimationFrame(drawConfetti); }
  }
  function celebrate(item, node) {
    const m = memberById(item.memberId);
    toast(`${pick(CHEERS)}${m ? ', ' + m.name : ''}! +${item.points} ★`);
    const r = node ? node.getBoundingClientRect() : { left: innerWidth / 2, top: innerHeight / 2, width: 0, height: 0 };
    burst(r.left + r.width / 2, r.top + r.height / 2, [m ? safeColor(m.color, '#FF8FA3') : '#FF8FA3', '#FFC857', '#7BD3B9', '#9C8CFF', '#FF5A7E']);
  }
  function bigCelebrate(m, msg) {
    toast(msg);
    const colors = [m ? safeColor(m.color, '#FF8FA3') : '#FF8FA3', '#FFC857', '#7BD3B9', '#9C8CFF', '#FF5A7E', '#6EC1FF'];
    [0.2, 0.5, 0.8].forEach((f, i) => setTimeout(() => burst(innerWidth * f, innerHeight * 0.35, colors, 90), i * 220));
  }
  function drawConfetti() {
    const cv = $('#confetti'); const ctx = cv.getContext('2d');
    if (cv.width !== innerWidth || cv.height !== innerHeight) { cv.width = innerWidth; cv.height = innerHeight; }
    ctx.clearRect(0, 0, cv.width, cv.height);
    confetti.parts = confetti.parts.filter((p) => p.life > 0);
    for (const p of confetti.parts) {
      p.vy += 0.25; p.x += p.vx; p.y += p.vy; p.life--; p.rot += 0.2;
      ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.rot); ctx.fillStyle = p.c;
      ctx.globalAlpha = Math.min(1, p.life / 30); ctx.fillRect(-p.r, -p.r / 2, p.r * 2, p.r); ctx.restore();
    }
    if (confetti.parts.length) requestAnimationFrame(drawConfetti);
    else { confetti.running = false; ctx.clearRect(0, 0, cv.width, cv.height); }
  }

  // ---------- Weather (Open-Meteo, free, no key) ----------
  const WMO = (c) => (c === 0 ? '☀️' : c <= 2 ? '🌤️' : c === 3 ? '☁️' : c <= 48 ? '🌫️' : c <= 57 ? '🌦️' : c <= 67 ? '🌧️' : c <= 77 ? '🌨️' : c <= 82 ? '🌧️' : c <= 86 ? '🌨️' : '⛈️');
  let weatherKey = '';
  async function loadWeather(force = false) {
    const w = state.family.weather;
    const k = w && w.lat != null ? `${w.lat},${w.lon},${w.unit}` : '';
    if (!k) { state.weather = null; weatherKey = ''; renderHeader(); return; }
    if (k === weatherKey && !force) return;
    weatherKey = k;
    try {
      const q = new URLSearchParams({ latitude: w.lat, longitude: w.lon, current: 'temperature_2m,weather_code',
        daily: 'weather_code,temperature_2m_max,temperature_2m_min', timezone: 'auto', forecast_days: '16',
        temperature_unit: w.unit === 'celsius' ? 'celsius' : 'fahrenheit' });
      const r = await fetch(`https://api.open-meteo.com/v1/forecast?${q}`);
      if (!r.ok) throw new Error(`weather ${r.status}`);
      const j = await r.json();
      const days = {};
      (j.daily.time || []).forEach((d, i) => { days[d] = { max: j.daily.temperature_2m_max[i], min: j.daily.temperature_2m_min[i], code: j.daily.weather_code[i] }; });
      state.weather = { temp: j.current.temperature_2m, code: j.current.weather_code, days };
      render();
    } catch (e) { console.warn('Weather unavailable', e); weatherKey = ''; }
  }
  const dayWeather = (key) => (state.weather && state.weather.days[key]) || null;

  // ---------- Countdowns ----------
  function upcomingCountdowns() {
    const t = today0();
    return state.countdowns.map((c) => {
      let d = parseKey(c.date);
      if (c.yearly) { d = new Date(t.getFullYear(), d.getMonth(), d.getDate()); if (d < t) d = new Date(t.getFullYear() + 1, d.getMonth(), d.getDate()); }
      return { ...c, next: d, days: daysBetween(t, d) };
    }).filter((c) => c.days >= 0).sort((a, b) => a.days - b.days);
  }
  function countdownStrip() {
    const list = upcomingCountdowns().slice(0, 4);
    if (!list.length && KIOSK) return null;
    return el('div', { class: 'countdowns' },
      list.map((c) => el('div', { class: 'cd' + (c.days === 0 ? ' is-today' : '') },
        el('span', { class: 'cd-emoji', 'aria-hidden': 'true', text: c.emoji || '🎉' }),
        el('div', {}, el('div', { class: 'cd-title', text: c.title }),
          el('div', { class: 'cd-days', text: c.days === 0 ? 'Today! 🎉' : c.days === 1 ? 'Tomorrow' : `in ${c.days} days` })))),
      btn(list.length ? '+ Countdown' : '⏳ Add a countdown (birthdays, trips…)', openCountdownSheet, 'btn soft small cd-add'));
  }

  // ---------- Cards ----------
  function itemBody(item, meta) {
    const editable = item.kind !== 'event';
    return editable
      ? el('button', { class: 'body', type: 'button', 'aria-label': `Edit ${item.title}`, onclick: () => openEditSheet(item) }, el('span', { class: 't', text: item.title }), meta)
      : el('div', { class: 'body' }, el('span', { class: 't', text: item.title }), meta);
  }

  function eventCard(item, { compact = false, showWho = true } = {}) {
    const m = memberById(item.memberId);
    const who = showWho && m && state.filter === 'all';
    const when = item.allDay ? 'All day' : item.time ? fmtTime(item.time) + (item.endTime && !compact ? ` – ${fmtTime(item.endTime)}` : '') : '';
    const meta = el('span', { class: 'meta' },
      who && compact ? el('span', { title: m.name, text: m.emoji }) : null,
      when ? el('span', { text: when }) : null,
      compact ? null : el('span', { text: item.kind === 'event' ? 'Google Calendar' : item.src === 'chores' ? '🔁 Event' : 'Event' }),
      who && !compact ? el('span', { text: `${m.emoji} ${m.name}` }) : null);
    return el('div', { class: 'item event' + (compact ? ' compact' : ''), style: `--c:${m ? safeColor(m.color) : 'var(--line)'}`, title: item.kind === 'event' ? 'From Google Calendar' : '' },
      el('span', { class: 'cal-icon', 'aria-hidden': 'true', text: '📅' }), itemBody(item, meta));
  }

  function itemCard(item, { compact = false, showWho = true } = {}) {
    if (!isTodo(item)) return eventCard(item, { compact, showWho });
    const m = memberById(item.memberId);
    const repeatName = { daily: 'Daily', weekdays: 'Weekdays', weekly: 'Weekly' }[item.repeat] || '';
    const node = el('div', { class: 'item' + (item.done ? ' done' : '') + (compact ? ' compact' : ''), style: `--c:${m ? safeColor(m.color) : 'var(--line)'}` });
    const check = el('button', {
      class: 'check', type: 'button', text: '✓', 'aria-pressed': String(item.done),
      'aria-label': `${item.done ? 'Mark not done' : 'Mark done'}: ${item.title}`,
      onclick: () => { node.classList.add('pop'); toggleItem(item, !item.done, node); },
    });
    const who = showWho && m && state.filter === 'all';
    const meta = el('span', { class: 'meta' },
      who && compact ? el('span', { title: m.name, text: m.emoji }) : null,
      item.time ? el('span', { text: (compact ? '' : '🕒 ') + fmtTime(item.time) }) : null,
      el('span', { class: 'stars', title: `${item.points} stars`, text: '★'.repeat(Math.min(item.points, 5)) }),
      item.kind === 'chore' && !item.routine ? el('span', { title: `Repeats: ${repeatName}`, text: compact ? '🔁' : `🔁 ${repeatName}` }) : null,
      who && !compact ? el('span', { text: `${m.emoji} ${m.name}` }) : null);
    node.append(check, itemBody(item, meta));
    return node;
  }

  // ---------- Header & chips ----------
  function renderHeader() {
    const now = new Date();
    const h = now.getHours();
    const hi = h < 5 ? 'Good night' : h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening';
    $('#greeting').textContent = `${hi}, ${state.family.name || 'family'}!`;
    $('#dateLine').textContent = now.toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' });
    const time = now.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
    $('#clock').textContent = time;
    $('#saverClock').textContent = time; $('#sleepClock').textContent = time;
    $('#saverDate').textContent = $('#dateLine').textContent;
    $('#weekStars').textContent = String(scoreboard().total);
    const wp = $('#weatherPill');
    wp.hidden = !state.weather;
    if (state.weather) {
      wp.textContent = `${WMO(state.weather.code)} ${Math.round(state.weather.temp)}°`;
      wp.title = state.family.weather ? `Weather in ${state.family.weather.name}` : '';
    }
    document.querySelectorAll('.tab').forEach((t) => t.setAttribute('aria-selected', String(t.dataset.view === state.view)));
  }

  function renderPeople() {
    const box = $('#people');
    const showChips = ['calendar', 'today', 'routines'].includes(state.view) && state.family.members.length > 0;
    box.hidden = !showChips;
    if (!showChips) return;
    const todayKey = dayKey(today0());
    const mode = state.view === 'routines' ? 'routines' : 'board';
    const left = (id) => itemsFor(todayKey, id, mode).filter((i) => isTodo(i) && !i.done).length;
    const chip = (id, label, m) => el('button', {
      class: 'chip', type: 'button', 'aria-pressed': String(state.filter === id),
      onclick: () => { state.filter = state.filter === id ? 'all' : id; render(); },
    }, m ? avatar(m) : el('span', { class: 'avatar', text: '👨‍👩‍👧' }), label, el('span', { class: 'count', title: 'Left today', text: String(left(id)) }));
    box.replaceChildren(chip('all', 'Everyone', null), ...state.family.members.map((m) => chip(m.id, m.name, m)));
  }

  function emptyFamily() {
    return el('div', { class: 'panel' },
      el('h2', { text: 'Who is in your family?' }),
      el('p', { class: 'muted', style: 'margin:0', text: 'Add each person with a fun avatar. Then add events, chores, routines, and dinners, and start earning stars.' }),
      el('div', {}, btn('Add family members', openSettings, 'btn')));
  }

  const seg = (options, current, onPick, label) => el('div', { class: 'seg', role: 'group', 'aria-label': label },
    options.map(([v, text]) => el('button', { type: 'button', 'aria-pressed': String(current === v), text, onclick: () => onPick(v) })));

  // ---------- Calendar: Week / Month / Schedule ----------
  function calendarNav(title) {
    const unit = state.calMode === 'month' ? 'month' : state.calMode === 'schedule' ? 'page' : 'week';
    return el('div', { class: 'weeknav' },
      seg([['week', 'Week'], ['month', 'Month'], ['schedule', 'Schedule']], state.calMode,
        (v) => { state.calMode = v; state.offset = 0; store.set('calMode', v); render(); }, 'Calendar view'),
      el('h2', { text: title }),
      btn('‹', () => { state.offset--; render(); }, 'btn soft small', { 'aria-label': `Previous ${unit}` }),
      btn('Today', () => { state.offset = 0; render(); }, 'btn soft small', { disabled: state.offset === 0 ? true : null }),
      btn('›', () => { state.offset++; render(); }, 'btn soft small', { 'aria-label': `Next ${unit}` }));
  }

  function weatherTag(key) {
    const w = dayWeather(key);
    return w ? el('span', { class: 'wx', title: 'Forecast', text: `${WMO(w.code)} ${Math.round(w.max)}°/${Math.round(w.min)}°` }) : null;
  }

  function renderWeek() {
    const start = addDays(mondayOf(today0()), state.offset * 7);
    const todayKey = dayKey(today0());
    const end = addDays(start, 6);
    const compact = !matchMedia('(max-width: 1000px)').matches;
    const days = weekKeys(start).map((key) => {
      const d = parseKey(key);
      const items = itemsFor(key);
      const dinner = (state.meals[key] || {}).dinner;
      return el('section', { class: 'day' + (key === todayKey ? ' is-today' : '') + (key < todayKey ? ' is-past' : ''), 'aria-label': d.toDateString() },
        el('div', { class: 'day-head' },
          el('span', { class: 'num', text: String(d.getDate()) }),
          el('span', { class: 'name', text: DOW[d.getDay()] }),
          key === todayKey ? el('span', { class: 'today-tag', text: 'Today' }) : null,
          el('button', { class: 'plus', type: 'button', text: '+', 'aria-label': `Add on ${d.toDateString()}`, onclick: () => openTaskSheet(key) })),
        weatherTag(key),
        el('button', { class: 'meal' + (dinner ? ' set' : ''), type: 'button', onclick: () => openMealSheet(key) }, '🍽️ ', dinner || 'Add dinner'),
        ...(items.length ? items.map((i) => itemCard(i, { compact })) : [el('p', { class: 'free', text: 'Free day ✨' })]));
    });
    return el('div', { class: 'stack' }, countdownStrip(),
      calendarNav(`${fmtDay(start, { month: 'short', day: 'numeric' })} – ${fmtDay(end, { month: 'short', day: 'numeric' })}`),
      el('div', { class: 'week' }, days));
  }

  function renderMonth() {
    const t = today0();
    const first = new Date(t.getFullYear(), t.getMonth() + state.offset, 1);
    const last = new Date(first.getFullYear(), first.getMonth() + 1, 0);
    const start = mondayOf(first);
    const end = addDays(mondayOf(last), 6);
    const todayKey = dayKey(t);
    const cells = [];
    for (let d = start; d <= end; d = addDays(d, 1)) {
      const key = dayKey(d);
      const items = itemsFor(key);
      const w = dayWeather(key);
      cells.push(el('button', {
        class: 'mcell' + (d.getMonth() !== first.getMonth() ? ' out' : '') + (key === todayKey ? ' is-today' : ''), type: 'button',
        'aria-label': `${d.toDateString()}: ${items.length} item${items.length === 1 ? '' : 's'}. Open week.`,
        onclick: () => { state.calMode = 'week'; store.set('calMode', 'week'); state.offset = daysBetween(mondayOf(t), mondayOf(d)) / 7; render(); },
      },
      el('span', { class: 'mhead' }, el('span', { class: 'mnum', text: String(d.getDate()) }), w ? el('span', { class: 'mwx', text: WMO(w.code) }) : null),
      ...items.slice(0, 3).map((i) => {
        const m = memberById(i.memberId);
        return el('span', { class: 'mi' + (i.done ? ' done' : '') + (isTodo(i) ? '' : ' ev'), style: `--c:${m ? safeColor(m.color) : 'var(--line)'}` },
          i.time && !i.allDay ? el('b', { text: fmtTime(i.time).replace(':00', '') + ' ' }) : null, i.title);
      }),
      items.length > 3 ? el('span', { class: 'more', text: `+${items.length - 3} more` }) : null));
    }
    return el('div', { class: 'stack' }, countdownStrip(),
      calendarNav(fmtDay(first, { month: 'long', year: 'numeric' })),
      el('div', { class: 'month' }, ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map((n) => el('div', { class: 'mdow', text: n })), cells));
  }

  function renderSchedule() {
    const start = addDays(today0(), state.offset * 21);
    const todayKey = dayKey(today0());
    const groups = [];
    for (let i = 0; i < 21; i++) {
      const d = addDays(start, i);
      const key = dayKey(d);
      const items = itemsFor(key);
      const dinner = (state.meals[key] || {}).dinner;
      if (!items.length && !dinner) continue;
      groups.push(el('section', { class: 'sched-day' + (key === todayKey ? ' is-today' : '') },
        el('div', { class: 'sched-head' },
          el('h3', { text: key === todayKey ? `Today · ${fmtDay(d)}` : fmtDay(d, { weekday: 'long', month: 'short', day: 'numeric' }) }),
          weatherTag(key),
          dinner ? el('span', { class: 'sched-meal', text: `🍽️ ${dinner}` }) : null),
        el('div', { class: 'sched-items' }, items.map((x) => itemCard(x)))));
    }
    const end = addDays(start, 20);
    return el('div', { class: 'stack' }, countdownStrip(),
      calendarNav(`${fmtDay(start, { month: 'short', day: 'numeric' })} – ${fmtDay(end, { month: 'short', day: 'numeric' })}`),
      groups.length ? el('div', { class: 'schedule' }, groups) : el('div', { class: 'panel' }, el('p', { class: 'muted', style: 'margin:0', text: 'Nothing scheduled in these three weeks. Tap + to add something.' })));
  }

  const renderCalendar = () => (state.calMode === 'month' ? renderMonth() : state.calMode === 'schedule' ? renderSchedule() : renderWeek());

  function ring(done, total, color) {
    color = safeColor(color, '#9C8CFF');
    const r = 20, c = 2 * Math.PI * r, f = total ? done / total : 0;
    const box = el('div', { class: 'ring', title: `${done} of ${total} done` });
    box.innerHTML = `<svg width="48" height="48" viewBox="0 0 48 48" aria-hidden="true"><circle cx="24" cy="24" r="${r}" fill="none" stroke="var(--line)" stroke-width="6"/><circle cx="24" cy="24" r="${r}" fill="none" stroke="${color}" stroke-width="6" stroke-linecap="round" stroke-dasharray="${c}" stroke-dashoffset="${c * (1 - f)}"/></svg>`;
    box.append(el('span', { text: `${done}/${total}` }));
    return box;
  }

  function personColumn(m, items, emptyText, doneText) {
    const todos = items.filter(isTodo);
    const done = todos.filter((i) => i.done).length;
    return el('section', { class: 'person-col', style: `--c:${safeColor(m.color)}` },
      el('div', { class: 'person-head' }, avatar(m, 'lg'),
        el('div', {}, el('h3', { text: m.name }), el('div', { class: 'sub', text: todos.length ? (done === todos.length ? doneText : `${todos.length - done} to go`) : items.length ? 'No chores today' : 'Nothing today' })),
        ring(done, todos.length, m.color)),
      ...(items.length ? items.map((i) => itemCard(i, { showWho: false })) : [el('p', { class: 'free', text: emptyText })]));
  }

  // ---------- Chores (Today) ----------
  function renderToday() {
    const key = dayKey(today0());
    const meals = state.meals[key] || {};
    const people = state.filter === 'all' ? state.family.members : state.family.members.filter((m) => m.id === state.filter);
    const cols = people.map((m) => personColumn(m, itemsFor(key, m.id), 'Free as a bird 🐦', 'All done! 🎉'));
    const unassigned = itemsFor(key, 'all').filter((i) => !memberById(i.memberId));
    if (unassigned.length && state.filter === 'all') {
      cols.push(el('section', { class: 'person-col' }, el('div', { class: 'person-head' }, el('span', { class: 'avatar lg', text: '🙌' }), el('h3', { text: 'Anyone' })), ...unassigned.map((i) => itemCard(i))));
    }
    const mealLine = MEALS.filter(([k]) => meals[k]).map(([k, e]) => `${e} ${meals[k]}`).join('   ·   ');
    const top = el('div', { class: 'tonight' },
      el('span', { class: 'big', 'aria-hidden': 'true', text: '🍽️' }),
      el('div', { style: 'flex:1;min-width:0' }, el('div', { class: 'lbl', text: "Today's meals" }), el('div', { text: mealLine || 'No meals planned yet' })),
      btn(mealLine ? 'Change' : 'Plan meals', () => openMealSheet(key)));
    return el('div', { class: 'stack' }, countdownStrip(), top, el('div', { class: 'today-grid' }, cols));
  }

  // ---------- Routines ----------
  function renderRoutines() {
    const key = dayKey(today0());
    const period = state.routinePeriod || currentPeriod();
    const people = state.filter === 'all' ? state.family.members : state.family.members.filter((m) => m.id === state.filter);
    const all = itemsFor(key, 'all', 'routines');
    const label = PERIODS.find((p) => p[0] === period);
    const head = el('div', { class: 'weeknav' },
      seg(PERIODS.map(([v, e, n]) => [v, `${e} ${n}`]), period, (v) => { state.routinePeriod = v; render(); }, 'Routine time'),
      el('h2', { text: `${label[2]} routine` }),
      btn('+ Add a routine step', () => openTaskSheet(key, { routine: period })));
    if (!state.chores.some((c) => c.routine)) {
      return el('div', { class: 'stack' }, head, el('div', { class: 'panel' },
        el('h2', { text: 'Build healthy habits' }),
        el('p', { class: 'muted', style: 'margin:0', text: 'Routines are steps that repeat at the same time of day, like brush teeth, make bed, or pack the backpack. Each step earns stars, and finishing a routine sets off a party.' }),
        el('div', {}, btn(`Add a ${label[2].toLowerCase()} routine step`, () => openTaskSheet(key, { routine: period }), 'btn'))));
    }
    const cols = people.map((m) => personColumn(m, all.filter((i) => i.memberId === m.id && i.routine === period), 'No steps for this time', 'Routine done! 🎉'));
    return el('div', { class: 'stack' }, head, el('div', { class: 'today-grid' }, cols));
  }

  // ---------- Meals ----------
  function renderMeals() {
    const start = addDays(mondayOf(today0()), state.offset * 7);
    const todayKey = dayKey(today0());
    const rows = weekKeys(start).map((key) => {
      const d = parseKey(key);
      const meals = state.meals[key] || {};
      return el('div', { class: 'meal-row' + (key === todayKey ? ' is-today' : '') },
        el('span', { class: 'd', text: fmtDay(d, { weekday: 'short', day: 'numeric' }) }),
        ...MEALS.map(([type, emoji, name]) => {
          const input = el('input', { id: `meal-${key}-${type}`, maxlength: '60', placeholder: `${emoji} ${name}`, 'aria-label': `${name} on ${d.toDateString()}`, list: `favs-${type}` });
          input.value = meals[type] || '';
          input.addEventListener('change', () => saveMealField(key, type, input.value));
          return input;
        }));
    });
    const datalists = MEALS.map(([type]) => el('datalist', { id: `favs-${type}` }, state.recipes.filter((r) => r.type === type).map((r) => el('option', { value: r.title }))));
    const favType = el('select', { id: 'favType', 'aria-label': 'Meal type' }, MEALS.map(([v, e, n]) => el('option', { value: v, text: `${e} ${n}` })));
    favType.value = 'dinner';
    const favInput = el('input', { id: 'favInput', maxlength: '60', placeholder: 'Mac and cheese, pancakes…', 'aria-label': 'Favorite meal' });
    const favs = el('div', { class: 'panel' }, el('h2', { text: '⭐ Family favorites' }),
      el('p', { class: 'muted', style: 'margin:0', text: 'Saved favorites pop up as suggestions when you type a meal.' }),
      el('form', { class: 'row', autocomplete: 'off', onsubmit: async (e) => {
        e.preventDefault();
        const v = favInput.value.trim(); if (!v) return;
        favInput.value = '';
        try { await col('recipes').add({ title: v, type: favType.value, createdAt: Date.now() }); toast('Saved to favorites ⭐'); } catch (err) { fail(err); }
      } }, favInput, favType, el('button', { class: 'btn', type: 'submit', text: 'Save' })),
      el('div', { class: 'fav-chips' }, state.recipes.length ? [...state.recipes].sort((a, b) => a.title.localeCompare(b.title)).map((r) => el('span', { class: 'fav' },
        `${(MEALS.find((x) => x[0] === r.type) || MEALS[2])[1]} ${r.title}`,
        el('button', { type: 'button', text: '✕', 'aria-label': `Remove ${r.title}`, onclick: () => col('recipes').doc(r.id).delete().catch(fail) })))
        : el('span', { class: 'muted', text: 'No favorites yet.' })));
    return el('div', { class: 'stack' },
      el('div', { class: 'panel' },
        el('div', { class: 'weeknav' }, el('h2', { text: `🍽️ Meal plan · ${fmtDay(start, { month: 'short', day: 'numeric' })}` }),
          btn('‹', () => { state.offset--; render(); }, 'btn soft small', { 'aria-label': 'Previous week' }),
          btn('This week', () => { state.offset = 0; render(); }, 'btn soft small', { disabled: state.offset === 0 ? true : null }),
          btn('›', () => { state.offset++; render(); }, 'btn soft small', { 'aria-label': 'Next week' })),
        el('div', { class: 'meal-row meal-head', 'aria-hidden': 'true' }, el('span'), ...MEALS.map(([, e, n]) => el('span', { text: `${e} ${n}` }))),
        ...rows, datalists),
      favs);
  }

  // ---------- Lists ----------
  function renderLists() {
    const lists = [{ id: 'groceries', title: 'Groceries', emoji: '🛒', color: '#7BD3B9', builtin: true },
      ...[...state.lists].sort((a, b) => (a.createdAt || 0) - (b.createdAt || 0))];
    if (!lists.some((l) => l.id === state.activeList)) state.activeList = 'groceries';
    const active = lists.find((l) => l.id === state.activeList);
    const isG = active.id === 'groceries';
    const itemsOf = (id) => (id === 'groceries' ? state.groceries : state.listItems.filter((i) => i.listId === id));
    const ref = (id) => (isG ? col('groceries') : col('listItems')).doc(id);
    const chips = el('div', { class: 'list-chips' }, lists.map((l) => el('button', {
      class: 'list-chip', type: 'button', 'aria-pressed': String(l.id === active.id), style: `--c:${safeColor(l.color)}`,
      onclick: () => { state.activeList = l.id; store.set('activeList', l.id); render(); },
    }, `${l.emoji || '📝'} ${l.title}`, el('span', { class: 'count', text: String(itemsOf(l.id).filter((i) => !i.done).length) }))));
    const items = [...itemsOf(active.id)].sort((a, b) => (a.done - b.done) || ((a.createdAt || 0) - (b.createdAt || 0)));
    const input = el('input', { id: 'listInput', maxlength: '80', placeholder: isG ? 'Milk, bananas, birthday candles…' : `Add to ${active.title}…`, 'aria-label': `Add to ${active.title}` });
    const form = el('form', { class: 'row', autocomplete: 'off', onsubmit: async (e) => {
      e.preventDefault();
      const v = input.value.trim(); if (!v) return;
      input.value = '';
      try {
        if (isG) await col('groceries').add({ title: v, done: false, createdAt: Date.now() });
        else await col('listItems').add({ listId: active.id, title: v, done: false, createdAt: Date.now() });
      } catch (err) { fail(err); }
      document.getElementById('listInput')?.focus();
    } }, input, el('button', { class: 'btn', type: 'submit', text: 'Add' }));
    const rows = items.map((g) => el('div', { class: 'groc' + (g.done ? ' done' : '') },
      el('button', { class: 'check', type: 'button', text: '✓', style: g.done ? `background:${safeColor(active.color, 'var(--mint)')};color:#fff;border-color:transparent` : '',
        'aria-label': `${g.done ? 'Uncheck' : 'Check'} ${g.title}`, onclick: () => ref(g.id).update({ done: !g.done }).catch(fail) }),
      el('span', { class: 't', text: g.title }),
      btn('✕', () => ref(g.id).delete().catch(fail), 'del btn soft small', { 'aria-label': `Remove ${g.title}` })));
    const doneCount = items.filter((g) => g.done).length;
    const newName = el('input', { id: 'newListName', maxlength: '30', placeholder: 'New list: Packing, To-do, Gifts…', 'aria-label': 'New list name' });
    const newForm = el('form', { class: 'row', autocomplete: 'off', onsubmit: async (e) => {
      e.preventDefault();
      const v = newName.value.trim(); if (!v) return;
      newName.value = '';
      const used = new Set(state.lists.map((l) => l.color));
      const color = PALETTE.find((c) => !used.has(c)) || pick(PALETTE);
      const emoji = /pack|trip|travel/i.test(v) ? '🧳' : /gift|birthday/i.test(v) ? '🎁' : /school/i.test(v) ? '🎒' : /todo|to-do|to do/i.test(v) ? '☑️' : '📝';
      try { const r = await col('lists').add({ title: v, emoji, color, createdAt: Date.now() }); state.activeList = r.id; store.set('activeList', r.id); render(); } catch (err) { fail(err); }
    } }, newName, el('button', { class: 'btn soft', type: 'submit', text: 'Create list' }));
    return el('div', { class: 'stack' }, chips,
      el('div', { class: 'panel', style: `border-top:6px solid ${safeColor(active.color)}` },
        el('div', { class: 'weeknav' }, el('h2', { text: `${active.emoji || '📝'} ${active.title}` }),
          active.builtin ? null : btn('Delete list', async () => {
            if (!confirm(`Delete the "${active.title}" list and everything on it?`)) return;
            try {
              const batch = db.batch();
              itemsOf(active.id).forEach((i) => batch.delete(col('listItems').doc(i.id)));
              batch.delete(col('lists').doc(active.id));
              await batch.commit();
              state.activeList = 'groceries'; store.set('activeList', 'groceries'); render();
            } catch (err) { fail(err); }
          }, 'btn danger small')),
        form,
        rows.length ? el('div', {}, rows) : el('p', { class: 'muted', text: isG ? 'The list is empty. Add what you need and check things off in the store.' : 'Nothing here yet.' }),
        doneCount ? el('div', {}, btn(`Clear ${doneCount} checked`, async () => {
          try { const batch = db.batch(); items.filter((x) => x.done).forEach((x) => batch.delete(ref(x.id))); await batch.commit(); } catch (e) { fail(e); }
        })) : null),
      el('div', { class: 'panel' }, el('h2', { text: '➕ New list' }), newForm));
  }

  // ---------- Rewards ----------
  function renderRewards() {
    const sb = scoreboard();
    const medals = ['🥇', '🥈', '🥉'];
    const board = el('div', { class: 'panel' }, el('h2', { text: '⭐ This week’s stars' }),
      sb.rows.length ? sb.rows.map((r, i) => el('div', { class: 'leader' },
        el('span', { class: 'rank', text: r.points > 0 ? (medals[i] || String(i + 1)) : String(i + 1) }),
        avatar(r.m),
        el('div', {}, el('div', { class: 'name', text: r.m.name }),
          el('div', { class: 'streak', text: `${r.streak ? `🔥 ${r.streak}-day streak` : 'Start a streak today'} · 🏦 ${r.balance} to spend` })),
        el('span', { class: 'pts', text: `${r.points} ★` })))
        : el('p', { class: 'muted', text: 'Add family members to start earning stars.' }),
      el('p', { class: 'muted', style: 'margin:0;font-size:.9rem', text: 'Weekly stars reset every Monday. Stars to spend keep adding up until someone cashes them in at the reward shop.' }));

    const reward = state.family.reward;
    const goal = reward && Number(reward.stars) > 0 ? Number(reward.stars) : 0;
    const pct = goal ? Math.min(100, Math.round((sb.total / goal) * 100)) : 0;
    let goalBody;
    if (state.editingGoal) {
      const gt = el('input', { id: 'goalTitle', maxlength: '40', placeholder: 'Pizza & movie night', 'aria-label': 'Family reward' });
      const gs = el('input', { id: 'goalStars', type: 'number', min: '1', max: '999', placeholder: '40', 'aria-label': 'Stars needed' });
      gt.value = (reward && reward.title) || ''; gs.value = goal || '';
      goalBody = [el('div', { class: 'grid2' }, gt, gs), el('div', { class: 'row' },
        btn('Save goal', async () => {
          const stars = Math.max(0, Math.min(999, parseInt(gs.value, 10) || 0));
          try { await famRef().update({ reward: stars ? { title: gt.value.trim(), stars } : null }); state.editingGoal = false; toast('Goal saved 🎁'); render(); } catch (e) { fail(e); }
        }, 'btn small'),
        btn('Cancel', () => { state.editingGoal = false; render(); }))];
    } else {
      goalBody = goal
        ? [el('div', { class: 'goal-title', text: reward.title || 'Family treat' }),
          el('div', { class: 'bar', role: 'progressbar', 'aria-valuemin': '0', 'aria-valuemax': String(goal), 'aria-valuenow': String(Math.min(sb.total, goal)) }, el('i', { style: `width:${pct}%` })),
          el('p', { style: 'margin:0;font-weight:800', text: sb.total >= goal ? `Unlocked! ${sb.total} of ${goal} stars 🎉` : `${sb.total} of ${goal} stars · ${goal - sb.total} to go` })]
        : [el('p', { class: 'muted', style: 'margin:0', text: 'A treat the whole family works toward together each week, like a movie night or an ice cream trip.' })];
      goalBody.push(el('div', {}, btn(goal ? 'Edit goal' : 'Set a family goal', async () => { if (await requirePin()) { state.editingGoal = true; render(); } })));
    }
    const goalPanel = el('div', { class: 'panel' }, el('h2', { text: '🎁 Family goal this week' }), goalBody);

    const shopCards = [...state.rewards].sort((a, b) => (a.cost || 0) - (b.cost || 0)).map((r) => {
      const open = state.redeeming === r.id;
      return el('div', { class: 'reward' + (open ? ' open' : '') },
        el('div', { class: 'reward-emoji', 'aria-hidden': 'true', text: r.emoji || '🎁' }),
        el('div', { class: 'reward-title', text: r.title }),
        el('div', { class: 'reward-cost', text: `${r.cost} ★` }),
        open
          ? el('div', { class: 'redeem-for' }, el('span', { class: 'muted', text: 'Who is cashing in?' }),
            state.family.members.map((m) => {
              const can = sb.balance(m.id) >= r.cost;
              return el('button', { type: 'button', class: 'who-btn', disabled: can ? null : true, title: can ? '' : `${m.name} has ${sb.balance(m.id)} ★`,
                onclick: () => redeem(r, m) }, avatar(m, 'sm'), `${m.name} (${sb.balance(m.id)})`);
            }),
            btn('Cancel', () => { state.redeeming = null; render(); }))
          : el('div', { class: 'row' }, btn('Redeem', () => { state.redeeming = r.id; render(); }, 'btn small'),
            btn('✕', async () => { if (await requirePin() && confirm(`Remove "${r.title}" from the shop?`)) col('rewards').doc(r.id).delete().catch(fail); }, 'btn soft small', { 'aria-label': `Remove ${r.title}` })));
    });
    const rEmoji = el('input', { id: 'rwEmoji', maxlength: '4', value: '🍦', 'aria-label': 'Reward emoji', style: 'flex:0 0 64px;text-align:center' });
    const rTitle = el('input', { id: 'rwTitle', maxlength: '40', placeholder: 'Ice cream trip, 30 min screen time…', 'aria-label': 'Reward' });
    const rCost = el('input', { id: 'rwCost', type: 'number', min: '1', max: '999', placeholder: 'Stars', 'aria-label': 'Star cost', style: 'flex:0 0 100px' });
    const addForm = el('form', { class: 'row', autocomplete: 'off', onsubmit: async (e) => {
      e.preventDefault();
      const title = rTitle.value.trim(); const cost = Math.max(1, Math.min(999, parseInt(rCost.value, 10) || 0));
      if (!title || !parseInt(rCost.value, 10)) { toast('Add a name and a star cost'); return; }
      if (!(await requirePin())) return;
      try { await col('rewards').add({ title, cost, emoji: rEmoji.value.trim() || '🎁', createdAt: Date.now() }); rTitle.value = ''; rCost.value = ''; toast('Reward added to the shop 🛍️'); } catch (err) { fail(err); }
    } }, rEmoji, rTitle, rCost, el('button', { class: 'btn', type: 'submit', text: 'Add reward' }));
    const shop = el('div', { class: 'panel' }, el('h2', { text: '🛍️ Reward shop' }),
      shopCards.length ? el('div', { class: 'shop' }, shopCards) : el('p', { class: 'muted', style: 'margin:0', text: 'No rewards yet. Add treats kids can buy with their stars.' }),
      addForm);
    const hist = [...state.redemptions].sort((a, b) => (b.at || 0) - (a.at || 0)).slice(0, 8);
    const history = hist.length ? el('div', { class: 'panel' }, el('h2', { text: '🧾 Recently redeemed' }),
      hist.map((h) => {
        const m = memberById(h.memberId);
        return el('div', { class: 'member-row' }, avatar(m, 'sm'),
          el('span', { class: 'n', text: `${m ? m.name : 'Someone'} got ${h.emoji || '🎁'} ${h.title}` }),
          el('span', { class: 'muted', text: `${h.cost} ★ · ${fmtDay(new Date(h.at || Date.now()), { month: 'short', day: 'numeric' })}` }));
      })) : null;
    return el('div', { class: 'stack' }, el('div', { class: 'two' }, board, goalPanel), shop, history);
  }

  async function redeem(r, m) {
    if (!(await requirePin())) return;
    const sb = scoreboard();
    if (sb.balance(m.id) < r.cost) { toast(`${m.name} needs ${r.cost - sb.balance(m.id)} more stars`); return; }
    try {
      await col('redemptions').add({ rewardId: r.id, title: r.title, emoji: r.emoji || '🎁', cost: r.cost, memberId: m.id, at: Date.now(), date: dayKey(today0()) });
      state.redeeming = null;
      bigCelebrate(m, `🎁 ${m.name} cashed in ${r.cost} ★ for ${r.title}!`);
    } catch (e) { fail(e); }
  }

  // ---------- Render ----------
  function render() {
    state.lastDay = dayKey(today0());
    renderHeader();
    renderPeople();
    renderSyncBtn();
    const hasMembers = state.family.members.length > 0;
    $('#fab').hidden = !hasMembers || !['calendar', 'today', 'routines'].includes(state.view);
    let view;
    if (!hasMembers && ['calendar', 'today', 'routines', 'rewards'].includes(state.view)) view = emptyFamily();
    else if (state.view === 'today') view = renderToday();
    else if (state.view === 'routines') view = renderRoutines();
    else if (state.view === 'meals') view = renderMeals();
    else if (state.view === 'lists') view = renderLists();
    else if (state.view === 'rewards') view = renderRewards();
    else view = renderCalendar();
    // Live updates re-render the view: keep focus and any half-typed text in inputs.
    const a = document.activeElement;
    const keep = a && a.id && a.tagName === 'INPUT' && a.closest('#view') ? { id: a.id, value: a.value, pos: a.selectionStart } : null;
    $('#view').replaceChildren(view);
    if (keep) {
      const n = document.getElementById(keep.id);
      if (n) { n.value = keep.value; n.focus(); try { n.setSelectionRange(keep.pos, keep.pos); } catch (_) {} }
    }
    if ($('#settingsSheet').open) renderSettings();
    if ($('#countdownSheet').open) drawCountdownList();
  }

  // ---------- Task / event sheet ----------
  const sheetState = { type: 'chore', who: [], stars: 1, days: [], edit: null };
  function closeOnBackdrop(dlg) {
    dlg.addEventListener('click', (e) => { if (e.target === dlg) dlg.close(); });
    dlg.querySelectorAll('[data-close]').forEach((b) => b.addEventListener('click', () => dlg.close()));
  }

  function openTaskSheet(key, opts = {}) {
    key = key || dayKey(today0());
    Object.assign(sheetState, {
      type: opts.type || 'chore', edit: null, stars: 1, days: [parseKey(key).getDay()],
      who: state.filter !== 'all' ? [state.filter] : [],
    });
    $('#tTitle').value = '';
    $('#tDate').value = key;
    $('#tTime').value = '';
    $('#tEnd').value = '';
    $('#tRepeat').value = opts.routine ? 'daily' : 'none';
    $('#tRoutine').value = opts.routine || '';
    drawTaskSheet();
    $('#taskSheet').showModal();
    $('#tTitle').focus();
  }

  function openEditSheet(item) {
    const doc = (item.src === 'tasks' ? state.tasks : state.chores).find((x) => x.id === item.id);
    if (!doc) return;
    Object.assign(sheetState, {
      type: doc.type === 'event' ? 'event' : 'chore', edit: { src: item.src, id: item.id },
      stars: Number(doc.points) || 1, who: [item.memberId].filter(Boolean),
      days: doc.days && doc.days.length ? [...doc.days] : [parseKey(item.date).getDay()],
    });
    $('#tTitle').value = doc.title || '';
    $('#tDate').value = item.src === 'tasks' ? doc.date : (doc.start || item.date);
    $('#tTime').value = doc.time || '';
    $('#tEnd').value = doc.endTime || '';
    $('#tRepeat').value = item.src === 'tasks' ? 'none' : (doc.repeat || 'daily');
    $('#tRoutine').value = doc.routine || '';
    drawTaskSheet();
    $('#taskSheet').showModal();
  }

  function drawTaskSheet() {
    const ev = sheetState.type === 'event';
    const editing = !!sheetState.edit;
    $('#taskSheetTitle').textContent = editing ? (ev ? 'Edit event' : 'Edit chore') : 'Add to the board';
    $('#tSubmit').textContent = editing ? 'Save changes' : 'Add it';
    $('#tDelete').hidden = !editing;
    document.querySelectorAll('#tType button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.type === sheetState.type)));
    $('#tStarsWrap').hidden = ev;
    $('#tRoutineWrap').hidden = ev;
    $('#tEndWrap').hidden = !ev;
    $('#tWhoLabel').textContent = editing ? 'Who' : sheetState.who.length ? 'Who (tap more people to give each their own copy)' : 'Who (pick one or more, or leave empty for anyone)';
    $('#tWho').replaceChildren(...state.family.members.map((m) => el('button', {
      type: 'button', 'aria-pressed': String(sheetState.who.includes(m.id)),
      onclick: () => {
        if (editing) sheetState.who = [m.id];
        else sheetState.who = sheetState.who.includes(m.id) ? sheetState.who.filter((x) => x !== m.id) : [...sheetState.who, m.id];
        drawTaskSheet();
      },
    }, avatar(m, 'sm'), m.name)));
    $('#tStars').replaceChildren(...[1, 2, 3, 4, 5].map((n) => el('button', {
      type: 'button', class: n <= sheetState.stars ? 'on' : '', text: '⭐', 'aria-label': `${n} star${n > 1 ? 's' : ''}`,
      onclick: () => { sheetState.stars = n; drawTaskSheet(); },
    })));
    const weekly = $('#tRepeat').value === 'weekly';
    $('#tDays').hidden = !weekly;
    $('#tDays').replaceChildren(...[1, 2, 3, 4, 5, 6, 0].map((d) => el('button', {
      type: 'button', text: DOW[d].slice(0, 2), 'aria-pressed': String(sheetState.days.includes(d)), 'aria-label': DOW[d],
      onclick: () => {
        sheetState.days = sheetState.days.includes(d) ? sheetState.days.filter((x) => x !== d) : [...sheetState.days, d];
        drawTaskSheet();
      },
    })));
  }

  async function submitTask(e) {
    e.preventDefault();
    const title = $('#tTitle').value.trim();
    const date = $('#tDate').value;
    if (!title || !date) return;
    const ev = sheetState.type === 'event';
    const routine = ev ? '' : $('#tRoutine').value;
    let repeat = $('#tRepeat').value;
    if (routine && repeat === 'none') repeat = 'daily';
    const days = repeat === 'weekly' ? (sheetState.days.length ? sheetState.days : [parseKey(date).getDay()]) : [];
    const base = { title, type: sheetState.type, time: $('#tTime').value || '', endTime: ev ? ($('#tEnd').value || '') : '', points: ev ? 0 : sheetState.stars, routine };
    const asTask = (memberId) => ({ ...base, memberId, date, done: false, createdAt: Date.now() });
    const asChore = (memberId) => ({ ...base, memberId, repeat, days, start: date, createdAt: Date.now() });
    const edit = sheetState.edit;
    $('#taskSheet').close();
    try {
      if (edit) {
        const memberId = sheetState.who[0] || '';
        if (edit.src === 'tasks' && repeat === 'none') await col('tasks').doc(edit.id).update({ ...base, memberId, date });
        else if (edit.src === 'chores' && repeat !== 'none') await col('chores').doc(edit.id).update({ ...base, memberId, repeat, days, start: date });
        else {
          await col(edit.src).doc(edit.id).delete();
          await (repeat === 'none' ? col('tasks').add(asTask(memberId)) : col('chores').add(asChore(memberId)));
        }
        toast('Saved ✨');
      } else {
        const who = sheetState.who.length ? sheetState.who : [''];
        const batch = db.batch();
        who.forEach((memberId) => batch.set((repeat === 'none' ? col('tasks') : col('chores')).doc(), repeat === 'none' ? asTask(memberId) : asChore(memberId)));
        await batch.commit();
        toast(routine ? 'Routine step added 🌅' : repeat !== 'none' ? 'Repeating item added 🔁' : ev ? 'Event added 📅' : 'Added to the board ✨');
      }
    } catch (err) { fail(err); }
  }

  // ---------- Meals sheet ----------
  let mealKey = '';
  function openMealSheet(key) {
    mealKey = key;
    const meals = state.meals[key] || {};
    $('#mealSheetTitle').textContent = `Meals · ${fmtDay(parseKey(key), { weekday: 'long', month: 'short', day: 'numeric' })}`;
    for (const [type] of MEALS) $(`#m${type[0].toUpperCase()}${type.slice(1)}`).value = meals[type] || '';
    $('#mFavWrap').hidden = !state.recipes.length;
    $('#mFavs').replaceChildren(...[...state.recipes].sort((a, b) => a.title.localeCompare(b.title)).map((r) => {
      const meal = MEALS.find((x) => x[0] === r.type) || MEALS[2];
      return el('button', { class: 'fav', type: 'button', text: `${meal[1]} ${r.title}`, onclick: () => { $(`#m${meal[0][0].toUpperCase()}${meal[0].slice(1)}`).value = r.title; } });
    }));
    $('#mealSheet').showModal();
    $('#mDinner').focus();
  }
  async function writeMeals(key, meals) {
    const clean = Object.fromEntries(MEALS.map(([t]) => [t, String(meals[t] || '').trim()]));
    try {
      if (MEALS.every(([t]) => !clean[t])) await col('meals').doc(key).delete();
      else await col('meals').doc(key).set({ title: clean.dinner, breakfast: clean.breakfast, lunch: clean.lunch, snack: clean.snack, date: key });
    } catch (e) { fail(e); }
  }
  const saveMealField = (key, type, value) => writeMeals(key, { ...(state.meals[key] || {}), [type]: value });

  // ---------- Countdown sheet ----------
  function openCountdownSheet() {
    $('#cdName').value = ''; $('#cdDate').value = ''; $('#cdEmoji').value = '🎉'; $('#cdYearly').checked = false;
    drawCountdownList();
    $('#countdownSheet').showModal();
    $('#cdName').focus();
  }
  function drawCountdownList() {
    const list = upcomingCountdowns();
    const past = state.countdowns.filter((c) => !list.some((x) => x.id === c.id));
    $('#cdList').replaceChildren(...(list.length || past.length ? [...list, ...past].map((c) => el('div', { class: 'member-row' },
      el('span', { class: 'cd-emoji', text: c.emoji || '🎉' }),
      el('span', { class: 'n', text: c.title }),
      el('span', { class: 'muted', text: c.days == null ? 'Passed' : c.days === 0 ? 'Today' : `${c.days} days${c.yearly ? ' · yearly' : ''}` }),
      btn('Remove', () => col('countdowns').doc(c.id).delete().catch(fail), 'btn danger small')))
      : [el('p', { class: 'muted', style: 'margin:0', text: 'No countdowns yet.' })]));
  }
  async function submitCountdown(e) {
    e.preventDefault();
    const title = $('#cdName').value.trim(); const date = $('#cdDate').value;
    if (!title || !date) return;
    try {
      await col('countdowns').add({ title, date, emoji: $('#cdEmoji').value.trim() || '🎉', yearly: $('#cdYearly').checked, createdAt: Date.now() });
      $('#cdName').value = ''; $('#cdDate').value = '';
      toast('Countdown added ⏳');
    } catch (err) { fail(err); }
  }

  // ---------- Settings ----------
  const settingsState = { emoji: EMOJI[0] };
  async function openSettings() {
    if (!(await requirePin())) return;
    $('#sFamilyName').value = state.family.name || '';
    const w = state.family.weather;
    $('#sCity').value = w ? w.query || w.name || '' : '';
    $('#sUnit').value = w && w.unit === 'celsius' ? 'celsius' : (w ? 'fahrenheit' : (navigator.language === 'en-US' ? 'fahrenheit' : 'celsius'));
    const sl = state.family.sleep || {};
    $('#sSleepOn').checked = !!sl.on; $('#sSleepStart').value = sl.start || '21:30'; $('#sSleepEnd').value = sl.end || '06:30';
    $('#sSaverMins').value = String((state.family.saver && state.family.saver.minutes) ?? 5);
    $('#sPin').value = '';
    const used = new Set(state.family.members.map((m) => m.emoji));
    settingsState.emoji = EMOJI.find((e) => !used.has(e)) || EMOJI[0];
    renderSettings();
    loadPhotoThumbs();
    $('#settingsSheet').showModal();
  }

  function renderSettings() {
    const members = state.family.members;
    $('#sMembers').replaceChildren(...(members.length ? members.map((m, i) => el('div', { class: 'member-row' },
      avatar(m), el('span', { class: 'n', text: m.name }),
      btn('↑', () => { const a = [...members]; [a[i - 1], a[i]] = [a[i], a[i - 1]]; saveMembers(a); }, 'btn soft small', { 'aria-label': `Move ${m.name} up`, disabled: i === 0 ? true : null }),
      btn('Remove', () => { if (confirm(`Remove ${m.name}? Their items stay on the board as "Anyone".`)) saveMembers(members.filter((x) => x.id !== m.id)); }, 'btn danger small')))
      : [el('p', { class: 'muted', style: 'margin:0', text: 'No one yet. Add your first family member below.' })]));
    $('#sEmojis').replaceChildren(...EMOJI.map((e) => el('button', {
      type: 'button', text: e, 'aria-pressed': String(settingsState.emoji === e), 'aria-label': `Avatar ${e}`,
      onclick: () => { settingsState.emoji = e; renderSettings(); },
    })));
    const repeatLabel = (c) => c.repeat === 'daily' ? 'Every day' : c.repeat === 'weekdays' ? 'Weekdays' : (c.days || []).slice().sort((a, b) => ((a + 6) % 7) - ((b + 6) % 7)).map((d) => DOW[d]).join(', ');
    const sorted = [...state.chores].sort((a, b) => String(a.routine || '~').localeCompare(String(b.routine || '~')) || String(a.title).localeCompare(String(b.title)));
    $('#sChores').replaceChildren(...(sorted.length ? sorted.map((c) => {
      const m = memberById(c.memberId);
      const p = PERIODS.find((x) => x[0] === c.routine);
      return el('div', { class: 'member-row' }, avatar(m, 'sm'),
        el('span', { class: 'n' }, `${p ? p[1] + ' ' : c.type === 'event' ? '📅 ' : ''}${c.title}`, el('span', { class: 'muted', style: 'font-weight:600', text: ` · ${repeatLabel(c)}${c.time ? ' · ' + fmtTime(c.time) : ''}` })),
        btn('Remove', () => deleteItem({ src: 'chores', id: c.id, title: c.title }), 'btn danger small'));
    }) : [el('p', { class: 'muted', style: 'margin:0', text: 'None yet. Use + and choose "Repeat" or "Part of a routine".' })]));
    const w = state.family.weather;
    $('#sCityNow').textContent = w ? `Showing weather for ${w.name}.` : 'Add a city to show the forecast on the board.';
    $('#sCode').textContent = `Family code: ${state.familyId}`;
    renderGcalRows();
  }

  async function saveCity() {
    const q = $('#sCity').value.trim();
    const unit = $('#sUnit').value;
    if (!q) { await famRef().update({ weather: null }).catch(fail); toast('Weather turned off'); return; }
    try {
      const r = await fetch(`https://geocoding-api.open-meteo.com/v1/search?${new URLSearchParams({ name: q.split(',')[0].trim(), count: '5', language: 'en' })}`);
      const j = await r.json();
      const hint = (q.split(',')[1] || '').trim().toLowerCase();
      const res = (j.results || []).find((x) => !hint || [x.admin1, x.country, x.country_code].some((v) => String(v || '').toLowerCase().startsWith(hint))) || (j.results || [])[0];
      if (!res) { toast(`Couldn't find "${q}". Try "City, State".`); return; }
      const name = [res.name, res.admin1 || res.country].filter(Boolean).join(', ');
      await famRef().update({ weather: { name, query: q, lat: res.latitude, lon: res.longitude, unit } });
      toast(`Weather set to ${name} ${WMO(0)}`);
    } catch (e) { toast('Could not look up that city. Check your connection.'); console.error(e); }
  }

  async function copy(text, label) {
    try { await navigator.clipboard.writeText(text); toast(`${label} copied 📋`); }
    catch (_) { prompt('Copy this link:', text); }
  }

  // ---------- Photos & screensaver ----------
  const MAX_PHOTOS = 40;
  function shrinkPhoto(file) {
    return new Promise((resolve, reject) => {
      const img = new Image();
      const url = URL.createObjectURL(file);
      img.onload = () => {
        URL.revokeObjectURL(url);
        const scale = Math.min(1, 1280 / Math.max(img.width, img.height));
        const cv = document.createElement('canvas');
        cv.width = Math.round(img.width * scale); cv.height = Math.round(img.height * scale);
        cv.getContext('2d').drawImage(img, 0, 0, cv.width, cv.height);
        let q = 0.82, data = cv.toDataURL('image/jpeg', q);
        while (data.length > 700000 && q > 0.4) { q -= 0.1; data = cv.toDataURL('image/jpeg', q); }
        resolve(data);
      };
      img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('Not an image')); };
      img.src = url;
    });
  }
  async function uploadPhotos(files) {
    const existing = (await col('photos').get()).size;
    let room = MAX_PHOTOS - existing;
    if (room <= 0) { toast(`The screensaver holds up to ${MAX_PHOTOS} photos. Remove some first.`); return; }
    let n = 0;
    for (const f of files) {
      if (room <= 0) break;
      try { await col('photos').add({ data: await shrinkPhoto(f), createdAt: Date.now() }); n++; room--; } catch (e) { console.error(e); }
    }
    toast(n ? `${n} photo${n === 1 ? '' : 's'} added 📷` : 'No photos were added');
    loadPhotoThumbs();
  }
  async function loadPhotoThumbs() {
    try {
      const snap = await col('photos').orderBy('createdAt').get();
      const rows = snap.docs.map((d) => ({ id: d.id, ...d.data() }));
      if (!KIOSK) state.photos = rows;
      $('#sPhotos').replaceChildren(...(rows.length ? rows.map((p) => el('div', { class: 'thumb' },
        el('img', { src: p.data, alt: 'Family photo' }),
        btn('✕', async () => { await col('photos').doc(p.id).delete().catch(fail); loadPhotoThumbs(); }, 'thumb-del', { 'aria-label': 'Remove photo' })))
        : [el('p', { class: 'muted', style: 'margin:0', text: 'No photos yet.' })]));
    } catch (e) { console.error(e); }
  }

  const saver = { on: false, idx: 0, timer: null, front: 'A' };
  function nextUpText() {
    const hm = nowHM();
    const items = itemsFor(dayKey(today0()), 'all').filter((i) => !i.done && (i.allDay || !i.time || i.time >= hm));
    const nxt = items.find((i) => i.time && !i.allDay) || items[0];
    if (!nxt) return '';
    const m = memberById(nxt.memberId);
    return `Next: ${nxt.time && !nxt.allDay ? fmtTime(nxt.time) + ' · ' : ''}${nxt.title}${m ? ' · ' + m.emoji + ' ' + m.name : ''}`;
  }
  function showSaver() {
    if (!state.photos.length) { toast('Add photos in settings first 📷'); return; }
    saver.on = true; saver.idx = Math.floor(Math.random() * state.photos.length);
    $('#saver').hidden = false;
    const step = () => {
      if (!state.photos.length) { hideSaver(); return; }
      const p = state.photos[saver.idx % state.photos.length];
      const show = saver.front === 'A' ? $('#saverImgB') : $('#saverImgA');
      const hide = saver.front === 'A' ? $('#saverImgA') : $('#saverImgB');
      show.src = p.data; show.classList.add('on'); hide.classList.remove('on');
      saver.front = saver.front === 'A' ? 'B' : 'A';
      saver.idx++;
      $('#saverNext').textContent = nextUpText();
    };
    step();
    clearInterval(saver.timer);
    saver.timer = setInterval(step, 8000);
  }
  function hideSaver() {
    saver.on = false; clearInterval(saver.timer);
    $('#saver').hidden = true;
  }

  // Sleep mode and idle handling on the wall display.
  const idle = { last: Date.now(), wakeUntil: 0 };
  const inRange = (t, s, e) => (s <= e ? t >= s && t < e : t >= s || t < e);
  function kioskTick() {
    const now = Date.now();
    const sl = state.family.sleep;
    const sleeping = !!(sl && sl.on && sl.start && sl.end && inRange(nowHM(), sl.start, sl.end) && now > idle.wakeUntil);
    $('#sleep').hidden = !sleeping;
    if (sleeping) { if (saver.on) hideSaver(); return; }
    const idleMin = (now - idle.last) / 60000;
    const mins = Number((state.family.saver && state.family.saver.minutes) ?? 5);
    if (mins > 0 && !saver.on && state.photos.length && idleMin >= mins) showSaver();
    if (idleMin >= 3 && state.view !== 'today' && !document.querySelector('dialog[open]')) { state.view = 'today'; state.offset = 0; render(); }
  }

  // ---------- Google Calendar ----------
  // Each person connects from their own device with Google's sign-in window (OAuth).
  // The board gets a short-lived, read-only token; no passwords and no refresh tokens are stored.
  // Imported events are copied into the family's shared "events" collection so every device sees them.
  const GCAL_SCOPE = 'https://www.googleapis.com/auth/calendar.readonly';
  const GCAL_API = 'https://www.googleapis.com/calendar/v3';
  const gcalKey = () => `gcal:${state.familyId}`;
  const gcalLocal = () => { try { return JSON.parse(store.get(gcalKey()) || 'null'); } catch (_) { return null; } };
  const setGcalLocal = (v) => (v ? store.set(gcalKey(), JSON.stringify(v)) : store.del(gcalKey()));
  const tokenCache = {
    get() { try { const t = JSON.parse(sessionStorage.getItem('gcalToken') || 'null'); return t && t.exp > Date.now() ? t.token : null; } catch (_) { return null; } },
    set(token, seconds) { try { sessionStorage.setItem('gcalToken', JSON.stringify({ token, exp: Date.now() + (seconds - 60) * 1000 })); } catch (_) {} },
    clear() { try { sessionStorage.removeItem('gcalToken'); } catch (_) {} },
  };
  let syncing = false;

  // Must be called directly from a tap: Google's sign-in opens a pop-up window.
  function requestGoogleToken(promptMode) {
    return new Promise((resolve, reject) => {
      const clientId = window.GOOGLE_CLIENT_ID;
      if (!clientId) return reject(new Error('Google Calendar is not set up for this board yet. See the README.'));
      if (!(window.google && google.accounts && google.accounts.oauth2)) return reject(new Error('Google sign-in did not load. Check your connection and try again.'));
      const client = google.accounts.oauth2.initTokenClient({
        client_id: clientId,
        scope: GCAL_SCOPE,
        callback: (resp) => {
          if (resp.error) return reject(new Error(resp.error === 'access_denied' ? 'Calendar access was not allowed.' : (resp.error_description || resp.error)));
          if (!google.accounts.oauth2.hasGrantedAllScopes(resp, GCAL_SCOPE)) return reject(new Error('Please tick the calendar box on the Google screen so the board can read events.'));
          tokenCache.set(resp.access_token, Number(resp.expires_in) || 3600);
          resolve(resp.access_token);
        },
        error_callback: (err) => reject(new Error(err && err.type === 'popup_closed' ? 'The Google window was closed before finishing.' : 'The Google window was blocked. Allow pop-ups for this site and try again.')),
      });
      client.requestAccessToken({ prompt: promptMode });
    });
  }

  async function gapi(token, path) {
    const r = await fetch(GCAL_API + path, { headers: { Authorization: `Bearer ${token}` } });
    if (r.status === 401) { tokenCache.clear(); const e = new Error('Google sign-in expired. Tap sync to reconnect.'); e.code = 'auth'; throw e; }
    if (!r.ok) throw new Error(`Google Calendar returned an error (${r.status}). Try again in a minute.`);
    return r.json();
  }

  function hashId(s) {
    let h = 0x811c9dc5;
    for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193); }
    return (h >>> 0).toString(36);
  }

  // Turn Google events into one board entry per day they cover (multi-day events capped at 14 days).
  function toBoardEvents(items, memberId) {
    const out = new Map();
    const hm = (d) => `${pad(d.getHours())}:${pad(d.getMinutes())}`;
    for (const e of items) {
      if (e.status === 'cancelled' || !e.start) continue;
      const title = String(e.summary || 'Busy').slice(0, 200);
      const put = (date, extra) => {
        const id = `g-${memberId}-${hashId(`${e._cal}|${e.id}|${date}`)}`;
        out.set(id, { title, date, memberId, source: 'google', allDay: false, time: '', endTime: '', ...extra });
      };
      if (e.start.date) {
        let d = parseKey(e.start.date); const end = parseKey(e.end && e.end.date ? e.end.date : e.start.date);
        for (let n = 0; (d < end || n === 0) && n < 14; n++, d = addDays(d, 1)) put(dayKey(d), { allDay: true });
      } else if (e.start.dateTime) {
        const s = new Date(e.start.dateTime); const en = new Date(e.end && e.end.dateTime ? e.end.dateTime : e.start.dateTime);
        const sameDay = dayKey(s) === dayKey(en);
        put(dayKey(s), { time: hm(s), endTime: sameDay ? hm(en) : '' });
        // Continue overnight or multi-day timed events on the following days as all-day markers.
        let d = addDays(parseKey(dayKey(s)), 1);
        for (let n = 0; d < en && n < 13; n++, d = addDays(d, 1)) put(dayKey(d), { allDay: true });
      }
    }
    return out;
  }

  async function syncCalendar(token, conn, { quiet = false } = {}) {
    if (syncing) return;
    syncing = true;
    $('#syncBtn').classList.add('spinning');
    try {
      const from = addDays(today0(), -7), to = addDays(today0(), 60);
      const items = [];
      for (const calId of conn.calendars) {
        let pageToken = '';
        do {
          const q = new URLSearchParams({ singleEvents: 'true', orderBy: 'startTime', maxResults: '250', timeMin: from.toISOString(), timeMax: to.toISOString() });
          if (pageToken) q.set('pageToken', pageToken);
          const j = await gapi(token, `/calendars/${encodeURIComponent(calId)}/events?${q}`);
          for (const e of j.items || []) items.push({ ...e, _cal: calId });
          pageToken = j.nextPageToken || '';
        } while (pageToken);
      }
      const fresh = toBoardEvents(items, conn.memberId);
      const fromKey = dayKey(from);
      const mine = state.events.filter((e) => e.memberId === conn.memberId && e.source === 'google');
      const ops = [];
      for (const old of mine) if (old.date >= fromKey && !fresh.has(old.id)) ops.push((b) => b.delete(col('events').doc(old.id)));
      const same = (a, b) => a && ['title', 'date', 'time', 'endTime', 'allDay'].every((k) => (a[k] || '') === (b[k] || ''));
      for (const [id, data] of fresh) {
        if (!same(mine.find((x) => x.id === id), data)) ops.push((b) => b.set(col('events').doc(id), { ...data, syncedAt: Date.now() }));
      }
      for (let i = 0; i < ops.length; i += 400) {
        const batch = db.batch();
        ops.slice(i, i + 400).forEach((op) => op(batch));
        await batch.commit();
      }
      const members = state.family.members.map((m) => (m.id === conn.memberId ? { ...m, calendarSyncedAt: Date.now(), calendarConnected: true } : m));
      await famRef().update({ members });
      if (!quiet) toast(`Calendar synced 📅 ${fresh.size} event${fresh.size === 1 ? '' : 's'} on the board`);
    } catch (e) {
      if (!quiet || e.code !== 'auth') toast(e.message || 'Calendar sync failed. Try again.');
      if (e.code !== 'auth') console.error(e);
    } finally {
      syncing = false;
      $('#syncBtn').classList.remove('spinning');
      renderSyncBtn();
    }
  }

  // On open: sync silently if this device still holds a valid token (no pop-up).
  function autoSyncCalendar() {
    const conn = gcalLocal();
    const token = tokenCache.get();
    renderSyncBtn();
    if (conn && token) setTimeout(() => syncCalendar(token, conn, { quiet: true }), 1500);
  }

  async function syncNow() {
    const conn = gcalLocal();
    if (!conn) { openSettings(); return; }
    try {
      const token = tokenCache.get() || await requestGoogleToken('');
      await syncCalendar(token, conn);
    } catch (e) { toast(e.message); }
  }

  let pendingConnect = null;
  async function connectCalendar(memberId) {
    try {
      const token = await requestGoogleToken('consent');
      const list = await gapi(token, '/users/me/calendarList?minAccessRole=reader');
      const cals = (list.items || []).sort((a, b) => (b.primary ? 1 : 0) - (a.primary ? 1 : 0));
      const prev = gcalLocal();
      const chosen = new Set(prev && prev.memberId === memberId ? prev.calendars : cals.filter((c) => c.primary).map((c) => c.id));
      pendingConnect = { token, memberId };
      $('#calSheetTitle').textContent = `Pick ${memberById(memberId)?.name || 'your'}'s calendars`;
      $('#calList').replaceChildren(...cals.map((c) => {
        const box = el('input', { type: 'checkbox', value: c.id, id: 'cal-' + hashId(c.id) });
        box.checked = chosen.has(c.id);
        return el('label', { class: 'cal-choice', for: box.id }, box,
          el('span', { class: 'sw', style: `background:${safeColor(c.backgroundColor)}` }),
          el('span', { text: (c.summaryOverride || c.summary || c.id) + (c.primary ? ' (main)' : '') }));
      }));
      $('#settingsSheet').close();
      $('#calSheet').showModal();
    } catch (e) { toast(e.message); }
  }

  async function importChosen() {
    if (!pendingConnect) return;
    const calendars = [...document.querySelectorAll('#calList input:checked')].map((x) => x.value);
    if (!calendars.length) { toast('Pick at least one calendar'); return; }
    const conn = { memberId: pendingConnect.memberId, calendars };
    const token = pendingConnect.token;
    pendingConnect = null;
    setGcalLocal(conn);
    $('#calSheet').close();
    await syncCalendar(token, conn);
  }

  async function disconnectCalendar(memberId) {
    const m = memberById(memberId);
    if (!confirm(`Disconnect ${m ? m.name + "'s" : 'this'} Google Calendar and remove its events from the board?`)) return;
    try {
      const mine = state.events.filter((e) => e.memberId === memberId && e.source === 'google');
      for (let i = 0; i < mine.length; i += 400) {
        const batch = db.batch();
        mine.slice(i, i + 400).forEach((e) => batch.delete(col('events').doc(e.id)));
        await batch.commit();
      }
      const conn = gcalLocal();
      if (conn && conn.memberId === memberId) {
        const token = tokenCache.get();
        if (token && window.google && google.accounts && google.accounts.oauth2) google.accounts.oauth2.revoke(token, () => {});
        tokenCache.clear();
        setGcalLocal(null);
      }
      await saveMembers(state.family.members.map((x) => (x.id === memberId ? { ...x, calendarConnected: false, calendarSyncedAt: null } : x)));
      toast('Calendar disconnected');
      renderSyncBtn();
    } catch (e) { fail(e); }
  }

  const ago = (t) => {
    if (!t) return 'never';
    const mins = Math.round((Date.now() - t) / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins} min ago`;
    const h = Math.round(mins / 60);
    return h < 48 ? `${h} hr ago` : `${Math.round(h / 24)} days ago`;
  };

  function renderSyncBtn() {
    const conn = gcalLocal();
    const b = $('#syncBtn');
    b.hidden = !conn || !memberById(conn.memberId);
    if (b.hidden) return;
    const m = memberById(conn.memberId);
    const stale = !m.calendarSyncedAt || Date.now() - m.calendarSyncedAt > 3 * 3600 * 1000;
    b.querySelector('.badge')?.remove();
    if (stale) b.append(el('span', { class: 'badge', 'aria-hidden': 'true' }));
    b.title = `Sync ${m.name}'s Google Calendar (last synced ${ago(m.calendarSyncedAt)})`;
  }

  function renderGcalRows() {
    const conn = gcalLocal();
    const configured = !!window.GOOGLE_CLIENT_ID;
    $('#gcalRows').replaceChildren(...(!configured
      ? [el('p', { class: 'error', style: 'margin:0', text: 'Google Calendar is not switched on for this board yet. The board owner needs to add a Google sign-in client ID (see README).' })]
      : state.family.members.length ? state.family.members.map((m) => {
        const here = conn && conn.memberId === m.id;
        const status = m.calendarConnected ? `Connected · synced ${ago(m.calendarSyncedAt)}${here ? ' · this device' : ''}` : 'Not connected';
        const acts = here
          ? [btn('Sync now', syncNow, 'btn small'), btn('Calendars', () => connectCalendar(m.id)), btn('Disconnect', () => disconnectCalendar(m.id), 'btn danger small')]
          : m.calendarConnected
            ? [btn('Remove events', () => disconnectCalendar(m.id), 'btn danger small')]
            : [btn(`I'm ${m.name}: connect`, () => connectCalendar(m.id))];
        return el('div', { class: 'gcal-row' }, avatar(m),
          el('div', {}, el('div', { class: 'n', text: m.name }), el('div', { class: 's', text: status })),
          el('div', { class: 'acts' }, acts));
      }) : [el('p', { class: 'muted', style: 'margin:0', text: 'Add family members first.' })]));
  }

  // ---------- Family lifecycle ----------
  function watchFamily() {
    unsubs.forEach((u) => u());
    unsubs = [famRef().onSnapshot((doc) => {
      const d = doc.data() || {};
      state.family = { name: d.name || '', members: normMembers(d.members), reward: d.reward || null,
        weather: d.weather || null, pinHash: d.pinHash || '', sleep: d.sleep || null, saver: d.saver || null };
      render();
      loadWeather();
    }, fail)];
    const listen = (name, apply) => unsubs.push(col(name).onSnapshot((snap) => { apply(snap.docs.map((x) => ({ id: x.id, ...x.data() }))); render(); }, fail));
    const rows = (name) => (r) => { state[name] = r; };
    listen('tasks', rows('tasks'));
    listen('chores', rows('chores'));
    listen('completions', (r) => { state.completions = Object.fromEntries(r.map((x) => [x.id, x])); });
    listen('meals', (r) => { state.meals = Object.fromEntries(r.map((x) => [x.id, { dinner: x.title || x.dinner || '', breakfast: x.breakfast || '', lunch: x.lunch || '', snack: x.snack || '' }])); });
    listen('groceries', rows('groceries'));
    listen('events', rows('events'));
    listen('rewards', rows('rewards'));
    listen('redemptions', rows('redemptions'));
    listen('lists', rows('lists'));
    listen('listItems', rows('listItems'));
    listen('countdowns', rows('countdowns'));
    listen('recipes', rows('recipes'));
    // Photos are large: only the wall display keeps them in memory.
    if (KIOSK) unsubs.push(col('photos').orderBy('createdAt').onSnapshot((snap) => { state.photos = snap.docs.map((x) => ({ id: x.id, ...x.data() })); }, fail));
    autoSyncCalendar();
  }

  function enterFamily(id) {
    state.familyId = id;
    store.set('familyId', id);
    history.replaceState(null, '', location.pathname + (KIOSK ? '?kiosk=1' : ''));
    $('#setup').hidden = true;
    $('#app').hidden = false;
    render();
    watchFamily();
  }

  async function createFamily() {
    const id = crypto.randomUUID().replace(/-/g, '');
    const name = $('#familyNameInput').value.trim();
    try {
      await db.collection('families').doc(id).set({ name, members: [], createdAt: Date.now() });
      enterFamily(id);
      setTimeout(openSettings, 300);
    } catch (e) { fail(e); }
  }

  async function joinFamily() {
    const id = $('#joinCode').value.trim();
    if (!id) return;
    try {
      const doc = await db.collection('families').doc(id).get();
      if (!doc.exists) { toast('No family found with that code'); return; }
      enterFamily(id);
    } catch (e) { fail(e); }
  }

  // ---------- Wiring ----------
  function bind() {
    $('#createBtn').addEventListener('click', createFamily);
    $('#joinBtn').addEventListener('click', joinFamily);
    document.querySelectorAll('.tab').forEach((t) => t.addEventListener('click', () => {
      state.view = t.dataset.view; state.offset = 0; state.redeeming = null; state.editingGoal = false;
      if (!KIOSK) store.set('view', state.view);
      render(); scrollTo({ top: 0 });
    }));
    $('#fab').addEventListener('click', () => {
      if (state.view === 'routines') return openTaskSheet(dayKey(today0()), { routine: state.routinePeriod || currentPeriod() });
      const weekStart = state.view === 'calendar' && state.calMode === 'week' && state.offset !== 0 ? dayKey(addDays(mondayOf(today0()), state.offset * 7)) : null;
      openTaskSheet(weekStart || dayKey(today0()));
    });
    $('#settingsBtn').addEventListener('click', openSettings);
    $('#taskForm').addEventListener('submit', submitTask);
    $('#tRepeat').addEventListener('change', drawTaskSheet);
    document.querySelectorAll('#tType button').forEach((b) => b.addEventListener('click', () => { sheetState.type = b.dataset.type; drawTaskSheet(); }));
    $('#tDelete').addEventListener('click', async () => {
      const ed = sheetState.edit; if (!ed) return;
      const doc = (ed.src === 'tasks' ? state.tasks : state.chores).find((x) => x.id === ed.id);
      if (await deleteItem({ src: ed.src, id: ed.id, title: doc ? doc.title : 'this' })) $('#taskSheet').close();
    });
    $('#mealForm').addEventListener('submit', (e) => {
      e.preventDefault();
      $('#mealSheet').close();
      writeMeals(mealKey, { breakfast: $('#mBreakfast').value, lunch: $('#mLunch').value, dinner: $('#mDinner').value, snack: $('#mSnack').value });
    });
    $('#cdForm').addEventListener('submit', submitCountdown);
    $('#pinForm').addEventListener('submit', submitPin);
    $('#pinSheet').addEventListener('close', () => { if (pinResolve) { const r = pinResolve; pinResolve = null; r(false); } });
    ['#taskSheet', '#mealSheet', '#settingsSheet', '#calSheet', '#countdownSheet', '#pinSheet'].forEach((s) => closeOnBackdrop($(s)));
    $('#syncBtn').addEventListener('click', syncNow);
    $('#calImport').addEventListener('click', importChosen);

    $('#sSaveName').addEventListener('click', () => famRef().update({ name: $('#sFamilyName').value.trim() }).then(() => toast('Saved')).catch(fail));
    $('#sMemberForm').addEventListener('submit', (e) => {
      e.preventDefault();
      const name = $('#sMemberName').value.trim();
      if (!name) return;
      const members = state.family.members;
      const used = new Set(members.map((m) => m.color));
      const color = PALETTE.find((c) => !used.has(c)) || PALETTE[members.length % PALETTE.length];
      const m = { id: crypto.randomUUID().slice(0, 8), name, emoji: settingsState.emoji, color };
      $('#sMemberName').value = '';
      const nextUsed = new Set([...members.map((x) => x.emoji), m.emoji]);
      settingsState.emoji = EMOJI.find((x) => !nextUsed.has(x)) || EMOJI[0];
      saveMembers([...members, m]).then(() => toast(`Welcome, ${name}! ${m.emoji}`));
    });
    $('#sSaveCity').addEventListener('click', saveCity);
    $('#sPhotoInput').addEventListener('change', (e) => { const files = [...e.target.files]; e.target.value = ''; if (files.length) uploadPhotos(files); });
    $('#sSaverMins').addEventListener('change', () => famRef().update({ saver: { minutes: Number($('#sSaverMins').value) } }).then(() => toast('Screensaver updated')).catch(fail));
    $('#sSlideshow').addEventListener('click', () => { $('#settingsSheet').close(); showSaver(); });
    $('#sSaveSleep').addEventListener('click', () => famRef().update({ sleep: { on: $('#sSleepOn').checked, start: $('#sSleepStart').value || '21:30', end: $('#sSleepEnd').value || '06:30' } }).then(() => toast('Sleep mode saved 🌙')).catch(fail));
    $('#sSavePin').addEventListener('click', async () => {
      const pin = $('#sPin').value.trim();
      if (!/^\d{4,8}$/.test(pin)) { toast('Use 4 to 8 digits'); return; }
      try {
        await famRef().update({ pinHash: await sha256(`${state.familyId}:${pin}`) });
        try { sessionStorage.setItem(pinKey(), String(Date.now() + 15 * 60000)); } catch (_) {}
        $('#sPin').value = ''; toast('Parent PIN set 🔒');
      } catch (e) { fail(e); }
    });
    $('#sClearPin').addEventListener('click', () => famRef().update({ pinHash: '' }).then(() => toast('Parent PIN removed')).catch(fail));
    const base = location.origin + location.pathname;
    $('#sCopyShare').addEventListener('click', () => copy(`${base}?family=${state.familyId}`, 'Family link'));
    $('#sCopyKiosk').addEventListener('click', () => copy(`${base}?family=${state.familyId}&kiosk=1`, 'Wall display link'));
    $('#sLeave').addEventListener('click', () => {
      if (!confirm('Leave this family on this device? You can rejoin with the family link.')) return;
      unsubs.forEach((u) => u()); unsubs = [];
      store.del('familyId');
      state.familyId = null;
      $('#settingsSheet').close();
      $('#app').hidden = true; $('#setup').hidden = false;
    });

    // Overlays: any touch wakes the screen.
    $('#saver').addEventListener('click', hideSaver);
    $('#sleep').addEventListener('click', () => { idle.wakeUntil = Date.now() + 2 * 60000; $('#sleep').hidden = true; });
    ['pointerdown', 'keydown', 'touchstart'].forEach((ev) => addEventListener(ev, () => { idle.last = Date.now(); }, { passive: true }));

    setInterval(() => { if (dayKey(today0()) !== state.lastDay) render(); else renderHeader(); }, 20 * 1000);
    setInterval(() => loadWeather(true), 30 * 60 * 1000);
    if (KIOSK) setInterval(kioskTick, 15 * 1000);
    // Week cards switch between compact (7 columns) and full (stacked days) layouts.
    let narrow = matchMedia('(max-width: 1000px)').matches;
    addEventListener('resize', () => {
      const now = matchMedia('(max-width: 1000px)').matches;
      if (now !== narrow && state.familyId) { narrow = now; render(); }
    });
    if (KIOSK && 'wakeLock' in navigator) {
      const lock = () => navigator.wakeLock.request('screen').catch(() => {});
      lock();
      document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') lock(); });
    }
  }

  // ---------- Boot ----------
  if (KIOSK) document.body.classList.add('kiosk');
  const cfg = window.FIREBASE_CONFIG || {};
  if (!cfg.apiKey || cfg.apiKey.startsWith('YOUR_')) {
    document.body.prepend(el('p', { class: 'error', text: 'Add your Firebase keys to firebase-config.js first. See README.md.' }));
    return;
  }
  firebase.initializeApp(cfg);
  db = firebase.firestore();
  bind();
  if (params.get('family')) store.set('familyId', params.get('family'));
  if (state.familyId) enterFamily(state.familyId);
  else $('#setup').hidden = false;
})();
