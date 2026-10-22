var C='pf32-v1';
var ASSETS=['./','index.html','manifest.webmanifest','icon-192.png','icon-512.png','apple-touch-icon.png','config.json','glossary.html'];
self.addEventListener('install',function(e){e.waitUntil(caches.open(C).then(function(c){return c.addAll(ASSETS)}));self.skipWaiting()});
self.addEventListener('activate',function(e){e.waitUntil(caches.keys().then(function(k){return Promise.all(k.filter(function(x){return x!==C}).map(function(x){return caches.delete(x)}))}));self.clients.claim()});
// network-first: 항상 최신 data.json, 오프라인이면 마지막 캐시
self.addEventListener('fetch',function(e){
  var u=new URL(e.request.url);
  if(e.request.method!=='GET'||u.origin!==location.origin||u.pathname.indexOf('/api/')>=0)return;
  var key=u.origin+u.pathname;
  e.respondWith(fetch(e.request,{cache:'no-cache'}).then(function(r){if(r.ok){var cp=r.clone();caches.open(C).then(function(c){c.put(key,cp)}).catch(function(){})}return r}).catch(function(){return caches.match(key).then(function(m){return m||caches.match('index.html')})}));
});
