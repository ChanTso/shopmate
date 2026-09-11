/* Local product walkthrough: no network, model, or business write is invoked. */
function initMerchantDemo(root) {
  if (!root) throw new Error('Merchant demo root is required');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const scenes = [...root.querySelectorAll('[data-md-scene]')];
  const titles = ['经营概览', '经营分析', '提案与审批'];
  const question = '分析咖啡机的成交情况，并将 AR-1001 的售价调整到 75.60 元，先准备草案。';
  const answer = '已按付款成功时间与历史成交价核对订单。\n\n十二杯定时滴滤咖啡机当前售价 ¥79.60。我已准备 ¥75.60 的调价草案，批准后执行。';
  const input = root.querySelector('[data-md-input]');
  const bubble = root.querySelector('[data-md-question]');
  const response = root.querySelector('[data-md-answer]');
  let scene = 0, manualPause = false, elapsed = 0, last = performance.now(), visible = true;
  const paused = () => manualPause || reduced.matches;
  const setPhase = value => { root.dataset.phase = String(value); };
  function render() {
    const t = elapsed;
    if (scene === 0) {
      const progress = reduced.matches ? 1 : Math.min(t / 2900, 1);
      const eased = progress * progress * (3 - 2 * progress);
      root.querySelectorAll('[data-md-counter]').forEach(node => {
        const value = Math.round(Number(node.dataset.mdCounter) * eased).toLocaleString('en-US');
        node.textContent = (node.hasAttribute('data-md-money') ? '¥' : '') + value;
      });
      root.querySelectorAll('.md-bars i').forEach((bar,i) => {
        const p = reduced.matches ? 1 : Math.max(.03, Math.min((t-i*55)/2900,1));
        const value = Math.max(.03,p*p*(3-2*p));
        bar.style.transform = `scaleY(${value})`;
        bar.style.setProperty('--label-scale',1/value);
      });
    } else if (scene === 1) {
      const phase = reduced.matches ? 4 : t < 1800 ? 0 : t < 2400 ? 1 : t < 3500 ? 2 : t < 7800 ? 3 : 4;
      setPhase(phase);
      input.textContent = phase === 0 ? question.slice(0, Math.ceil(t / 1700 * question.length)) : '继续追问经营、商品或库存…';
      bubble.textContent = question;
      response.textContent = reduced.matches ? answer : answer.slice(0, Math.max(0, Math.floor((t - 3500) / 35)));
    } else {
      setPhase(reduced.matches ? 4 : t < 500 ? 0 : t < 1600 ? 2 : t < 2100 ? 3 : 4);
    }
  }
  function setMerchantScene(index) {
    if (!Number.isInteger(index) || index < 0 || index >= scenes.length) return;
    if (scene === index && root.dataset.scene === String(index)) return;
    scene = index; elapsed = 0; last = performance.now();
    root.dataset.scene = String(index); setPhase(0);
    scenes.forEach((node, i) => { node.hidden = i !== index; });
    root.querySelector('[data-md-title]').textContent = titles[index];
    render();
  }
  function updatePause() {
    root.classList.toggle('md-paused', paused());
    last = performance.now(); render();
  }
  function setMerchantPaused(flag) { manualPause = Boolean(flag); updatePause(); }
  reduced.addEventListener('change', updatePause);
  const observer = new IntersectionObserver(([entry]) => { visible = entry.isIntersecting; last = performance.now(); });
  observer.observe(root);
  const timer = setInterval(() => {
    const now = performance.now();
    if (!paused() && visible && !document.hidden) {
      elapsed += Math.min(now - last, 200);
      const duration = scene === 0 ? 10000 : scene === 1 ? 12000 : 7200;
      if (elapsed > duration) {
        elapsed = 0;
        // Loop within the scene; the page owns navigation between scenes.
        scenes[scene].getAnimations({subtree:true}).forEach(animation => {
          if (animation.effect?.getTiming().iterations !== Infinity) animation.currentTime = 0;
        });
      }
      render();
    }
    last = now;
  }, 50);
  updatePause();
  return {setMerchantScene, setMerchantPaused, destroy() {clearInterval(timer); observer.disconnect(); reduced.removeEventListener('change', updatePause);}};
}

const merchantPlayback=initMerchantDemo(document.querySelector(".merchant-demo"));
window.setMerchantScene=merchantPlayback.setMerchantScene;
window.setMerchantPaused=merchantPlayback.setMerchantPaused;
