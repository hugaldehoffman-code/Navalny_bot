'use strict';

// Telegram WebApp
const tg = window.Telegram?.WebApp;
if (tg) { tg.ready(); tg.expand(); }
const TG_USER  = tg?.initDataUnsafe?.user;
const USER_NAME = TG_USER ? (TG_USER.first_name || TG_USER.username || 'Игрок') : 'Игрок';
const USER_ID   = TG_USER ? String(TG_USER.id) : 'local_' + Math.random().toString(36).slice(2);

// ── Leaderboard ──────────────────────────────────────────────────────────────
const LB_KEY = 'runner_v1_lb';
function getLB()     { try { return JSON.parse(localStorage.getItem(LB_KEY) || '[]'); } catch { return []; } }
function getRecord() { const me = getLB().find(e => e.uid === USER_ID); return me ? me.score : 0; }
function saveLB(pts) {
  let lb = getLB();
  const idx = lb.findIndex(e => e.uid === USER_ID);
  if (idx >= 0) { if (pts > lb[idx].score) lb[idx].score = pts; }
  else lb.push({ name: USER_NAME, uid: USER_ID, score: pts });
  lb.sort((a, b) => b.score - a.score);
  localStorage.setItem(LB_KEY, JSON.stringify(lb.slice(0, 50)));
}

// ── Canvas ───────────────────────────────────────────────────────────────────
const canvas = document.getElementById('c');
const ctx    = canvas.getContext('2d');
let W, H, GROUND_Y;

function resize() {
  const wrap = document.getElementById('wrapper');
  W = canvas.width  = wrap.clientWidth  || Math.min(window.innerWidth, 480);
  H = canvas.height = wrap.clientHeight || window.innerHeight;
  GROUND_Y = Math.floor(H * 0.73);
}
resize();
window.addEventListener('resize', () => { resize(); initBg(); resetPlayer(); });

// ── Constants ────────────────────────────────────────────────────────────────
const GRAVITY  = 0.62;
const JUMP_VY  = -16.5;
const BASE_SPD = 4.5;
const PW = 30, PH = 52;

// ── State ────────────────────────────────────────────────────────────────────
let state, dist, speed, frame, bgOff, roadOff;
let obstacles, powerups;
let nextSpawn, nextPowerup;
let flashAlpha, flashColor, deathFrames;
let multiplier, multTimer, shielded, shieldTimer;

const player = { x: 0, y: 0, vy: 0, grounded: true };

function resetPlayer() {
  player.x       = Math.floor(W * 0.18) - Math.floor(PW / 2);
  player.y       = GROUND_Y - PH;
  player.vy      = 0;
  player.grounded = true;
}

// ── Obstacles ────────────────────────────────────────────────────────────────
// kremlin = кремлёвская башня, bars = тюремная решётка, papers = судебная повестка
const OBS_DEF = [
  { id: 'kremlin', w: 44, h: 74 },
  { id: 'bars',    w: 40, h: 66 },
  { id: 'papers',  w: 62, h: 38 },
];

function spawnObs() {
  const def = OBS_DEF[Math.floor(Math.random() * OBS_DEF.length)];
  obstacles.push({ x: W + 20, y: GROUND_Y - def.h, w: def.w, h: def.h, type: def.id });
  const gap = Math.max(48, 92 - dist * 0.05);
  nextSpawn = gap + Math.random() * 60;
}

// ── Power-ups ────────────────────────────────────────────────────────────────
const PU_DEF = [
  { id: 'star',   w: 28, h: 28 },  // ×2 очки на 6 секунд
  { id: 'shield', w: 28, h: 28 },  // щит на 4 секунды
];

function spawnPowerup() {
  const def = PU_DEF[Math.floor(Math.random() * PU_DEF.length)];
  // Плавает на уровне груди (собирается без прыжка)
  const floatY = GROUND_Y - PH * 0.62 - def.h / 2;
  powerups.push({ x: W + 20, y: floatY, w: def.w, h: def.h, type: def.id });
  nextPowerup = 190 + Math.random() * 240;
}

// ── Background ───────────────────────────────────────────────────────────────
let buildings = [], totalBgW = 0;

function initBg() {
  buildings = [];
  let x = 0;
  const total = W * 6;
  while (x < total) {
    const bw = 28 + Math.floor(Math.random() * 70);
    const bh = 36 + Math.floor(Math.random() * 130);
    const kremlin = Math.random() < 0.12;
    const wins = [];
    for (let wy = 8; wy < bh - 10; wy += 13)
      for (let wx = 5; wx < bw - 3; wx += 10)
        if (Math.random() > 0.42) wins.push([wx, wy]);
    buildings.push({ x, w: bw, h: bh, kremlin, wins });
    x += bw + 4 + Math.floor(Math.random() * 26);
  }
  totalBgW = x;
}
initBg();

// ── Helpers ───────────────────────────────────────────────────────────────────
function starPath(cx, cy, r) {
  ctx.beginPath();
  for (let i = 0; i < 5; i++) {
    const a1 = (i * 4 * Math.PI / 5) - Math.PI / 2;
    const a2 = (i * 4 * Math.PI / 5 + Math.PI / 5) - Math.PI / 2;
    if (i === 0) ctx.moveTo(cx + Math.cos(a1) * r, cy + Math.sin(a1) * r);
    else          ctx.lineTo(cx + Math.cos(a1) * r, cy + Math.sin(a1) * r);
    ctx.lineTo(cx + Math.cos(a2) * (r * 0.42), cy + Math.sin(a2) * (r * 0.42));
  }
  ctx.closePath();
}

// ── Draw: background ─────────────────────────────────────────────────────────
function drawBg() {
  const sky = ctx.createLinearGradient(0, 0, 0, GROUND_Y);
  sky.addColorStop(0, '#07071a');
  sky.addColorStop(1, '#161630');
  ctx.fillStyle = sky;
  ctx.fillRect(0, 0, W, GROUND_Y);

  ctx.fillStyle = 'rgba(255,255,255,0.55)';
  [[.07,.07],[.21,.04],[.37,.13],[.51,.05],[.66,.10],[.82,.05],
   [.13,.22],[.90,.16],[.44,.25],[.75,.29],[.30,.31],[.59,.18],[.93,.32],[.04,.38]
  ].forEach(([fx, fy]) => ctx.fillRect(Math.floor(fx*W), Math.floor(fy*GROUND_Y), 2, 2));

  buildings.forEach(b => {
    let bx = ((b.x - bgOff * 0.3) % totalBgW + totalBgW) % totalBgW - W * 0.15;
    if (bx > W + 90 || bx + b.w < -10) return;
    const by = GROUND_Y - b.h;
    ctx.fillStyle = '#14142a';
    ctx.fillRect(bx, by, b.w, b.h);
    ctx.fillStyle = 'rgba(255,210,0,0.48)';
    b.wins.forEach(([wx, wy]) => ctx.fillRect(bx + wx, by + wy, 4, 4));
    if (b.kremlin) { ctx.fillStyle = '#FFD600'; starPath(bx + b.w/2, by - 9, 8); ctx.fill(); }
  });

  ctx.fillStyle = '#252525';
  ctx.fillRect(0, GROUND_Y, W, H - GROUND_Y);
  ctx.fillStyle = '#333';
  ctx.fillRect(0, GROUND_Y, W, 3);

  ctx.fillStyle = '#FFD600';
  const dw = 30, dh = 4, gap = 44;
  const markY = GROUND_Y + Math.floor((H - GROUND_Y) * 0.38);
  for (let rx = -(roadOff % (dw + gap)); rx < W; rx += dw + gap) ctx.fillRect(rx, markY, dw, dh);
}

// ── Draw: Навальный в костюме ──────────────────────────────────────────────
function drawPlayer() {
  const cx  = player.x + PW / 2;
  const py  = player.y;
  const run = state === 'running';
  const ls  = run && player.grounded ? Math.sin(frame * 0.23) * 10 : 0;
  const as  = run && player.grounded ? Math.sin(frame * 0.23 + Math.PI) * 8 : -4;

  // Щит-ореол
  if (shielded) {
    const pulse = 0.82 + Math.sin(frame * 0.18) * 0.18;
    ctx.globalAlpha = 0.38 * pulse;
    ctx.fillStyle = '#64B4FF';
    ctx.beginPath();
    ctx.ellipse(cx, py + PH * 0.4, PW * 0.9 * pulse, PH * 0.62 * pulse, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.globalAlpha = 1;
  }

  // Тень при прыжке
  if (!player.grounded && state !== 'dead') {
    const d  = Math.max(0, GROUND_Y - PH - player.y);
    const sc = Math.max(0.15, 1 - d / (H * 0.32));
    ctx.fillStyle = 'rgba(0,0,0,0.25)';
    ctx.beginPath();
    ctx.ellipse(cx, GROUND_Y + 5, PW * 0.5 * sc, 4 * sc, 0, 0, Math.PI * 2);
    ctx.fill();
  }

  // ── Ноги (тёмные брюки) ──
  ctx.fillStyle = '#2C3E50';
  ctx.fillRect(cx - 12, py + 32, 11, 18 + ls);
  ctx.fillRect(cx +  1, py + 32, 11, 18 - ls);

  // ── Ботинки (чёрные) ──
  ctx.fillStyle = '#111';
  ctx.fillRect(cx - 14, py + 47 + ls, 15, 5);
  ctx.fillRect(cx -  1, py + 47 - ls, 15, 5);

  // ── Пиджак (тёмно-синий) ──
  ctx.fillStyle = '#1E2A3A';
  ctx.fillRect(cx - 13, py + 8, 26, 25);

  // ── Белые воротнички (V-вырез) ──
  ctx.fillStyle = '#EEEEEE';
  ctx.beginPath();
  ctx.moveTo(cx - 2, py + 9);
  ctx.lineTo(cx - 7, py + 18);
  ctx.lineTo(cx - 2, py + 18);
  ctx.fill();
  ctx.beginPath();
  ctx.moveTo(cx + 2, py + 9);
  ctx.lineTo(cx + 7, py + 18);
  ctx.lineTo(cx + 2, py + 18);
  ctx.fill();

  // ── Жёлтый галстук ФБК (ключевая деталь!) ──
  ctx.fillStyle = '#FFD600';
  ctx.beginPath();
  ctx.moveTo(cx - 2, py + 10);
  ctx.lineTo(cx + 2, py + 10);
  ctx.lineTo(cx + 3, py + 26);
  ctx.lineTo(cx,     py + 31);
  ctx.lineTo(cx - 3, py + 26);
  ctx.fill();
  // Узел галстука
  ctx.fillStyle = '#E5C000';
  ctx.fillRect(cx - 3, py + 10, 6, 6);

  // ── Рукава пиджака ──
  ctx.fillStyle = '#1E2A3A';
  ctx.fillRect(cx - 21, py + 12 + as, 10, 6);
  ctx.fillRect(cx + 11, py + 12 - as, 10, 6);
  // Манжеты (белые)
  ctx.fillStyle = '#EEE';
  ctx.fillRect(cx - 22, py + 12 + as, 3, 6);
  ctx.fillRect(cx + 19, py + 12 - as, 3, 6);

  // ── Голова ──
  ctx.fillStyle = '#F0B899';
  ctx.beginPath();
  ctx.arc(cx, py, 13, 0, Math.PI * 2);
  ctx.fill();

  // ── Тёмные волосы (зачёс набок) ──
  ctx.fillStyle = '#3A2418';
  ctx.beginPath();
  ctx.arc(cx + 1, py - 5, 11, Math.PI, Math.PI * 2);
  ctx.fill();
  ctx.fillRect(cx - 11, py - 6, 23, 7);    // чёлка
  ctx.fillRect(cx - 13, py - 2, 4, 6);     // левый висок
  ctx.fillRect(cx + 7,  py - 14, 7, 5);    // зачёс вправо (характерно!)

  // ── Брови (решительные) ──
  ctx.fillStyle = '#3A2418';
  ctx.fillRect(cx - 7, py - 7, 5, 2);
  ctx.fillRect(cx + 2, py - 7, 5, 2);

  // ── Глаза ──
  ctx.fillStyle = '#222';
  ctx.fillRect(cx - 6, py - 3, 4, 3);
  ctx.fillRect(cx + 2, py - 3, 4, 3);

  // Мигание при ×2
  if (multiplier > 1 && Math.floor(frame / 8) % 2 === 0) {
    ctx.globalAlpha = 0.16;
    ctx.fillStyle = '#FFD600';
    ctx.beginPath();
    ctx.ellipse(cx, py + PH * 0.35, PW * 0.75, PH * 0.52, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.globalAlpha = 1;
  }
}

// ── Draw: препятствия ────────────────────────────────────────────────────────
function drawObs(o) {

  if (o.type === 'kremlin') {
    // Основание башни (тёмно-красный кирпич)
    ctx.fillStyle = '#8B1A1A';
    ctx.fillRect(o.x, o.y + 16, o.w, o.h - 16);

    // Горизонтальные линии кирпичной кладки
    ctx.fillStyle = '#6B1414';
    for (let by = o.y + 22; by < o.y + o.h; by += 10)
      ctx.fillRect(o.x, by, o.w, 2);

    // Зубцы (мерлоны) — 3 штуки
    const mw = Math.floor(o.w / 4);
    ctx.fillStyle = '#8B1A1A';
    for (let i = 0; i < 3; i++) {
      ctx.fillRect(o.x + i * mw + 2, o.y, mw - 2, 18);
      ctx.fillStyle = '#6B1414';
      ctx.fillRect(o.x + i * mw + 2, o.y + 9, mw - 2, 2);
      ctx.fillStyle = '#8B1A1A';
    }

    // Бойница в башне (тёмный прямоугольник)
    ctx.fillStyle = '#3d0000';
    ctx.fillRect(o.x + Math.floor(o.w * 0.3), o.y + 28, Math.floor(o.w * 0.4), Math.floor(o.h * 0.3));

    // Кремлёвская звезда
    ctx.fillStyle = '#FFD600';
    starPath(o.x + o.w / 2, o.y - 10, 10);
    ctx.fill();
    // Блик на звезде
    ctx.fillStyle = '#FFF9';
    starPath(o.x + o.w / 2 - 1, o.y - 11, 4);
    ctx.fill();

  } else if (o.type === 'bars') {
    // Фон за решёткой (тёмный)
    ctx.fillStyle = '#111';
    ctx.fillRect(o.x + 3, o.y + 5, o.w - 6, o.h - 5);

    // Верхняя и нижняя поперечины
    ctx.fillStyle = '#5A5A5A';
    ctx.fillRect(o.x, o.y,          o.w, 7);
    ctx.fillRect(o.x, o.y + o.h - 5, o.w, 5);

    // Вертикальные прутья (4 штуки) с бликом
    const cnt  = 4;
    const barW = 7;
    const gapX = (o.w - barW * cnt) / (cnt + 1);
    for (let i = 0; i < cnt; i++) {
      const bx = o.x + gapX + i * (barW + gapX);
      ctx.fillStyle = '#5A5A5A';
      ctx.fillRect(bx, o.y, barW, o.h);
      // Блик (металлический)
      ctx.fillStyle = '#8A8A8A';
      ctx.fillRect(bx + 1, o.y, 2, o.h);
    }

    // Надпись «СИЗО» на верхней поперечине
    ctx.fillStyle = '#999';
    ctx.font = 'bold 7px sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('СИЗО', o.x + o.w / 2, o.y + 3.5);
    ctx.textBaseline = 'alphabetic';

  } else if (o.type === 'papers') {
    // Три слоя бумаг (чуть смещены)
    const layers = ['#C8BC88', '#DDD3A0', '#F2ECC8'];
    for (let i = 2; i >= 0; i--) {
      ctx.fillStyle = layers[i];
      ctx.fillRect(o.x + i * 3, o.y + i * 3, o.w - i * 2, o.h - i * 2);
    }

    // Линии текста
    ctx.fillStyle = '#B0A06A';
    for (let ly = o.y + 8; ly < o.y + o.h - 4; ly += 7)
      ctx.fillRect(o.x + 6, ly, o.w - 20, 1);

    // Красный штамп «СУДИ!» под углом
    ctx.save();
    ctx.translate(o.x + o.w * 0.64, o.y + o.h * 0.48);
    ctx.rotate(-0.38);
    ctx.strokeStyle = 'rgba(180,0,0,0.88)';
    ctx.lineWidth = 1.5;
    ctx.strokeRect(-17, -9, 34, 18);
    ctx.fillStyle = 'rgba(180,0,0,0.88)';
    ctx.font = 'bold 9px sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('СУДИ!', 0, 1);
    ctx.restore();
    ctx.textBaseline = 'alphabetic';
  }
}

// ── Draw: баффы ──────────────────────────────────────────────────────────────
function drawPowerup(p) {
  const cx  = p.x + p.w / 2;
  const cy  = p.y + p.h / 2;
  const bob = Math.sin(frame * 0.08) * 3; // плавающее движение вверх-вниз
  const pulse = 0.88 + Math.sin(frame * 0.14) * 0.12;

  if (p.type === 'star') {
    // Золотое свечение
    ctx.globalAlpha = 0.35;
    ctx.fillStyle = '#FFD600';
    ctx.beginPath();
    ctx.arc(cx, cy + bob, p.w * 0.72 * pulse, 0, Math.PI * 2);
    ctx.fill();
    ctx.globalAlpha = 1;

    // Звезда
    ctx.fillStyle = '#FFD600';
    starPath(cx, cy + bob, p.w * 0.48 * pulse);
    ctx.fill();
    // Блик
    ctx.fillStyle = 'rgba(255,255,255,0.5)';
    starPath(cx - 1, cy + bob - 2, p.w * 0.2);
    ctx.fill();

    // Подпись «×2»
    ctx.fillStyle = '#FFD600';
    ctx.font = 'bold 12px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('×2', cx, p.y + bob - 6);

  } else if (p.type === 'shield') {
    // Синее свечение
    ctx.globalAlpha = 0.32;
    ctx.fillStyle = '#64B4FF';
    ctx.beginPath();
    ctx.arc(cx, cy + bob, p.w * 0.75 * pulse, 0, Math.PI * 2);
    ctx.fill();
    ctx.globalAlpha = 1;

    // Пузырь
    ctx.fillStyle = '#2979D0';
    ctx.beginPath();
    ctx.arc(cx, cy + bob, p.w * 0.46 * pulse, 0, Math.PI * 2);
    ctx.fill();

    // Символ щита
    ctx.fillStyle = '#FFFFFF';
    const sh = p.w * 0.32 * pulse;
    const sy = cy + bob;
    ctx.beginPath();
    ctx.moveTo(cx - sh, sy - sh * 0.9);
    ctx.lineTo(cx + sh, sy - sh * 0.9);
    ctx.lineTo(cx + sh, sy + sh * 0.1);
    ctx.quadraticCurveTo(cx + sh, sy + sh, cx, sy + sh * 1.3);
    ctx.quadraticCurveTo(cx - sh, sy + sh, cx - sh, sy + sh * 0.1);
    ctx.closePath();
    ctx.fill();

    // Подпись
    ctx.fillStyle = '#64B4FF';
    ctx.font = 'bold 11px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('щит', cx, p.y + bob - 6);
  }
}

// ── UI ────────────────────────────────────────────────────────────────────────
const elScore     = document.getElementById('score');
const elRecord    = document.getElementById('record');
const elMultBadge = document.getElementById('mult-badge');
const elHint      = document.getElementById('hint');
const elOver      = document.getElementById('gameover');
const elOverDist  = document.getElementById('over-dist');
const elOverRec   = document.getElementById('over-rec');

function updateHUD() {
  elScore.textContent  = Math.floor(dist) + ' м';
  elRecord.textContent = 'Рекорд: ' + getRecord() + ' м';
  if (elMultBadge) elMultBadge.style.display = multiplier > 1 ? 'inline-block' : 'none';
}

// ── Game control ──────────────────────────────────────────────────────────────
function initGame() {
  dist        = 0;
  speed       = BASE_SPD;
  frame       = 0;
  bgOff       = 0;
  roadOff     = 0;
  obstacles   = [];
  powerups    = [];
  nextSpawn   = 80;
  nextPowerup = 200 + Math.random() * 150;
  flashAlpha  = 0;
  flashColor  = 'rgba(200,0,0,';
  deathFrames = 0;
  multiplier  = 1;
  multTimer   = 0;
  shielded    = false;
  shieldTimer = 0;
  state       = 'idle';
  resetPlayer();
  updateHUD();
  elHint.style.display = 'flex';
  elOver.classList.remove('show');
}

function startRun() {
  state = 'running';
  elHint.style.display = 'none';
  elOver.classList.remove('show');
}

function die() {
  state      = 'dead';
  flashAlpha = 0.55;
  flashColor = 'rgba(200,0,0,';
  saveLB(Math.floor(dist));
}

// ── Update ────────────────────────────────────────────────────────────────────
function update() {
  if (state === 'idle') {
    player.y = GROUND_Y - PH + Math.sin(Date.now() * 0.003) * 3;
    frame++;
    return;
  }

  if (state === 'dead') {
    deathFrames++;
    player.vy  += GRAVITY * 1.6;
    player.y   += player.vy;
    flashAlpha  = Math.max(0, flashAlpha - 0.022);
    if (deathFrames === 32) {
      elOverDist.textContent = Math.floor(dist) + ' м';
      elOverRec.textContent  = 'Рекорд: ' + getRecord() + ' м';
      elOver.classList.add('show');
    }
    return;
  }

  // running
  frame++;
  speed = BASE_SPD + dist * 0.003;

  // Таймеры баффов
  if (multTimer   > 0) { multTimer--;   if (multTimer   === 0) multiplier = 1; }
  if (shieldTimer > 0) { shieldTimer--; if (shieldTimer === 0) shielded   = false; }

  // Физика
  player.vy += GRAVITY;
  player.y  += player.vy;
  if (player.y >= GROUND_Y - PH) {
    player.y        = GROUND_Y - PH;
    player.vy       = 0;
    player.grounded = true;
  }

  bgOff   += speed;
  roadOff += speed;

  // Препятствия
  nextSpawn--;
  if (nextSpawn <= 0) spawnObs();
  obstacles.forEach(o => { o.x -= speed; });
  obstacles = obstacles.filter(o => o.x + o.w > -10);

  // Баффы
  nextPowerup--;
  if (nextPowerup <= 0) spawnPowerup();
  powerups.forEach(p => { p.x -= speed; });
  powerups = powerups.filter(p => p.x + p.w > -10);

  // Коллизия с препятствиями (5px прощения)
  const pad = 5;
  for (const o of obstacles) {
    if (player.x + pad      < o.x + o.w &&
        player.x + PW - pad > o.x        &&
        player.y + pad      < o.y + o.h  &&
        player.y + PH - pad > o.y) {
      if (shielded) {
        // Щит поглощает удар
        shielded    = false;
        shieldTimer = 0;
        flashAlpha  = 0.35;
        flashColor  = 'rgba(100,180,255,';
        obstacles.splice(obstacles.indexOf(o), 1);
      } else {
        die();
      }
      return;
    }
  }

  // Сбор баффов
  for (let i = powerups.length - 1; i >= 0; i--) {
    const p = powerups[i];
    if (player.x + PW > p.x && player.x < p.x + p.w &&
        player.y + PH > p.y && player.y < p.y + p.h) {
      if (p.type === 'star')   { multiplier = 2; multTimer   = 60 * 6; } // 6 сек
      if (p.type === 'shield') { shielded = true; shieldTimer = 60 * 4; } // 4 сек
      flashAlpha = 0.22;
      flashColor = p.type === 'star' ? 'rgba(255,214,0,' : 'rgba(100,180,255,';
      powerups.splice(i, 1);
    }
  }

  dist += (speed / 60) * multiplier;
  updateHUD();
}

// ── Render ────────────────────────────────────────────────────────────────────
function render() {
  ctx.clearRect(0, 0, W, H);
  drawBg();
  obstacles.forEach(drawObs);
  powerups.forEach(drawPowerup);
  drawPlayer();
  if (flashAlpha > 0) {
    ctx.fillStyle = flashColor + flashAlpha.toFixed(3) + ')';
    ctx.fillRect(0, 0, W, H);
    flashAlpha = Math.max(0, flashAlpha - 0.025);
  }
}

// ── Input ─────────────────────────────────────────────────────────────────────
function onTap() {
  if (state === 'idle')   { startRun(); return; }
  if (state === 'running' && player.grounded) {
    player.vy       = JUMP_VY;
    player.grounded = false;
  }
}

canvas.addEventListener('touchstart', e => { e.preventDefault(); onTap(); }, { passive: false });
canvas.addEventListener('mousedown',  () => onTap());
document.addEventListener('keydown',  e => {
  if (e.code === 'Space' || e.code === 'ArrowUp') { e.preventDefault(); onTap(); }
});

const btnRestart = document.getElementById('btn-restart');
btnRestart.addEventListener('click',    () => { initGame(); startRun(); });
btnRestart.addEventListener('touchend', e => { e.preventDefault(); initGame(); startRun(); });

// ── Loop ──────────────────────────────────────────────────────────────────────
function loop() { update(); render(); requestAnimationFrame(loop); }
initGame();
requestAnimationFrame(loop);
