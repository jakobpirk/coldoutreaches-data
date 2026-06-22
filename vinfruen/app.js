// ===== Vinfruen shared behaviour =====
(function(){
  // nav scroll state (only matters on pages with a dark hero)
  var nav=document.getElementById('nav');
  if(nav && !document.body.classList.contains('inner')){
    var onScroll=function(){nav.classList.toggle('scrolled',window.scrollY>60);};
    onScroll();window.addEventListener('scroll',onScroll,{passive:true});
  }

  // mobile menu
  var burger=document.querySelector('.burger');
  var menu=document.querySelector('header.nav nav');
  if(burger && menu){
    burger.addEventListener('click',function(){
      menu.classList.toggle('open');
      document.body.classList.toggle('menu-open');
    });
    menu.querySelectorAll('a').forEach(function(a){
      a.addEventListener('click',function(){menu.classList.remove('open');document.body.classList.remove('menu-open');});
    });
  }

  // reveal on scroll
  var io=new IntersectionObserver(function(es){
    es.forEach(function(e){if(e.isIntersecting){e.target.classList.add('in');io.unobserve(e.target);}});
  },{threshold:.14,rootMargin:'0px 0px -7% 0px'});
  document.querySelectorAll('.reveal').forEach(function(el){io.observe(el);});

  // wine filter chips
  var bar=document.querySelector('[data-filterbar]');
  if(bar){
    var cards=Array.prototype.slice.call(document.querySelectorAll('.wine'));
    bar.addEventListener('click',function(e){
      var chip=e.target.closest('.chip');if(!chip)return;
      bar.querySelectorAll('.chip').forEach(function(c){c.classList.remove('active');});
      chip.classList.add('active');
      var f=chip.getAttribute('data-filter');
      cards.forEach(function(c){
        var match = f==='all' || (c.getAttribute('data-tags')||'').split(' ').indexOf(f)>-1;
        c.classList.toggle('hide',!match);
      });
      // hide empty group headings
      document.querySelectorAll('[data-group]').forEach(function(g){
        var any=g.querySelectorAll('.wine:not(.hide)').length>0 || f==='all';
      });
    });
  }
})();
