import React, { useCallback, useEffect, useState } from 'react';
import {
  LayoutDashboard, Users, Route, ListOrdered, FileText, Shield, LogOut, ClipboardCheck, BarChart3, Monitor,
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

const NAV = [
  { id: 'dashboard', icon: LayoutDashboard, labelKey: 'admin.navDashboard' },
  { id: 'agents', icon: Users, labelKey: 'admin.navAgents' },
  { id: 'routing', icon: Route, labelKey: 'admin.navRouting' },
  { id: 'queue', icon: ListOrdered, labelKey: 'admin.navQueue' },
  { id: 'audit', icon: FileText, labelKey: 'admin.navAudit' },
  { id: 'qc', icon: Shield, labelKey: 'admin.navQc' },
  { id: 'approvals', icon: ClipboardCheck, labelKey: 'admin.navApprovals' },
  { id: 'reports', icon: BarChart3, labelKey: 'admin.navReports' },
  { id: 'ops', icon: Monitor, labelKey: 'admin.navOps' },
];

/** 008 管理员运营后台 Shell */
export default function AdminShell({ user, legacyRouting }) {
  const [tab, setTab] = useState('dashboard');
  const [demo, setDemo] = useState(null);
  const [demoBusy, setDemoBusy] = useState(false);

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
      else window.alert(data.message || data.error || '演示数据操作失败');
    } catch (e) {
      console.error(e);
      window.alert('演示数据操作失败，请稍后重试');
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
      <aside className="md:w-60 border-b md:border-b-0 md:border-r border-slate-200 bg-white/95 backdrop-blur p-4 flex md:flex-col gap-1 overflow-x-auto">
        <div className="hidden md:block mb-4 px-2">
          <p className="inline-flex px-2 py-1 rounded-full bg-[var(--mitako-lime-soft)] border border-slate-200 text-xs font-black text-[var(--mitako-ink)] uppercase tracking-wider">{t('admin.badge')}</p>
          <p className="text-base font-black mt-3">{t('admin.shellTitle')}</p>
          <p className="text-[11px] text-slate-500 mt-1">{user?.display_name || user?.username}</p>
        </div>
        {NAV.map(({ id, icon: Icon, labelKey }) => (
          <button
            key={id}
            type="button"
            onClick={() => setTab(id)}
            aria-current={tab === id ? 'page' : undefined}
            className={`flex items-center gap-2 px-3 py-2.5 rounded-[8px] text-sm font-bold whitespace-nowrap transition-colors border ${
              tab === id ? 'bg-[var(--mitako-lime)] text-[var(--mitako-ink)] border-transparent shadow-[0_10px_24px_rgba(127,164,49,.18)]' : 'text-slate-600 border-transparent hover:bg-slate-100'
            }`}
          >
            <Icon className="w-4 h-4" />
            {t(labelKey)}
          </button>
        ))}
        <div className="flex-1" />
        <a href="/desk" target="_blank" rel="noopener noreferrer" className="text-xs text-[var(--mitako-ink)] bg-white border border-slate-200 rounded-[8px] font-bold px-3 py-2 hover:bg-[var(--mitako-lime-soft)]">{t('admin.openDesk')}</a>
        <button type="button" onClick={logout} className="flex items-center gap-2 px-3 py-2 text-xs text-slate-500 hover:text-rose-600">
          <LogOut className="w-3.5 h-3.5" /> {t('admin.logout')}
        </button>
      </aside>
      <main className="flex-1 min-w-0 overflow-auto">
        <div className="sticky top-0 z-20 border-b border-slate-200 bg-white/90 backdrop-blur px-4 sm:px-6 py-3 flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-sm font-black text-slate-950">客服运营管理中心</p>
            <p className="text-xs text-slate-500">{demo?.message || '正在读取数据状态'}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className={`rounded-[8px] px-2 py-1 text-[11px] font-bold ${demo?.mode === 'demo' ? 'bg-[var(--mitako-lime-soft)] text-slate-900' : 'bg-slate-100 text-slate-600'}`}>
              {demo?.mode === 'demo' ? `演示数据 ${demo.session_count || 0} 条` : '空状态/待接入'}
            </span>
            <button type="button" disabled={demoBusy} onClick={() => runDemoAction('load')} className="min-h-[36px] rounded-[8px] bg-[var(--mitako-lime)] px-3 text-xs font-bold text-slate-950 disabled:opacity-60">
              加载演示数据
            </button>
            <button
              type="button"
              disabled={demoBusy}
              onClick={() => {
                if (window.confirm('确认清空演示数据？真实接口数据不会被删除。')) runDemoAction('clear');
              }}
              className="min-h-[36px] rounded-[8px] bg-white border border-slate-200 px-3 text-xs font-bold text-slate-700 disabled:opacity-60"
            >
              清空演示数据
            </button>
          </div>
        </div>
        {tab === 'dashboard' && <Dashboard />}
        {tab === 'agents' && <AgentManagement />}
        {tab === 'routing' && <RoutingRules />}
        {tab === 'queue' && <QueueMonitor />}
        {tab === 'audit' && <AuditLog />}
        {tab === 'qc' && <ObserverQC />}
        {tab === 'approvals' && <Approvals user={user} />}
        {tab === 'reports' && <Reports />}
        {tab === 'ops' && <OpsMonitor />}
      </main>
    </div>
  );
}
