/**
 * main.js – TaxPro HRMS client-side utilities (Phase 1)
 *
 * Phase 1: Minimal JS for UX polish only.
 * Phase 2: Add Chart.js for TDS timeline graphs,
 *          AJAX for payroll polling, WebSocket for real-time notifications.
 */

'use strict';

// ── Auto-dismiss flash messages ────────────────────────────
document.addEventListener('DOMContentLoaded', () => {

  // Dismiss flash alerts after 5 seconds
  const flashes = document.querySelectorAll('[class*="bg-emerald-9"], [class*="bg-red-9"], [class*="bg-amber-9"], [class*="bg-brand-9"]');
  flashes.forEach(el => {
    if (el.closest('main') || el.closest('.px-6')) {
      setTimeout(() => {
        el.style.transition = 'opacity 0.5s ease';
        el.style.opacity = '0';
        setTimeout(() => el.remove(), 500);
      }, 5000);
    }
  });

  // ── Confirm on destructive actions ──────────────────────
  document.querySelectorAll('[data-confirm]').forEach(btn => {
    btn.addEventListener('click', e => {
      if (!confirm(btn.dataset.confirm)) e.preventDefault();
    });
  });

  // ── Number input: format with commas on blur ────────────
  document.querySelectorAll('input[type="number"]').forEach(input => {
    input.addEventListener('wheel', e => e.preventDefault()); // disable scroll
  });

  // ── Active nav link highlight (fallback) ────────────────
  const currentPath = window.location.pathname;
  document.querySelectorAll('.nav-link').forEach(link => {
    if (link.getAttribute('href') === currentPath) {
      link.classList.add('nav-link-active');
    }
  });

  // ── Form loading state ──────────────────────────────────
  document.querySelectorAll('form').forEach(form => {
    form.addEventListener('submit', () => {
      const btn = form.querySelector('button[type="submit"]');
      if (btn) {
        const originalText = btn.textContent;
        const originalOpacity = btn.style.opacity;
        btn.disabled = true;
        btn.style.opacity = '0.7';
        btn.textContent = 'Processing…';

        // Reset button state after 30 seconds as a safety net
        setTimeout(() => {
          btn.disabled = false;
          btn.style.opacity = originalOpacity;
          btn.textContent = originalText;
        }, 30000);
      }
    });
  });

  console.log('TaxPro HRMS · Phase 1 Prototype · JS loaded');
});
