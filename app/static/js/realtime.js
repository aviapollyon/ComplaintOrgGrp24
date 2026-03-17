(function () {
  if (window.__complaintOrgRealtimeInitialized) {
    return;
  }
  window.__complaintOrgRealtimeInitialized = true;

  var body = document.body;
  var realtimeDisabled = body && body.dataset.realtimeEnabled === '0';
  if (!body || body.dataset.authenticated !== '1' ||
      realtimeDisabled || !window.fetch) {
    return;
  }

  var enableToasts = body.dataset.realtimeToasts === '1';
  var reloadTimer = null;
  var pollTimer = null;
  var pollInFlight = false;
  var consecutiveFailures = 0;
  var leaderHeartbeatTimer = null;
  var lastUserNotifId = null;
  var lastAdminNotifId = null;

  var basePollIntervalMs = Math.max(5000, parseInt(body.dataset.pollIntervalMs || '10000', 10) || 10000);
  var maxBackoffMs = Math.max(basePollIntervalMs, parseInt(body.dataset.pollMaxBackoffMs || '30000', 10) || 30000);
  var requestTimeoutMs = Math.max(2000, parseInt(body.dataset.pollTimeoutMs || '8000', 10) || 8000);

  var tabId = 'tab_' + Math.random().toString(36).slice(2);
  var leaderKey = 'complaintorg-realtime-leader';
  var heartbeatMs = 4000;
  var leaderTtlMs = 12000;

  function scheduleReload(delayMs) {
    if (reloadTimer) {
      return;
    }
    reloadTimer = window.setTimeout(function () {
      window.location.reload();
    }, delayMs || 1200);
  }

  function ensureBadge(anchor, cssClass) {
    if (!anchor) {
      return null;
    }
    var badge = anchor.querySelector('.badge');
    if (!badge) {
      badge = document.createElement('span');
      badge.className = 'position-absolute top-0 start-100 translate-middle badge rounded-pill ' + cssClass;
      badge.style.fontSize = '.6rem';
      badge.style.minWidth = '1.1rem';
      anchor.appendChild(badge);
    }
    return badge;
  }

  function incrementBellCount(selector, cssClass) {
    var anchor = document.querySelector(selector);
    if (!anchor) {
      return;
    }
    var badge = ensureBadge(anchor, cssClass);
    if (!badge) {
      return;
    }
    var currentText = (badge.textContent || '').trim();
    var count = parseInt(currentText, 10);
    if (isNaN(count)) {
      count = 0;
    }
    count += 1;
    badge.textContent = count > 99 ? '99+' : String(count);
  }

  function setBellCount(selector, cssClass, count) {
    var anchor = document.querySelector(selector);
    if (!anchor) {
      return;
    }
    var badge = ensureBadge(anchor, cssClass);
    if (!badge) {
      return;
    }
    var value = Number(count);
    if (!isFinite(value) || value <= 0) {
      badge.remove();
      return;
    }
    badge.textContent = value > 99 ? '99+' : String(value);
  }

  function showToast(message) {
    var container = document.getElementById('realtime-toast-container');
    if (!container) {
      container = document.createElement('div');
      container.id = 'realtime-toast-container';
      container.className = 'toast-container position-fixed top-0 end-0 p-3';
      container.style.zIndex = '1200';
      document.body.appendChild(container);
    }

    var toastEl = document.createElement('div');
    toastEl.className = 'toast align-items-center text-bg-primary border-0';
    toastEl.setAttribute('role', 'alert');
    toastEl.setAttribute('aria-live', 'assertive');
    toastEl.setAttribute('aria-atomic', 'true');
    toastEl.innerHTML = '<div class="d-flex">' +
      '<div class="toast-body">' + message + '</div>' +
      '<button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>' +
      '</div>';
    container.appendChild(toastEl);

    if (window.bootstrap && window.bootstrap.Toast) {
      var toast = new window.bootstrap.Toast(toastEl, { delay: 3500 });
      toast.show();
      toastEl.addEventListener('hidden.bs.toast', function () {
        toastEl.remove();
      });
    }
  }

  function shouldSoftReload(payload) {
    var path = window.location.pathname;
    if (path.indexOf('/dashboard') !== -1 || path.indexOf('/notifications') !== -1) {
      return true;
    }
    if (payload && payload.ticket_id) {
      if (path.indexOf('/ticket') !== -1 || path.indexOf('/tickets') !== -1 || path.indexOf('/new-tickets') !== -1) {
        return true;
      }
      if (path.indexOf('/student/') !== -1 || path.indexOf('/staff/') !== -1 || path.indexOf('/admin/') !== -1) {
        return true;
      }
    }
    if (payload && payload.action && payload.action.indexOf('ticket_') === 0) {
      return true;
    }
    if (path.indexOf('/community') !== -1 || path.indexOf('/pending-actions') !== -1 ||
        path.indexOf('/new-tickets') !== -1 || path.indexOf('/recurring-issues') !== -1) {
      return true;
    }
    return false;
  }

  var pollUrl = '/user/notifications/poll';

  function parseLeader(raw) {
    if (!raw) {
      return null;
    }
    try {
      return JSON.parse(raw);
    } catch (e) {
      return null;
    }
  }

  function nowMs() {
    return Date.now();
  }

  function readLeader() {
    return parseLeader(window.localStorage.getItem(leaderKey));
  }

  function writeLeader() {
    window.localStorage.setItem(leaderKey, JSON.stringify({ id: tabId, ts: nowMs() }));
  }

  function releaseLeader() {
    var leader = readLeader();
    if (leader && leader.id === tabId) {
      window.localStorage.removeItem(leaderKey);
    }
  }

  function hasActiveLeader(leader) {
    if (!leader || !leader.id || !leader.ts) {
      return false;
    }
    return (nowMs() - leader.ts) < leaderTtlMs;
  }

  function ensureLeadership() {
    var leader = readLeader();
    if (!hasActiveLeader(leader) || leader.id === tabId) {
      writeLeader();
      return true;
    }
    return false;
  }

  function scheduleNextPoll(customDelayMs) {
    if (pollTimer) {
      return;
    }
    var delay = typeof customDelayMs === 'number'
      ? customDelayMs
      : Math.min(basePollIntervalMs + (consecutiveFailures * 5000), maxBackoffMs);
    pollTimer = window.setTimeout(function () {
      pollTimer = null;
      pollOnce();
    }, delay);
  }

  function clearPollTimer() {
    if (pollTimer) {
      window.clearTimeout(pollTimer);
      pollTimer = null;
    }
  }

  function pollOnce() {
    if (pollInFlight || document.visibilityState === 'hidden' || !ensureLeadership()) {
      scheduleNextPoll();
      return;
    }
    pollInFlight = true;

    var params = new URLSearchParams();
    if (lastUserNotifId !== null) {
      params.set('last_user_notif_id', String(lastUserNotifId));
    }
    if (lastAdminNotifId !== null) {
      params.set('last_admin_notif_id', String(lastAdminNotifId));
    }

    var timeoutHandle = window.setTimeout(function () {
      pollInFlight = false;
      consecutiveFailures += 1;
      scheduleNextPoll();
    }, requestTimeoutMs);

    window.fetch(pollUrl + '?' + params.toString(), {
      method: 'GET',
      headers: { 'Accept': 'application/json' },
      cache: 'no-store',
      credentials: 'same-origin'
    })
      .then(function (response) {
        if (!response.ok) {
          throw new Error('HTTP ' + response.status);
        }
        return response.json();
      })
      .then(function (data) {
        window.clearTimeout(timeoutHandle);
        pollInFlight = false;

        if (!data || data.enabled === false) {
          clearPollTimer();
          return;
        }

        consecutiveFailures = 0;
        if (typeof data.next_last_user_notif_id === 'number') {
          lastUserNotifId = data.next_last_user_notif_id;
        }
        if (typeof data.next_last_admin_notif_id === 'number') {
          lastAdminNotifId = data.next_last_admin_notif_id;
        }

        var userNotifications = Array.isArray(data.user_notifications) ? data.user_notifications : [];
        var adminNotifications = Array.isArray(data.admin_notifications) ? data.admin_notifications : [];
        var activityEvents = Array.isArray(data.activity_events) ? data.activity_events : [];

        userNotifications.forEach(function (payload) {
          incrementBellCount('[data-user-bell="1"]', 'bg-warning text-dark');
          if (enableToasts && payload.title) {
            showToast(payload.title);
          }
          if (shouldSoftReload(payload)) {
            scheduleReload(1000);
          }
        });

        adminNotifications.forEach(function (payload) {
          incrementBellCount('[data-admin-bell="1"]', 'bg-danger');
          if (enableToasts && payload.message) {
            showToast(payload.message);
          }
          if (shouldSoftReload(payload)) {
            scheduleReload(1000);
          }
        });

        activityEvents.forEach(function (payload) {
          if (shouldSoftReload(payload)) {
            scheduleReload(700);
          }
        });

        if (typeof data.user_unread_count === 'number') {
          setBellCount('[data-user-bell="1"]', 'bg-warning text-dark', data.user_unread_count);
        }
        if (typeof data.admin_unread_count === 'number') {
          setBellCount('[data-admin-bell="1"]', 'bg-danger', data.admin_unread_count);
        }

        scheduleNextPoll(basePollIntervalMs);
      })
      .catch(function () {
        window.clearTimeout(timeoutHandle);
        pollInFlight = false;
        consecutiveFailures += 1;
        scheduleNextPoll();
      });
  }

  function startHeartbeat() {
    if (leaderHeartbeatTimer) {
      return;
    }
    leaderHeartbeatTimer = window.setInterval(function () {
      if (document.visibilityState === 'hidden') {
        return;
      }
      if (ensureLeadership()) {
        pollOnce();
      } else {
        clearPollTimer();
      }
    }, heartbeatMs);
  }

  function stopHeartbeat() {
    if (leaderHeartbeatTimer) {
      window.clearInterval(leaderHeartbeatTimer);
      leaderHeartbeatTimer = null;
    }
  }

  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'hidden') {
      clearPollTimer();
      releaseLeader();
    } else {
      pollOnce();
    }
  });

  window.addEventListener('storage', function (event) {
    if (event.key !== leaderKey || document.visibilityState === 'hidden') {
      return;
    }

    var leader = parseLeader(event.newValue);
    if (!hasActiveLeader(leader) || leader.id === tabId) {
      pollOnce();
    } else {
      clearPollTimer();
    }
  });

  window.addEventListener('pagehide', function () {
    clearPollTimer();
    releaseLeader();
    stopHeartbeat();
  });
  window.addEventListener('beforeunload', function () {
    clearPollTimer();
    releaseLeader();
    stopHeartbeat();
  });

  startHeartbeat();
  pollOnce();
})();
