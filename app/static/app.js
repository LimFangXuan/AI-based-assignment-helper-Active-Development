/* 作业效率助手 · 页面交互
   原则：没有 JS 时所有表单照样能用（整页提交）；有 JS 时改成局部刷新，并加上动效。 */
(function () {
  "use strict";
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  document.documentElement.classList.add("js");

  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { v === null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch (e) { /* 隐私模式下忽略 */ } },
  };

  // ---------- 主题：Settings 页三选一（初始值在 <head> 里的小脚本设置，避免闪烁） ----------
  $$("[data-theme-choice]").forEach((group) => {
    const current = store.get("theme") || "system";
    $$("input", group).forEach((input) => {
      input.checked = input.value === current;
      input.addEventListener("change", () => {
        const root = document.documentElement;
        if (input.value === "system") { delete root.dataset.theme; store.set("theme", null); }
        else { root.dataset.theme = input.value; store.set("theme", input.value); }
      });
    });
  });

  // ---------- 侧栏：大屏折叠（记住状态），小屏抽屉 ----------
  const root = document.documentElement;
  $$("[data-sidebar-collapse]").forEach((btn) => btn.addEventListener("click", () => {
    const collapsed = root.classList.toggle("sidebar-collapsed");
    store.set("sidebar", collapsed ? "collapsed" : null);
    btn.setAttribute("aria-label", collapsed ? "Expand sidebar" : "Collapse sidebar");
  }));
  const closeDrawer = () => root.classList.remove("sidebar-open");
  $$("[data-sidebar-open]").forEach((btn) => btn.addEventListener("click", () => root.classList.add("sidebar-open")));
  $$("[data-sidebar-close]").forEach((el) => el.addEventListener("click", closeDrawer));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });

  // ---------- 日历：“+N more” 展开当天的全部截止 ----------
  $$("[data-cal-more]").forEach((btn) => btn.addEventListener("click", () => {
    const cell = btn.closest(".cal-cell");
    const open = cell.classList.toggle("expanded");
    btn.setAttribute("aria-expanded", String(open));
    btn.dataset.label = btn.dataset.label || btn.textContent;
    btn.textContent = open ? "Show less" : btn.dataset.label;
  }));

  // ---------- 提示 toast ----------
  const toastBox = $(".toasts");
  function dismiss(el) {
    if (!el || el.classList.contains("leaving")) return;
    el.classList.add("leaving");
    setTimeout(() => el.remove(), reduceMotion ? 0 : 300);
  }
  function arm(el) {
    el.addEventListener("click", () => dismiss(el));
    setTimeout(() => dismiss(el), el.classList.contains("error") ? 7000 : 4000);
  }
  $$(".toasts .flash").forEach(arm);
  function toast(message, kind = "success") {
    if (!toastBox || !message) return;
    const el = document.createElement("div");
    el.className = "flash " + kind;
    el.setAttribute("role", "status");
    el.textContent = message;
    toastBox.appendChild(el);
    arm(el);
  }
  window.toast = toast;

  // ---------- 入场动画：给 .reveal 的子元素编号，错开出现 ----------
  $$(".reveal").forEach((box) => Array.from(box.children).forEach((c, i) => c.style.setProperty("--i", i)));

  // ---------- 确认弹窗（替代浏览器自带的 confirm） ----------
  const confirmDlg = $("#confirm-dialog");
  function askConfirm(form) {
    return new Promise((resolve) => {
      if (!confirmDlg || typeof confirmDlg.showModal !== "function") {
        resolve(window.confirm(form.dataset.confirm));
        return;
      }
      $("[data-c-title]", confirmDlg).textContent = form.dataset.confirmTitle || "Are you sure?";
      $("[data-c-text]", confirmDlg).textContent = form.dataset.confirm;
      const ok = $("[data-c-ok]", confirmDlg);
      ok.textContent = form.dataset.confirmOk || "Confirm";
      ok.className = "btn " + (form.dataset.danger ? "danger" : "");
      $(".dialog-icon", confirmDlg).className = "dialog-icon" + (form.dataset.danger ? " danger" : "");
      confirmDlg.returnValue = "";
      confirmDlg.showModal();
      confirmDlg.addEventListener("close", () => resolve(confirmDlg.returnValue === "ok"), { once: true });
    });
  }

  // ---------- AI 等待层：调用 AI 要十几秒，给出明确的反馈 ----------
  const aiDlg = $("#ai-dialog");
  function showAiWait(form) {
    if (!aiDlg || typeof aiDlg.showModal !== "function") return;
    const lines = (form.dataset.ai || "The AI is thinking").split("|");
    const status = $(".ai-status", aiDlg);
    let i = 0;
    status.textContent = lines[0];
    aiDlg.showModal();
    aiDlg.addEventListener("cancel", (e) => e.preventDefault()); // 提交中不允许按 Esc 关掉
    if (lines.length > 1) {
      setInterval(() => {
        status.classList.add("swap");
        setTimeout(() => {
          i = (i + 1) % lines.length;
          status.textContent = lines[i];
          status.classList.remove("swap");
        }, 300);
      }, 2600);
    }
  }

  // ---------- 所有表单：防重复提交 + 加载状态 + 确认 ----------
  document.addEventListener("submit", async (e) => {
    const form = e.target;
    if (form.matches("[data-ajax]")) return; // 局部刷新的表单单独处理
    if (form.dataset.confirm && !form.dataset.confirmed) {
      e.preventDefault();
      if (await askConfirm(form)) {
        form.dataset.confirmed = "1";
        form.requestSubmit ? form.requestSubmit() : form.submit();
      }
      return;
    }
    if (form.dataset.submitting) { e.preventDefault(); return; }
    form.dataset.submitting = "1";
    const btn = e.submitter || $("[type=submit]", form);
    if (btn) btn.classList.add("is-loading");
    if (form.dataset.ai) showAiWait(form);
  });
  // 浏览器“返回”从缓存恢复页面时，清掉加载状态
  window.addEventListener("pageshow", (e) => {
    if (!e.persisted) return;
    $$("form[data-submitting]").forEach((f) => delete f.dataset.submitting);
    $$(".is-loading").forEach((b) => b.classList.remove("is-loading"));
    if (aiDlg && aiDlg.open) aiDlg.close();
  });

  // ---------- 状态下拉框：改了就提交 ----------
  $$("[data-autosubmit]").forEach((sel) => {
    const form = sel.form;
    const btn = $("[type=submit]", form);
    if (btn) btn.hidden = true;
    sel.addEventListener("change", () => (form.requestSubmit ? form.requestSubmit() : form.submit()));
  });

  // ---------- 菜单 ----------
  $$("[data-menu]").forEach((menu) => {
    const btn = $("[data-menu-btn]", menu);
    const pop = $(".menu-pop", menu);
    const close = () => { pop.hidden = true; btn.setAttribute("aria-expanded", "false"); };
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const open = pop.hidden;
      $$(".menu-pop").forEach((p) => { p.hidden = true; });
      pop.hidden = !open;
      btn.setAttribute("aria-expanded", String(open));
    });
    document.addEventListener("click", (e) => { if (!menu.contains(e.target)) close(); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
  });

  // ---------- Overview 按状态筛选 ----------
  $$("[data-filters]").forEach((bar) => {
    const list = document.getElementById(bar.dataset.filters);
    $$(".chip", bar).forEach((chip) => chip.addEventListener("click", () => {
      $$(".chip", bar).forEach((c) => { c.classList.toggle("active", c === chip); c.setAttribute("aria-pressed", String(c === chip)); });
      const f = chip.dataset.filter;
      $$(".project-card", list).forEach((row, i) => {
        const show = f === "all" || row.dataset.status === f;
        row.classList.toggle("is-hidden", !show);
        if (show && !reduceMotion) {
          row.style.animation = "none";
          void row.offsetWidth; // 重新触发动画
          row.style.animation = `fade-up .4s var(--ease-out) ${i * 30}ms both`;
        }
      });
      const empty = $("[data-filter-empty]", list.parentElement);
      if (empty) empty.hidden = $$(".project-card:not(.is-hidden)", list).length > 0;
    }));
  });

  // ---------- 复制按钮 ----------
  $$("[data-copy]").forEach((btn) => btn.addEventListener("click", async () => {
    const target = document.getElementById(btn.dataset.copy);
    const text = "value" in target ? target.value : target.innerText;
    try {
      await navigator.clipboard.writeText(text);
    } catch (e) {
      if (target.select) { target.select(); document.execCommand("copy"); }
    }
    const label = btn.innerHTML;
    btn.innerHTML = '<i class="ph ph-check"></i> Copied';
    setTimeout(() => { btn.innerHTML = label; }, 1800);
  }));

  // ---------- 字数统计 ----------
  $$("textarea[maxlength][data-count]").forEach((ta) => {
    const out = document.createElement("div");
    out.className = "char-count";
    ta.after(out);
    const update = () => {
      const max = +ta.maxLength;
      out.textContent = `${ta.value.length} / ${max}`;
      out.classList.toggle("warn", ta.value.length > max * 0.9);
    };
    ta.addEventListener("input", update);
    update();
  });

  // ---------- 显示 / 隐藏密码 ----------
  $$("[data-pw-toggle]").forEach((btn) => btn.addEventListener("click", () => {
    const input = btn.parentElement.querySelector("input");
    const show = input.type === "password";
    input.type = show ? "text" : "password";
    btn.innerHTML = show ? '<i class="ph ph-eye-slash"></i>' : '<i class="ph ph-eye"></i>';
    btn.setAttribute("aria-label", show ? "Hide password" : "Show password");
  }));

  // ---------- 彩带 ----------
  function confetti() {
    if (reduceMotion) return;
    const box = document.createElement("div");
    box.className = "confetti";
    const colors = ["var(--green)", "var(--yellow)", "var(--red)", "var(--text)"];
    for (let i = 0; i < 70; i++) {
      const p = document.createElement("i");
      p.style.left = Math.random() * 100 + "vw";
      p.style.background = colors[i % colors.length];
      p.style.setProperty("--x", (Math.random() * 200 - 100) + "px");
      p.style.setProperty("--r", (Math.random() * 720 - 360) + "deg");
      p.style.setProperty("--d", (1.2 + Math.random() * 1.2) + "s");
      p.style.setProperty("--delay", (Math.random() * 0.3) + "s");
      box.appendChild(p);
    }
    document.body.appendChild(box);
    setTimeout(() => box.remove(), 3000);
  }

  // ---------- 任务步骤：打勾、编辑、删除、新增、拖拽排序（全部局部刷新） ----------
  async function send(url, data) {
    const res = await fetch(url, { method: "POST", body: data, headers: { "X-Requested-With": "fetch" } });
    let json = null;
    try { json = await res.json(); } catch (e) { /* 非 JSON（比如 400 表单过期） */ }
    if (!res.ok || !json || !json.ok) throw new Error((json && json.error) || "Could not save. Refresh the page and try again.");
    return json;
  }
  const csrf = () => ($("meta[name=csrf-token]") || {}).content || "";
  const formData = (obj) => {
    const fd = new FormData();
    fd.append("_csrf_token", csrf());
    Object.entries(obj || {}).forEach(([k, v]) => fd.append(k, v));
    return fd;
  };

  function applyProgress(p) {
    if (!p || !p.progress) return;
    const { done, total, pct } = p.progress;
    $$("[data-progress-line]").forEach((el) => el.style.setProperty("--pct", pct));
    $$("[data-progress-text]").forEach((el) => { el.textContent = total ? `${done} / ${total} tasks done` : "No tasks yet"; });
    $$("[data-task-empty]").forEach((el) => { el.hidden = total > 0; });
  }

  function updateCount(list) {
    const counter = list.dataset.counter && document.getElementById(list.dataset.counter);
    if (counter) counter.textContent = $$(".task:not(.leaving)", list).length;
    const empty = list.dataset.empty && document.getElementById(list.dataset.empty);
    if (empty) empty.hidden = $$(".task:not(.leaving)", list).length > 0;
  }

  function removeRow(row, after) {
    const list = row.parentElement;
    row.classList.add("leaving");
    updateCount(list);
    setTimeout(() => {
      const group = row.closest("[data-agenda-day]");
      row.remove();
      if (group && !$(".task", group)) group.remove();
      if (after) after();
    }, reduceMotion ? 0 : 350);
  }

  function startEdit(row) {
    if ($(".task-edit", row)) return;
    const body = $(".body", row);
    const form = document.createElement("form");
    form.className = "task-edit";
    form.innerHTML = `
      <input class="title-input" type="text" name="title" maxlength="200" required aria-label="Task name">
      <input type="date" name="due_date" aria-label="Date">
      <input type="number" name="minutes" min="5" max="600" step="5" placeholder="Minutes" aria-label="Estimated minutes">
      <div class="btn-row"><button class="btn small" type="submit">Save</button><button class="btn small ghost" type="button" data-cancel>Cancel</button></div>`;
    form.title.value = row.dataset.title;
    form.due_date.value = row.dataset.due;
    form.minutes.value = row.dataset.minutes;
    form.dataset.ajax = "1";
    body.hidden = true;
    $(".actions", row).hidden = true;
    body.after(form);
    form.title.focus();
    form.title.select();
    const cancel = () => { form.remove(); body.hidden = false; $(".actions", row).hidden = false; };
    $("[data-cancel]", form).addEventListener("click", cancel);
    form.addEventListener("keydown", (e) => { if (e.key === "Escape") cancel(); });
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      try {
        const res = await send(row.dataset.updateUrl, formData({
          title: form.title.value, due_date: form.due_date.value, minutes: form.minutes.value,
        }));
        const tmp = document.createElement("template");
        tmp.innerHTML = res.html.trim();
        const fresh = tmp.content.firstElementChild;
        row.replaceWith(fresh);
        bindRow(fresh);
      } catch (err) { toast(err.message, "error"); }
    });
  }

  function bindRow(row) {
    const list = row.closest("[data-task-list]");
    const agenda = list && list.dataset.mode === "agenda";
    const toggle = $("form.toggle-form", row);
    if (toggle) {
      toggle.dataset.ajax = "1";
      toggle.addEventListener("submit", async (e) => {
        e.preventDefault();
        const wasDone = row.classList.contains("is-done");
        row.classList.toggle("is-done");      // 先改界面，失败再改回来
        try {
          const res = await send(toggle.action, new FormData(toggle));
          applyProgress(res);
          if (res.message) { toast(res.message); confetti(); }
          if (agenda && !wasDone) setTimeout(() => removeRow(row, () => bumpDoneToday()), 450);
        } catch (err) {
          row.classList.toggle("is-done", wasDone);
          toast(err.message, "error");
        }
      });
    }
    const edit = $("[data-edit]", row);
    if (edit) edit.addEventListener("click", () => startEdit(row));
    $(".title", row) && !agenda && $(".title", row).addEventListener("dblclick", () => startEdit(row));
    const del = $("form.delete-form", row);
    if (del) {
      del.dataset.ajax = "1";
      del.addEventListener("submit", async (e) => {
        e.preventDefault();
        try {
          const res = await send(del.action, new FormData(del));
          removeRow(row);
          applyProgress(res);
        } catch (err) { toast(err.message, "error"); }
      });
    }
  }

  function bumpDoneToday() {
    $$("[data-done-today]").forEach((el) => { el.textContent = (+el.textContent || 0) + 1; });
  }

  $$("[data-task-list]").forEach((list) => {
    $$(".task", list).forEach(bindRow);
    if (list.dataset.reorderUrl) enableDrag(list);
  });

  // 新增步骤：回车即可添加，添加后输入框保持焦点，可以连续输入
  $$("[data-composer]").forEach((form) => {
    form.dataset.ajax = "1";
    const list = document.getElementById(form.dataset.composer);
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const btn = $("[type=submit]", form);
      btn.classList.add("is-loading");
      try {
        const res = await send(form.action, new FormData(form));
        const tmp = document.createElement("template");
        tmp.innerHTML = res.html.trim();
        const row = tmp.content.firstElementChild;
        row.classList.add("entering");
        list.appendChild(row);
        bindRow(row);
        applyProgress(res);
        updateCount(list);
        form.title.value = "";
        form.minutes.value = "";
        form.title.focus();
      } catch (err) {
        toast(err.message, "error");
      } finally {
        btn.classList.remove("is-loading");
      }
    });
  });

  // 拖拽排序：只能从左边的把手开始拖
  function enableDrag(list) {
    let dragging = null;
    list.addEventListener("pointerdown", (e) => {
      const handle = e.target.closest(".drag-handle");
      if (handle) handle.closest(".task").draggable = true;
    });
    list.addEventListener("dragstart", (e) => {
      dragging = e.target.closest(".task");
      if (!dragging) return;
      dragging.classList.add("dragging");
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", dragging.dataset.id);
    });
    list.addEventListener("dragover", (e) => {
      if (!dragging) return;
      e.preventDefault();
      const over = e.target.closest(".task");
      $$(".drop-before, .drop-after", list).forEach((r) => r.classList.remove("drop-before", "drop-after"));
      if (!over || over === dragging) return;
      const after = e.clientY > over.getBoundingClientRect().top + over.offsetHeight / 2;
      over.classList.add(after ? "drop-after" : "drop-before");
    });
    list.addEventListener("drop", async (e) => {
      if (!dragging) return;
      e.preventDefault();
      const over = e.target.closest(".task");
      if (over && over !== dragging) {
        const after = over.classList.contains("drop-after");
        over.after && (after ? over.after(dragging) : over.before(dragging));
        try {
          await send(list.dataset.reorderUrl, formData({ ids: $$(".task", list).map((r) => r.dataset.id).join(",") }));
        } catch (err) { toast(err.message, "error"); }
      }
    });
    list.addEventListener("dragend", () => {
      if (dragging) { dragging.classList.remove("dragging"); dragging.draggable = false; }
      $$(".drop-before, .drop-after", list).forEach((r) => r.classList.remove("drop-before", "drop-after"));
      dragging = null;
    });
  }

  // ---------- AI 拆解草稿：增删行 ----------
  $$("[data-draft]").forEach((box) => {
    const tpl = $("template[data-row-template]");
    const renumber = () => $$(".draft-row", box).forEach((r, i) => { $(".idx", r).textContent = i + 1; });
    box.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-remove]");
      if (!btn) return;
      const row = btn.closest(".draft-row");
      row.classList.add("leaving");
      setTimeout(() => { row.remove(); renumber(); }, reduceMotion ? 0 : 250);
    });
    $$("[data-add-row]").forEach((btn) => btn.addEventListener("click", () => {
      const row = tpl.content.firstElementChild.cloneNode(true);
      row.classList.add("entering");
      box.appendChild(row);
      renumber();
      $("input", row).focus();
    }));
  });
  // ---------- 推送通知：在这台设备上开启 / 关闭（需要 https 或 localhost） ----------
  const pushBox = $("[data-push]");
  if (pushBox) {
    const status = $("[data-push-status]", pushBox);
    const enableBtn = $("[data-push-enable]", pushBox);
    const disableBtn = $("[data-push-disable]", pushBox);
    const supported = "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
    const b64ToBytes = (text) => {
      const raw = atob((text + "=".repeat((4 - (text.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/"));
      return Uint8Array.from(raw, (c) => c.charCodeAt(0));
    };
    const currentSub = async () => {
      const reg = await navigator.serviceWorker.getRegistration("/");
      return reg ? reg.pushManager.getSubscription() : null;
    };
    const show = (text, mode) => {
      status.textContent = text;
      enableBtn.hidden = mode !== "off";
      disableBtn.hidden = mode !== "on";
    };
    async function render() {
      if (!window.isSecureContext) return show("Push notifications need a secure (https) connection.", "none");
      if (!supported) return show("This browser doesn't support push notifications. On an iPhone, add this site to your Home Screen first.", "none");
      if (Notification.permission === "denied") return show("Notifications are blocked for this site. Allow them in your browser's site settings, then reload.", "none");
      try {
        const sub = await currentSub();
        show(sub ? "Enabled on this device." : "Not enabled on this device.", sub ? "on" : "off");
      } catch (e) { show("Could not check this browser.", "none"); }
    }
    enableBtn.addEventListener("click", async () => {
      enableBtn.classList.add("is-loading");
      try {
        if ((await Notification.requestPermission()) !== "granted") { await render(); return; }
        const reg = await navigator.serviceWorker.register("/sw.js");
        await navigator.serviceWorker.ready;
        const old = await reg.pushManager.getSubscription();
        if (old) await old.unsubscribe();  // 服务器的密钥换过时，旧订阅不能复用
        const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToBytes(pushBox.dataset.vapidKey) });
        const json = sub.toJSON();
        try {
          await send(pushBox.dataset.subscribeUrl, formData({ endpoint: json.endpoint, p256dh: json.keys.p256dh, auth: json.keys.auth }));
        } catch (err) { await sub.unsubscribe(); throw err; }
        toast("Push notifications enabled on this device.");
        setTimeout(() => location.reload(), 600);  // 刷新后设备列表和开关才会更新
      } catch (err) {
        toast("Could not enable push: " + (err.message || err), "error");
        await render();
      } finally { enableBtn.classList.remove("is-loading"); }
    });
    disableBtn.addEventListener("click", async () => {
      disableBtn.classList.add("is-loading");
      try {
        const sub = await currentSub();
        if (sub) {
          const endpoint = sub.endpoint;
          await sub.unsubscribe();
          await send(pushBox.dataset.unsubscribeUrl, formData({ endpoint }));
        }
        toast("Push notifications turned off on this device.");
        setTimeout(() => location.reload(), 600);
      } catch (err) { toast(err.message || "Could not turn off push.", "error"); } finally { disableBtn.classList.remove("is-loading"); }
    });
    render();
  }

  // ---------- 时区：默认值还是 UTC 时自动选这台设备的时区，否则只给个建议 ----------
  const tzSelect = $("[data-timezone]");
  if (tzSelect) {
    try {
      const detected = Intl.DateTimeFormat().resolvedOptions().timeZone;
      const hint = $("[data-tz-hint]");
      const known = [...tzSelect.options].some((o) => o.value === detected);
      if (detected && known && detected !== tzSelect.value) {
        if (tzSelect.dataset.default === "UTC") {
          tzSelect.value = detected;
          hint.textContent = `Detected from this device: ${detected}. Save to keep it.`;
        } else {
          hint.innerHTML = `This device is in ${detected}. <button class="link" type="button" style="background:none;border:0;padding:0;cursor:pointer;font:inherit;">Use it</button>`;
          $("button", hint).addEventListener("click", () => { tzSelect.value = detected; hint.textContent = "Save to keep it."; });
        }
        hint.hidden = false;
      }
    } catch (e) { /* 浏览器不支持就保持原样 */ }
  }
})();
