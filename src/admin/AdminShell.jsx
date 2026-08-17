import React, { useCallback, useEffect, useState } from 'react';
import {
  LayoutDashboard, Users, Route, ListOrdered, FileText, Shield, LogOut, ClipboardCheck, BarChart3, Monitor,
  Network, BookOpenCheck, Cpu,
} from 'lucide-react';
import t from '../i18n/index.js';
import { authFetch, clearAuthSession } from '../lib/authClient.js';
import Dashboard from './pages/Dashboard.jsx';
import AgentManagement from './pages/AgentManagement.jsx';
import RoutingRules from './pages/RoutingRules.jsx';
import QueueMonitor from './pages/QueueMonitor.jsx';
import AuditLog from './pages/AuditLog.jsx';
import ObserverQC from './pages/ObserverQC.jsx';
import Approvals from './pages/Approvals.jsx';
import Reports from './pages/Reports.jsx';
import OpsMonitor from './pages/OpsMonitor.jsx';
import PrivateDomainAgent from './pages/PrivateDomainAgent.jsx';
import BusinessRules from './pages/BusinessRules.jsx';
import ReviewModels from './pages/ReviewModels.jsx';
import ReviewPolicies from './pages/ReviewPolicies.jsx';

const NAV = [
  { id: 'dashboard', icon: LayoutDashboard, labelKey: 'admin.navDashboard', roles: ['super_admin', 'supervisor', 'bpo_manager'] },
  { id: 'agents', icon: Users, labelKey: 'admin.navAgents', roles: ['super_admin'] },
  { id: 'routing', icon: Route, labelKey: 'admin.navRouting', roles: ['super_admin'] },
  { id: 'queue', icon: ListOrdered, labelKey: 'admin.navQueue', roles: ['super_admin', 'supervisor', 'bpo_manager'] },
  { id: 'audit', icon: FileText, labelKey: 'admin.navAudit', roles: ['super_admin', 'supervisor', 'bpo_manager'] },
  { id: 'qc', icon: Shield, labelKey: 'admin.navQc', roles: ['super_admin', 'supervisor', 'bpo_manager'] },
  { id: 'approvals', icon: ClipboardCheck, labelKey: 'admin.navApprovals', roles: ['super_admin', 'supervisor'] },
  { id: 'businessRules', icon: BookOpenCheck, labelKey: 'admin.navBusinessRules', roles: ['super_admin', 'supervisor'] },
  { id: 'reviewModels', icon: Cpu, labelKey: 'admin.navReviewModels', roles: ['super_admin'] },
  { id: 'reviewPolicies', icon: Shield, labelKey: 'admin.navReviewPolicies', roles: ['super_admin', 'supervisor'] },
  { id: 'reports', icon: BarChart3, labelKey: 'admin.navReports', roles: ['super_admin', 'supervisor', 'bpo_manager'] },
  { id: 'privateDomain', icon: Network, labelKey: 'admin.navPrivateDomain', roles: ['super_admin', 'supervisor', 'bpo_manager'] },
  { id: 'ops', icon: Monitor, labelKey: 'admin.navOps', roles: ['super_admin'] },
];

/** 008 管理员运营后台 Shell */
export default function AdminShell({ user, legacyRouting }) {
  const [tab, setTab] = useState('dashboard');
  const [demo, setDemo] = useState(null);
  const [demoBusy, setDemoBusy] = useState(false);
  const role = user?.role || 'super_admin';
  const isSuperAdmin = role === 'super_admin';
  const visibleNav = NAV.filter(item => item.roles.includes(role));

  const loadDemoStatus = useCallback(async () => {
    try {
      const r = await authFetch('/api/v1/admin/demo/status');
      const data = await r.json();
      if (data.ok) setDemo(data);
    } catch (e) {
      console.error(e);
    }
  }, []);

  useEffect(() => { loadDemoStatus(); }, [loadDemoStatus]);

  const runDemoAction = async (action) => {
    setDemoBusy(true);
    try {
      const r = await authFetch(`/api/v1/admin/demo/${action}`, { method: 'POST' });
      const data = await r.json();
      if (data.ok) setDemo(data);
      else window.alert(data.message || data.error || t('admin.demoActionFailed'));
    } catch (e) {
      console.error(e);
      window.alert(t('admin.demoActionRetry'));
    } finally {
      setDemoBusy(false);
    }
  };

  const logout = () => {
    clearAuthSession();
    window.location.reload();
  };

  return (
    <div className="min-h-[100dvh] flex flex-col md:flex-row text-slate-800 bg-[#fbfff4]">
      <aside className="md:w-60 border-b md:border-b-0 md:border-r border-slate-200 bg-white/95 backdrop-blur p-3 md:p-4 flex flex-wrap md:flex-col gap-1">
        <div className="hidden md:block mb-4 px-2">
          <p className="inline-flex px-2 py-1 rounded-full bg-[var(--mitako-lime-soft)] border border-slate-200 text-xs font-black text-[var(--mitako-ink)] uppercase tracking-wider">{t('admin.badge')}</p>
          <p className="text-base font-black mt-3">{t('admin.shellTitle')}</p>
          <p className="text-[11px] text-slate-500 mt-1">{user?.display_name || user?.username}</p>
        </div>
        <label className="md:hidden flex-1 min-w-[180px]">
          <span className="sr-only">{t('admin.navSelect')}</span>
          <select
            aria-label={t('admin.navSelect')}
            value={tab}
            onChange={event => setTab(event.target.value)}
            className="w-full min-h-[44px] rounded-[8px] border border-slate-200 bg-white px-3 text-sm font-bold text-slate-800"
          >
            {visibleNav.map(({ id, labelKey }) => <option key={id} value={id}>{t(labelKey)}</option>)}
          </select>
        </label>
        {visibleNav.map(({ id, icon: Icon, labelKey }) => (
          <button
            key={id}
            type="button"
            onClick={() => setTab(id)}
            aria-current={tab === id ? 'page' : undefined}
            className={`hidden md:flex min-h-[44px] shrink-0 items-center gap-2 px-3 py-2.5 rounded-[8px] text-sm font-bold whitespace-nowrap transition-colors border ${
              tab === id ? 'bg-[var(--mitako-lime)] text-[var(--mitako-ink)] border-transparent shadow-[0_10px_24px_rgba(127,164,49,.18)]' : 'text-slate-600 border-transparent hover:bg-slate-100'
            }`}
          >
            <Icon className="w-4 h-4" />
            {t(labelKey)}
          </button>
        ))}
        <div className="hidden md:block md:flex-1" />
        <a href="/desk" target="_blank" rel="noopener noreferrer" className="inline-flex min-h-[44px] shrink-0 items-center text-xs text-[var(--mitako-ink)] bg-white border border-slate-200 rounded-[8px] font-bold px-3 py-2 hover:bg-[var(--mitako-lime-soft)]">{t('admin.openDesk')}</a>
        <button type="button" onClick={logout} className="flex min-h-[44px] shrink-0 items-center gap-2 px-3 py-2 text-xs text-slate-500 hover:text-rose-600">
          <LogOut className="w-3.5 h-3.5" /> {t('admin.logout')}
        </button>
      </aside>
      <main className="flex-1 min-w-0 overflow-auto">
        <div className="sticky top-0 z-20 border-b border-slate-200 bg-white/90 backdrop-blur px-4 sm:px-6 py-3 flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-sm font-black text-slate-950">{t('admin.opsCenterTitle')}</p>
            <p className="text-xs text-slate-500">{demo?.message || t('admin.loadingDataStatus')}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className={`rounded-[8px] px-2 py-1 text-[11px] font-bold ${demo?.mode === 'demo' ? 'bg-[var(--mitako-lime-soft)] text-slate-900' : 'bg-slate-100 text-slate-600'}`}>
              {demo?.mode === 'demo' ? t('admin.demoDataCount', 'zh-CN', { count: demo.session_count || 0 }) : t('admin.emptyPending')}
            </span>
            {isSuperAdmin && (
              <>
                <button type="button" disabled={demoBusy} onClick={() => runDemoAction('load')} className="min-h-[44px] rounded-[8px] bg-[var(--mitako-lime)] px-3 text-xs font-bold text-slate-950 disabled:opacity-60">
                  {t('admin.loadDemoData')}
                </button>
                <button
                  type="button"
                  disabled={demoBusy}
                  onClick={() => {
                    if (window.confirm(t('admin.clearDemoConfirm'))) runDemoAction('clear');
                  }}
                  className="min-h-[44px] rounded-[8px] bg-white border border-slate-200 px-3 text-xs font-bold text-slate-700 disabled:opacity-60"
                >
                  {t('admin.clearDemoData')}
                </button>
              </>
            )}
          </div>
        </div>
        {tab === 'dashboard' && <Dashboard />}
        {tab === 'agents' && <AgentManagement />}
        {tab === 'routing' && <RoutingRules />}
        {tab === 'queue' && <QueueMonitor />}
        {tab === 'audit' && <AuditLog />}
        {tab === 'qc' && <ObserverQC />}
        {tab === 'approvals' && <Approvals user={user} />}
        {tab === 'businessRules' && <BusinessRules />}
        {tab === 'reviewModels' && <ReviewModels />}
        {tab === 'reviewPolicies' && <ReviewPolicies />}
        {tab === 'reports' && <Reports />}
        {tab === 'privateDomain' && <PrivateDomainAgent />}
        {tab === 'ops' && <OpsMonitor />}
      </main>
    </div>
  );
}
