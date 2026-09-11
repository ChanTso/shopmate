const frames = [...document.querySelectorAll('[data-frame]')];
const steps = [...document.querySelectorAll('[data-step]')];
const pause = document.querySelector('#pause-motion');
const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)');
const platform = document.querySelector('#frame-platform');
let current = 0, paused = reduceMotion.matches, visible = false, lastAction = performance.now();
function select(index) {
  current = index;
  frames.forEach((frame, i) => { frame.classList.toggle('active', i === index); frame.setAttribute('aria-hidden', String(i !== index)); });
  steps.forEach((step, i) => { step.classList.toggle('active', i === index); step.querySelector('button').setAttribute('aria-pressed', String(i === index)); });
  platform.textContent = index === 2 ? 'Android · 实际运行界面' : 'iOS · 实际运行界面';
}
function setPaused(value) {
  paused = value; document.body.classList.toggle('motion-paused', value);
  pause.setAttribute('aria-pressed', String(value)); pause.textContent = value ? '播放动效 ▷' : '暂停动效 Ⅱ';
}
steps.forEach((step, index) => step.querySelector('button').addEventListener('click', () => { select(index); lastAction = performance.now(); }));
pause.addEventListener('click', () => setPaused(!paused));
reduceMotion.addEventListener('change', () => setPaused(reduceMotion.matches));
new IntersectionObserver(entries => { visible = entries.some(entry => entry.isIntersecting); }, {threshold: .15}).observe(document.querySelector('.story-device'));
let scheduled = false;
addEventListener('scroll', () => {
  lastAction = performance.now();
  if (scheduled || paused || innerWidth <= 650) return;
  scheduled = true;
  requestAnimationFrame(() => {
    scheduled = false;
    if (!visible || paused) return;
    const center = innerHeight * .55;
    let best = 0, distance = Infinity;
    steps.forEach((step, i) => { const box = step.getBoundingClientRect(); const d = Math.abs(box.top + box.height / 2 - center); if(d < distance) { distance = d; best = i; } });
    select(best);
  });
}, {passive:true});
setInterval(() => {
  if (!paused && visible && !document.hidden && performance.now() - lastAction > 5800) { select((current + 1) % frames.length); lastAction = performance.now(); }
}, 300);
select(0); setPaused(paused);
