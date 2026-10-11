/* Service worker：只负责接收推送并显示通知，点击通知时打开对应页面。不缓存任何内容，也不拦截任何请求。 */
self.addEventListener("push", (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) { data = { body: event.data ? event.data.text() : "" }; }
  event.waitUntil(self.registration.showNotification(data.title || "Assignment Helper", {
    body: data.body || "",
    tag: data.tag || "assignment-helper",   // 同一个 tag 的新通知会替换旧的，不会堆成一排
    data: { url: data.url || "/" },
  }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  // 只打开本站的页面：就算推送内容被篡改成别的网址，也只会回到首页
  let target = new URL("/", self.location.origin).href;
  try {
    const candidate = new URL((event.notification.data && event.notification.data.url) || "/", self.location.origin);
    if (candidate.origin === self.location.origin) target = candidate.href;
  } catch (e) { /* 用默认值 */ }
  event.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((windows) => {
    for (const w of windows) { if (w.url === target && "focus" in w) return w.focus(); }
    return self.clients.openWindow(target);
  }));
});
