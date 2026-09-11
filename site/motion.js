const experience = document.querySelector('.experience');
const stage = document.querySelector('.stage-inner');
const device = document.querySelector('.device-anchor');
const shell = document.querySelector('.device-shell');
const hero = document.querySelector('.hero-copy');
const decor = document.querySelector('.scene-decor');
const buyer = document.querySelector('.buyer-copy');
const wideCopy = document.querySelector('.wide-copy');
const phoneMedia = document.querySelector('.phone-media');
const wideMedia = document.querySelector('.wide-media');
const films = [...document.querySelectorAll('[data-film]')];
const copies = [...document.querySelectorAll('[data-copy]')];
const buttons = [...document.querySelectorAll('[data-go]')];
const pause = document.querySelector('#pause-motion');
const reduced = matchMedia('(prefers-reduced-motion: reduce)');
let paused = reduced.matches, current = -1, scheduled = false, buyerVisible = true;
const clamp = n => Math.max(0, Math.min(1, n));
const smooth = n => { n = clamp(n); return n * n * (3 - 2 * n); };
const lerp = (a,b,t) => a + (b-a)*t;
const stops = [.24, .45, .63, .96];
function runFilms() {
  films.forEach((film,i) => {
    if (i === current && !paused && buyerVisible && !document.hidden) {
      if (film.readyState === 0) film.load();
      film.play().catch(() => {});
    } else film.pause();
  });
}
function select(index) {
  if (current === index) return;
  current = index;
  films.forEach((film,i) => {
    film.classList.toggle('active',i===index || (index===3 && i===2));
    film.setAttribute('aria-hidden',String(i!==index));
    if(i===index) film.currentTime = 0;
  });
  copies.forEach((copy,i) => { copy.classList.toggle('active',i===index); copy.setAttribute('aria-hidden',String(i!==index)); });
  buttons.forEach((button,i) => button.setAttribute('aria-pressed',String(i===index)));
  document.querySelector('#step-count').textContent = String(index+1).padStart(2,'0');
  runFilms();
}
function setPaused(value) {
  paused=value;
  document.body.classList.toggle('motion-paused',value);
  document.querySelectorAll('[data-pause]').forEach(control=>{
    control.setAttribute('aria-pressed',String(value));
    control.setAttribute('aria-label',value?'播放演示动画':'暂停演示动画');
    control.querySelector('.pause-glyph').textContent=value?'▷':'Ⅱ';
    control.querySelector('.pause-text').textContent=value?'播放演示':'暂停演示';
  });
  runFilms();
  if(window.setMerchantPaused) window.setMerchantPaused(value || document.hidden);
}
function render() {
  scheduled=false;
  const box=experience.getBoundingClientRect();
  const H=stage.clientHeight,W=stage.clientWidth,mobile=innerWidth<=800;
  const p=clamp(-box.top/(experience.offsetHeight-innerHeight));
  const transfer=smooth((p-.025)/.19), expand=smooth((p-.76)/.15);
  const heroH=Math.min(H*(mobile?.49:.75),mobile?440:730);
  const storyH=Math.min(H*(mobile?.57:.81),mobile?520:750);
  const wideW=Math.min(W*(mobile?1:.92),1140,H*.67*4/3);
  const wideH=wideW*3/4;
  const start={w:heroH*.461,h:heroH,x:W*(mobile?.5:.77),y:H*(mobile?.72:.46)};
  const middle={w:storyH*.461,h:storyH,x:W*(mobile?.5:.245),y:H*(mobile?.65:.5)};
  const end={w:wideW,h:wideH,x:W*.5,y:H*(mobile?.62:.60)};
  let w=lerp(lerp(start.w,middle.w,transfer),end.w,expand);
  let h=lerp(lerp(start.h,middle.h,transfer),end.h,expand);
  let x=lerp(lerp(start.x,middle.x,transfer),end.x,expand)-w/2;
  let y=lerp(lerp(start.y,middle.y,transfer),end.y,expand)-h/2;
  device.style.width=w+'px';device.style.height=h+'px';device.style.transform=`translate3d(${x}px,${y}px,0)`;
  device.classList.toggle('in-story',transfer>.05); device.classList.toggle('expanding',expand>.01);
  shell.style.borderRadius=lerp(mobile?33:46,25,expand)+'px';
  hero.style.opacity=1-smooth(transfer*1.65);
  hero.style.pointerEvents=transfer<.35?'auto':'none';
  hero.inert=transfer>=.35;
  hero.style.transform=mobile?`translateY(${-transfer*40}px)`:`translateY(calc(-50% - ${transfer*45}px))`;
  decor.style.opacity=1-smooth(transfer*1.5);
  buyer.style.opacity=smooth((transfer-.45)/.55)*(1-smooth(expand*2));
  buyer.classList.toggle('visible',transfer>.65&&expand<.3);
  buyer.inert=!(transfer>.65&&expand<.3);
  wideCopy.style.opacity=smooth((expand-.35)/.65);
  phoneMedia.style.opacity=expand===1?0:1;
  wideMedia.style.opacity=smooth((expand-.25)/.65);
  document.querySelector('.scroll-hint').style.opacity=1-expand;
  select(expand>.35?3:p>=.58?2:p>=.40?1:0);
  updateMerchant();
}
function requestRender(){if(!scheduled){scheduled=true;requestAnimationFrame(render);}}
buttons.forEach((button,i)=>button.addEventListener('click',()=>{
  const target=scrollY+experience.getBoundingClientRect().top+stops[i]*(experience.offsetHeight-innerHeight);
  scrollTo({top:target,behavior:reduced.matches?'instant':'smooth'});
}));
document.querySelectorAll('[data-pause]').forEach(control=>control.addEventListener('click',()=>setPaused(!paused)));
reduced.addEventListener('change',()=>setPaused(reduced.matches));
document.addEventListener('visibilitychange',()=>setPaused(paused));
new IntersectionObserver(entries=>{buyerVisible=entries[0].isIntersecting;runFilms();},{threshold:.05}).observe(document.querySelector('.experience-stage'));
addEventListener('scroll',requestRender,{passive:true});addEventListener('resize',requestRender);
let merchantCurrent=-1;
function updateMerchant(){
  const section=document.querySelector('.merchant-section');
  const mount=document.querySelector('#merchant-mount');
  const demo=mount.querySelector('.merchant-demo');
  const mobile=innerWidth<=800;
  const baseWidth=mobile?350:1160, baseHeight=mobile?680:710;
  const availableHeight=Math.max(350,innerHeight-(mobile?285:290));
  const scale=Math.min(mount.parentElement.clientWidth/baseWidth,availableHeight/baseHeight,1.15);
  mount.style.width=(baseWidth*scale)+'px';mount.style.height=(baseHeight*scale)+'px';
  demo.style.width=baseWidth+'px';demo.style.height=baseHeight+'px';demo.style.transform=`scale(${scale})`;
  const rect=section.getBoundingClientRect();
  const progress=clamp(-rect.top/(section.offsetHeight-innerHeight));
  const index=Math.min(2,Math.floor(progress*3));
  if(index!==merchantCurrent){
    merchantCurrent=index;
    document.querySelectorAll('[data-merchant]').forEach((b,i)=>b.setAttribute('aria-pressed',String(i===index)));
    if(window.setMerchantScene) window.setMerchantScene(index);
  }
  if(window.setMerchantPaused) window.setMerchantPaused(paused||document.hidden||rect.top>innerHeight||rect.bottom<0);
}
document.querySelectorAll('[data-merchant]').forEach((button,i)=>button.addEventListener('click',()=>{
 const section=document.querySelector('.merchant-section');
 scrollTo({top:scrollY+section.getBoundingClientRect().top+(i/3+.06)*(section.offsetHeight-innerHeight),behavior:reduced.matches?'instant':'smooth'});
}));
setPaused(paused);render();
