// MeasiConnect Main JavaScript

document.addEventListener('DOMContentLoaded', () => {
    initMobileSidebar();
    initFlashAlerts();
    initNotifications();
});

function initMobileSidebar() {
    const sidebarToggleBtn = document.getElementById('sidebar-toggle');
    const sidebarCloseBtn = document.getElementById('sidebar-close');
    const sidebar = document.getElementById('sidebar');
    const sidebarOverlay = document.getElementById('sidebar-overlay');

    const toggle = () => {
        if (sidebar) {
            sidebar.classList.toggle('-translate-x-full');
            if (sidebarOverlay) sidebarOverlay.classList.toggle('hidden');
        }
    };

    if (sidebarToggleBtn) sidebarToggleBtn.addEventListener('click', toggle);
    if (sidebarCloseBtn) sidebarCloseBtn.addEventListener('click', toggle);
    if (sidebarOverlay) {
        sidebarOverlay.addEventListener('click', () => {
            if (sidebar) sidebar.classList.add('-translate-x-full');
            sidebarOverlay.classList.add('hidden');
        });
    }
}

function initFlashAlerts() {
    document.querySelectorAll('.flash-alert').forEach((alert) => {
        setTimeout(() => {
            alert.style.opacity = '0';
            alert.style.transform = 'translateY(-10px)';
            alert.style.transition = 'opacity 0.5s ease, transform 0.5s ease';
            setTimeout(() => alert.remove(), 500);
        }, 5000);
    });
}

function initNotifications() {
    const bellBtn = document.getElementById('notification-btn');
    const bellBtnMobile = document.getElementById('notification-btn-mobile');
    const dropdown = document.getElementById('notification-dropdown');
    const badge = document.getElementById('notification-badge');
    const badgeMobile = document.getElementById('notification-badge-mobile');
    const list = document.getElementById('notification-list');
    const markReadBtn = document.getElementById('notification-mark-read');

    if (!list) return;

    const updateBadge = (count) => {
        [badge, badgeMobile].forEach(b => {
            if (!b) return;
            if (count > 0) {
                b.textContent = count;
                b.classList.remove('hidden');
            } else {
                b.classList.add('hidden');
            }
        });
    };

    const fetchAlerts = () => {
        fetch('/api/notifications')
            .then(res => res.ok ? res.json() : Promise.reject())
            .then(data => {
                updateBadge(data.unread_count);
                if (data.notifications.length === 0) {
                    list.innerHTML = '<div class="p-6 text-center text-xs text-slate-400">No notifications.</div>';
                } else {
                    list.innerHTML = data.notifications.map(n => `
                        <a href="${n.link || '#'}" class="block px-4 py-3 hover:bg-slate-50 transition-colors border-b border-slate-50 last:border-0 ${!n.read ? 'bg-gold-light/30' : ''}">
                            <div class="flex justify-between items-start gap-2">
                                <p class="text-xs font-semibold text-navy">${n.title}</p>
                                <span class="text-[9px] text-slate-400 shrink-0">${n.time_ago}</span>
                            </div>
                            <p class="text-[11px] text-slate-500 mt-0.5 line-clamp-2">${n.content}</p>
                        </a>
                    `).join('');
                }
            })
            .catch(() => {});
    };

    fetchAlerts();

    const toggleDropdown = (e) => {
        e.stopPropagation();
        if (dropdown) dropdown.classList.toggle('hidden');
        const profileDropdown = document.getElementById('profile-dropdown');
        if (profileDropdown) profileDropdown.classList.add('hidden');
    };

    if (bellBtn) bellBtn.addEventListener('click', toggleDropdown);
    if (bellBtnMobile && dropdown) {
        bellBtnMobile.addEventListener('click', toggleDropdown);
    }

    document.addEventListener('click', (e) => {
        if (dropdown && bellBtn && !dropdown.contains(e.target) && !bellBtn.contains(e.target)) {
            if (!bellBtnMobile || !bellBtnMobile.contains(e.target)) {
                dropdown.classList.add('hidden');
            }
        }
    });

    if (markReadBtn) {
        markReadBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            fetch('/api/notifications/read', { method: 'POST' })
                .then(res => res.json())
                .then(data => { if (data.success) { updateBadge(0); fetchAlerts(); } });
        });
    }

    setInterval(fetchAlerts, 60000);
}

function toggleProfileDropdown() {
    const dropdown = document.getElementById('profile-dropdown');
    if (dropdown) {
        dropdown.classList.toggle('hidden');
        const notifDropdown = document.getElementById('notification-dropdown');
        if (notifDropdown) notifDropdown.classList.add('hidden');
    }
}

function markAllAttendance(status) {
    document.querySelectorAll(`input[type="radio"][value="${status}"]`).forEach(radio => {
        radio.checked = true;
    });
}
