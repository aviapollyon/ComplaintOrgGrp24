(function () {
  if (window.__complaintOrgRealtimeInitialized) {
    return;
  }
  window.__complaintOrgRealtimeInitialized = true;

  var body = document.body;
  if (!body || body.dataset.authenticated !== '1' || !window.EventSource) {
    return;
  }

  var enableToasts = body.dataset.realtimeToasts === '1';
  var reloadTimer = null;
  var source = null;
  var tabId = 'tab_' + Math.random().toString(36).slice(2);
  var leaderKey = 'complaintorg-realtime-leader';
  var heartbeatMs = 4000;
  var leaderTtlMs = 12000;
  var heartbeatTimer = null;

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

  var streamUrl = '/user/notifications/stream';

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

  function connectStream() {
    if (source || document.visibilityState === 'hidden' || !ensureLeadership()) {
      return;
    }
    source = new EventSource(streamUrl);

    source.addEventListener('notification', function (event) {
      var payload = {};
      try {
        payload = JSON.parse(event.data || '{}');
      } catch (e) {
        return;
      }

      incrementBellCount('[data-user-bell="1"]', 'bg-warning text-dark');
      if (enableToasts && payload.title) {
        showToast(payload.title);
      }
      if (shouldSoftReload(payload)) {
        scheduleReload(1000);
      }
    });

    source.addEventListener('admin_notification', function (event) {
      var payload = {};
      try {
        payload = JSON.parse(event.data || '{}');
      } catch (e) {
        return;
      }

      incrementBellCount('[data-admin-bell="1"]', 'bg-danger');
      if (enableToasts && payload.message) {
        showToast(payload.message);
      }
      if (shouldSoftReload(payload)) {
        scheduleReload(1000);
      }
    });

    source.addEventListener('ticket_activity', function (event) {
      var payload = {};
      try {
        payload = JSON.parse(event.data || '{}');
      } catch (e) {
        return;
      }

      if (shouldSoftReload(payload)) {
        scheduleReload(700);
      }
    });

    source.addEventListener('error', function () {
      // Close broken stream and allow reconnect when tab becomes visible again.
      disconnectStream();
    });
  }

  function disconnectStream() {
    if (source) {
      source.close();
      source = null;
    }
  }

  function startHeartbeat() {
    if (heartbeatTimer) {
      return;
    }
    heartbeatTimer = window.setInterval(function () {
      if (document.visibilityState === 'hidden') {
        return;
      }
      if (ensureLeadership()) {
        connectStream();
      } else {
        disconnectStream();
      }
    }, heartbeatMs);
  }

  function stopHeartbeat() {
    if (heartbeatTimer) {
      window.clearInterval(heartbeatTimer);
      heartbeatTimer = null;
    }
  }

  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'hidden') {
      disconnectStream();
      releaseLeader();
    } else {
      connectStream();
    }
  });

  window.addEventListener('storage', function (event) {
    if (event.key !== leaderKey || document.visibilityState === 'hidden') {
      return;
    }

    var leader = parseLeader(event.newValue);
    if (!hasActiveLeader(leader) || leader.id === tabId) {
      connectStream();
    } else {
      disconnectStream();
    }
  });

  window.addEventListener('pagehide', function () {
    disconnectStream();
    releaseLeader();
    stopHeartbeat();
  });
  window.addEventListener('beforeunload', function () {
    disconnectStream();
    releaseLeader();
    stopHeartbeat();
  });

  startHeartbeat();
  connectStream();
})();
