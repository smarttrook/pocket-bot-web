self.addEventListener('push', e => {
  let d={}; try{ d=e.data?e.data.json():{} }catch(_){ d={body:e.data?e.data.text():''} }
  e.waitUntil(self.registration.showNotification(d.title||'Trade Radar', {
    body:d.body||'New signal', tag:d.tag||'trade-radar', renotify:true,
    icon:'/static/radar-icon.png', badge:'/static/radar-icon.png', data:{url:d.url||'/'}
  }));
});
self.addEventListener('notificationclick', e => {
  e.notification.close();
  e.waitUntil(clients.matchAll({type:'window',includeUncontrolled:true}).then(ws=>{
    for(const w of ws){ if('focus' in w) return w.focus(); }
    return clients.openWindow(e.notification.data?.url||'/');
  }));
});
