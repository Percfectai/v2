(function(){
  function fix(){
    var header=document.querySelector('header,nav,[class*="header"]');
    if(!header||header.dataset.ppLogo==='1')return;
    var a=header.querySelector('a[href="/"],a[href="/percfectposts"]')||header.querySelector('a');
    if(!a)return;
    // Only replace if text logo
    if(a.querySelector('img#pp-site-logo')){header.dataset.ppLogo='1';return;}
    var txt=(a.textContent||'').trim();
    if(txt.length<40){
      a.innerHTML='<img id="pp-site-logo" src="/static/layouts/percfect-site/home/logo-clear.png" alt="PERCFECT STUDIOS" style="height:40px;width:auto;max-width:200px;object-fit:contain;display:block" onerror="this.src=\'/static/assets/brand/logo_percfect_studios.jpg\'"/>';
      a.setAttribute('href','/');
      header.dataset.ppLogo='1';
    }
  }
  function boot(){fix();var n=0;var t=setInterval(function(){fix();if(++n>30)clearInterval(t);},300);}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();
