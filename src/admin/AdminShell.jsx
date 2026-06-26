import React, { useState } from 'react';
import {
  LayoutDashboard, Users, Route, ListOrdered, FileText, Shield, LogOut, ClipboardCheck, BarChart3, Monitor,
} from 'lucide-react';
import t from '../i18n/index.js';
import { clearAuthSession } from '../lib/authClient.js';
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

  const logout = () => {
    clearAuthSession();
    window.location.reload();
  };

  return (
    <div className="min-h-[100dvh] flex flex-col md:flex-row bg-slate-50 text-slate-800">
      <aside className="md:w-56 border-b md:border-b-0 md:border-r border-slate-200 bg-white p-4 flex md:flex-col gap-1 overflow-x-auto">
        <div className="hidden md:block mb-4 px-2">
          <p className="text-xs font-bold text-[var(--mitako-purple)] uppercase tracking-wider">{t('admin.badge')}</p>
          <p className="text-sm font-bold mt-1">{t('admin.shellTitle')}</p>
          <p className="text-[11px] text-slate-500 mt-1">{user?.display_name || user?.username}</p>
        </div>
        {NAV.map(({ id, icon: Icon, labelKey }) => (
          <button
            key={id}
            type="button"
            onClick={() => setTab(id)}
            className={`flex items-center gap-2 px-3 py-2.5 rounded-xl text-sm font-semibold whitespace-nowrap transition-colors ${
              tab === id ? 'bg-[var(--mitako-purple)] text-white' : 'text-slate-600 hover:bg-slate-100'
            }`}
          >
            <Icon className="w-4 h-4" />
            {t(labelKey)}
          </button>
        ))}
        <div className="flex-1" />
        <a href="/desk" target="_blank" rel="noopener noreferrer" className="text-xs text-teal-700 font-semibold px-3 py-2">{t('admin.openDesk')}</a>
        <button type="button" onClick={logout} className="flex items-center gap-2 px-3 py-2 text-xs text-slate-500 hover:text-rose-600">
          <LogOut className="w-3.5 h-3.5" /> {t('admin.logout')}
        </button>
      </aside>
      <main className="flex-1 min-w-0 overflow-auto">
        {tab === 'dashboard' && <Dashboard />}
        {tab === 'agents' && <AgentManagement />}
        {tab === 'routing' && <RoutingRules />}
        {tab === 'queue' && <QueueMonitor />}
        {tab === 'audit' && <AuditLog />}
        {tab === 'qc' && <ObserverQC />}
        {tab === 'approvals' && <Approvals />}
        {tab === 'reports' && <Reports />}
        {tab === 'ops' && <OpsMonitor />}
      </main>
    </div>
  );
}
