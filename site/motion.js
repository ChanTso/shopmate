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
// Distances are viewport heights: generous reading spans, short scroll-driven handovers.
const stops = [1.10,3.75,6.40,9.80];
const buyerSpans = [[.95,3.6],[3.6,6.25],[6.25,9.65],[9.65,11.5]];
const merchantStops = [.1,2.75,5.35];
const merchantSpans = [[0,2.6],[2.6,5.2],[5.2,7.5]];
const buyerNavigation = document.querySelector('.buyer-navigation');
function chapterProgress(nav, position, travel, spans) {
  if(reduced.matches) position=Math.round(position);
  const items = [...nav.querySelectorAll('button')];
  items.forEach((button,i) => {
    const weight = Math.max(0,1-Math.abs(position-i));
    const rgb = [101,94,82].map((v,c)=>Math.round(lerp(v,[182,58,43][c],weight)));
    button.style.color = `rgb(${rgb.join(',')})`;
    button.style.setProperty('--chapter-weight',weight);
    button.setAttribute('aria-pressed',String(i===Math.round(position)));
    button.querySelector('.chapter-track i').style.transform = `scaleX(${clamp((travel-spans[i][0])/(spans[i][1]-spans[i][0]))})`;
  });
}
const ramp = (p,a,b) => smooth((p-a)/(b-a));
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

  });
  copies.forEach((copy,i) => { copy.classList.toggle('active',i===index); copy.setAttribute('aria-hidden',String(i!==index)); });
  buttons.forEach((button,i) => button.setAttribute('aria-pressed',String(i===index)));

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
  const travel=Math.max(0,-box.top/innerHeight);
  const position=ramp(travel,3.1,3.6)+ramp(travel,5.75,6.25)+ramp(travel,8.75,9.65);
  const transfer=reduced.matches ? Number(travel>=.525) : ramp(travel,.1,.95);
  const expand=reduced.matches ? Number(travel>=9.2) : ramp(travel,8.75,9.65);
  const compact=innerWidth<1100;
  buyerNavigation.style.setProperty('--wide-nav',expand);
  buyerNavigation.style.opacity=smooth((transfer-.45)/.55);
  buyerNavigation.inert=transfer<.7;
  buyerNavigation.style.pointerEvents=transfer>.7?'auto':'none';
  const navW=lerp(W*(mobile?1:.46),W*(compact?1:.5),expand);
  buyerNavigation.style.width=navW+'px';
  buyerNavigation.style.left=lerp(mobile?0:W*.54,0,expand)+'px';
  buyerNavigation.style.top=lerp(H*(mobile?.035:.12),18,expand)+'px';
  const wideHeaderBottom=Math.max(18+buyerNavigation.offsetHeight,wideCopy.offsetTop+wideCopy.offsetHeight);
  const mediaTop=wideHeaderBottom+20;
  const heroH=Math.min(H*(mobile?.49:.75),mobile?440:730);
  const storyH=Math.min(H*(mobile?.55:.86),mobile?520:820);
  const wideW=Math.min(W,1240,(H-mediaTop-28)*4/3);
  const wideH=wideW*3/4;
  const start={w:heroH*.461,h:heroH,x:W*(mobile?.5:.77),y:H*(mobile?.72:.46)};
  const middle={w:storyH*.461,h:storyH,x:W*(mobile?.5:.23),y:H*(mobile?.70:.5)};
  const end={w:wideW,h:wideH,x:W*.5,y:mediaTop+wideH/2+(mobile?Math.max(0,H-mediaTop-wideH-50)*.3:0)};
  let w=lerp(lerp(start.w,middle.w,transfer),end.w,expand);
  let h=lerp(lerp(start.h,middle.h,transfer),end.h,expand);
  let x=lerp(lerp(start.x,middle.x,transfer),end.x,expand)-w/2;
  let y=lerp(lerp(start.y,middle.y,transfer),end.y,expand)-h/2;
  device.style.width=w+'px';device.style.height=h+'px';device.style.transform=`translate3d(${x}px,${y}px,0)`;
  device.style.setProperty('--float',1-transfer); device.classList.toggle('in-story',transfer>.05); device.classList.toggle('expanding',expand>.01);
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
  films[3].style.opacity=1;
  document.querySelector('.scroll-hint').style.opacity=1-expand;
  select(Math.round(position));
  chapterProgress(document.querySelector('.buyer-chapters'),position,travel,buyerSpans);
  copies.forEach((copy,i)=>{
    copy.style.transform=reduced.matches ? "none" : `translateY(${(i-position)*(copy.parentElement.clientHeight+20)}px)`;
    copy.style.opacity=reduced.matches ? Number(i===current) : clamp(1-Math.abs(position-i));
  });
  films.slice(0,3).forEach((film,i)=>film.style.opacity=reduced.matches?Number(i===Math.min(current,2)):position>=2?(i===2?1:0):clamp(1-Math.abs(position-i)));
  updateMerchant();
}
function requestRender(){if(!scheduled){scheduled=true;requestAnimationFrame(render);}}
let scrollFrame=0;
function cancelScroll(){cancelAnimationFrame(scrollFrame);scrollFrame=0;}
function scrollToChapter(target,complete=()=>{}) {
  cancelScroll();
  const start=scrollY;
  const distance=Math.max(0,Math.min(target,document.documentElement.scrollHeight-innerHeight))-start;
  if(reduced.matches || Math.abs(distance)<1) {
    scrollTo({top:start+distance,behavior:'instant'});complete();return;
  }
  const duration=1250+450*clamp(Math.abs(distance)/(innerHeight*4));
  const started=performance.now();
  function step(now) {
    const progress=clamp((now-started)/duration);
    const eased=progress<.5?4*progress**3:1-(-2*progress+2)**3/2;
    scrollTo({top:start+distance*eased,behavior:'instant'});
    if(progress<1) scrollFrame=requestAnimationFrame(step);
    else {scrollFrame=0;complete();}
  }
  scrollFrame=requestAnimationFrame(step);
}
addEventListener('wheel',cancelScroll,{passive:true});
addEventListener('touchstart',cancelScroll,{passive:true});
addEventListener('popstate',cancelScroll);
addEventListener('keydown',event=>{
  if(['ArrowUp','ArrowDown','PageUp','PageDown','Home','End',' ','Tab'].includes(event.key)) cancelScroll();
});
document.querySelectorAll('a[href^="#"]').forEach(link=>link.addEventListener('click',event=>{
  if(event.defaultPrevented || event.button!==0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  const target=document.getElementById(link.hash.slice(1));
  if(!target) return;
  event.preventDefault();
  if(location.hash!==link.hash) history.pushState(history.state,'',link.hash);
  scrollToChapter(scrollY+target.getBoundingClientRect().top,()=>{
    const hadTabIndex=target.hasAttribute('tabindex');
    if(!hadTabIndex) target.setAttribute('tabindex','-1');
    target.focus({preventScroll:true});
    if(!hadTabIndex) target.addEventListener('blur',()=>target.removeAttribute('tabindex'),{once:true});
  });
}));
buttons.forEach((button,i)=>button.addEventListener('click',()=>{
  const target=scrollY+experience.getBoundingClientRect().top+stops[i]*innerHeight;
  cancelScroll();
  scrollTo({top:target,behavior:'instant'});
}));
document.querySelectorAll('[data-pause]').forEach(control=>control.addEventListener('click',()=>setPaused(!paused)));
reduced.addEventListener('change',()=>{cancelScroll();setPaused(reduced.matches);requestRender();});
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
  const stage=mount.parentElement;
  const top=stage.querySelector('.merchant-top');
  const topBottom=top.getBoundingClientRect().bottom-stage.getBoundingClientRect().top;
  const availableHeight=Math.max(260,stage.clientHeight-topBottom-parseFloat(getComputedStyle(stage).gap)-34);
  const scale=Math.min(mount.parentElement.clientWidth/baseWidth,availableHeight/baseHeight,1.15);
  mount.style.width=(baseWidth*scale)+'px';mount.style.height=(baseHeight*scale)+'px';
  demo.style.width=baseWidth+'px';demo.style.height=baseHeight+'px';demo.style.transform=`scale(${scale})`;
  const rect=section.getBoundingClientRect();
  const travel=Math.max(0,-rect.top/innerHeight);
  const position=ramp(travel,2.1,2.6)+ramp(travel,4.7,5.2);
  chapterProgress(document.querySelector('.merchant-chapters'),position,travel,merchantSpans);
  const index=Math.round(position);
  if(index!==merchantCurrent){
    merchantCurrent=index;
    document.querySelectorAll('[data-merchant]').forEach((b,i)=>b.setAttribute('aria-pressed',String(i===index)));
    if(window.setMerchantScene) window.setMerchantScene(index);
  }
  if(window.setMerchantPaused) window.setMerchantPaused(paused||document.hidden||rect.top>innerHeight||rect.bottom<0);
}
document.querySelectorAll('[data-merchant]').forEach((button,i)=>button.addEventListener('click',()=>{
 const section=document.querySelector('.merchant-section');
 cancelScroll();
 scrollTo({top:scrollY+section.getBoundingClientRect().top+merchantStops[i]*innerHeight,behavior:'instant'});
}));
setPaused(paused);render();
