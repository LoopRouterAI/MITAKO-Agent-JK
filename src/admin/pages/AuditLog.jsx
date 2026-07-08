import React, { useCallback, useEffect, useState } from 'react';
import t from '../../i18n/index.js';
import { authFetch } from '../../lib/authClient.js';
import { sanitizePublicText } from '../../utils/publicText.js';

export default function AuditLog() {
  const [events, setEvents] = useState([]);
  const [selected, setSelected] = useState('');
  const [transcript, setTranscript] = useState(null);
  const [eventType, setEventType] = useState('');

  const shortCode = (value = '', prefix = '服务单') => {
    const text = String(value || '').trim();
    if (!text) return `${prefix} -`;
    const compact = text.replace(/[^a-zA-Z0-9]/g, '');
    return `${prefix} #${(compact || text).slice(-6).toUpperCase()}`;
  };

  const publicEventType = (type = '') => String(type || '').replace('multimodal_fixture', 'material_review');

  const eventBusinessNo = (ev = {}) => {
    const sessionNo = shortCode(ev.session_id, '服务单');
    return ev.order_id ? `${sessionNo} / ${shortCode(ev.order_id, '关联单')}` : sessionNo;
  };

  const eventLabel = (type) => ({
    sop_branch: '服务类型识别',
    material_review: '材料校验',
    service_transfer_blocked: 'VIP客服接手留痕',
    service_after_sales_card: '售后处理单',
    service_warehouse_task: '仓库核查任务',
    service_ticket: '客服复核工单',
    service_qc_sop_proposal: '质检建议',
    service_private_domain_task: '后续跟进任务',
    accept: 'VIP客服接单',
    escalate: '升级处理',
    transfer: '同事转交',
    user: '用户消息',
    assistant: 'AI客服回复',
    observer: '服务记录',
  }[publicEventType(type)] || '业务记录');

  const statusLabel = (status) => ({
    service_only: '已记录',
    planned: '已规划',
    drafted: '已生成',
    matched: '已匹配',
    checked: '已核验',
    ready_for_dispatch: '待派发',
    ready_for_human_review: '待复核',
  }[publicEventType(status)] || '已记录');

  const sourceLabel = (source) => ({
    handoff: '转接记录',
    business: '业务记录',
    message: '会话消息',
    observer: '辅助记录',
  }[source] || '业务记录');

  const load = useCallback(async () => {
    const qs = eventType ? `&event_type=${encodeURIComponent(eventType)}` : '';
    const r = await authFetch(`/api/v1/admin/audit/events?limit=120${qs}`);
    const data = await r.json();
    if (data.ok) setEvents(data.events || []);
  }, [eventType]);

  useEffect(() => { load(); }, [load]);

  const openSession = async (sid) => {
    setSelected(sid);
    const r = await authFetch(`/api/v1/admin/audit/sessions/${encodeURIComponent(sid)}/transcript`);
    const data = await r.json();
    if (data.ok) setTranscript(data);
  };

  const describeEvent = (ev) => {
    const result = ev.result || {};
    if (ev.audit_source === 'message') return sanitizePublicText(ev.content?.slice(0, 220) || '');
    if (ev.event_type === 'sop_branch') return sanitizePublicText(`${result.sop_branch || '服务类型'} · ${result.ticket_type || ''}`);
    if (publicEventType(ev.event_type).startsWith('service_')) {
      const action = eventLabel(ev.event_type);
      const human = result.requires_human ? ` · ${t('admin.auditNeedsHuman')}` : '';
      return sanitizePublicText(`${action}${human} ${result.reason || result.next_step || ''}`.trim());
    }
    return sanitizePublicText(ev.note || ev.status || '');
  };

  const timeline = transcript ? [
    ...(transcript.messages || []).map(m => ({ ...m, audit_source: 'message', event_type: m.role, status: m.agent_id || '' })),
    ...(transcript.events || []).map(e => ({ ...e, audit_source: 'handoff' })),
    ...(transcript.business_events || []).map(e => ({ ...e, audit_source: 'business' })),
  ].sort((a, b) => (a.created_at || 0) - (b.created_at || 0)) : [];

  return (
    <div className="p-6 grid lg:grid-cols-2 gap-6">
      <div>
        <div className="flex items-center justify-between gap-3 mb-4">
          <h1 className="text-xl font-bold text-[var(--mitako-ink)]">{t('admin.navAudit')}</h1>
          <select value={eventType} onChange={e => setEventType(e.target.value)} className="rounded-[8px] border-2 border-[var(--mitako-ink)] bg-white px-3 py-2 text-xs font-bold shadow-[3px_3px_0_#111]">
            <option value="">{t('admin.auditAll')}</option>
            <option value="sop_branch">{t('admin.auditSopBranch')}</option>
            <option value="service_after_sales_card">{t('admin.auditAfterSalesCard')}</option>
            <option value="service_warehouse_task">{t('admin.auditWarehouseTask')}</option>
            <option value="accept">{t('admin.auditAccept')}</option>
          </select>
        </div>
        <ul className="space-y-2 max-h-[70vh] overflow-auto">
          {events.map(ev => (
            <li key={`${ev.session_id}-${ev.id}-${ev.created_at}`}>
              <button type="button" onClick={() => openSession(ev.session_id)} className="w-full text-left rounded-[8px] border-2 border-[var(--mitako-ink)] bg-white px-3 py-2 text-xs shadow-[3px_3px_0_#111] transition-transform hover:-translate-y-0.5 hover:bg-[var(--mitako-lime)]">
                <span className="font-bold text-[var(--mitako-ink)]">{eventLabel(ev.event_type)}</span>
                <span className="ml-2 rounded-[8px] border border-[var(--mitako-ink)] bg-white px-1.5 py-0.5 text-[10px] font-bold text-[var(--mitako-ink)]">{sourceLabel(ev.audit_source || 'handoff')}</span>
                <p className="mt-1 text-slate-600">{eventBusinessNo(ev)}</p>
              </button>
            </li>
          ))}
        </ul>
      </div>
      <div>
        <h2 className="font-bold text-sm mb-2 text-[var(--mitako-ink)]">{selected ? shortCode(selected, '服务单') : t('admin.pickSessionAudit')}</h2>
        {transcript && (
          <div className="rounded-[8px] border-2 border-[var(--mitako-ink)] bg-white p-4 text-xs space-y-3 max-h-[70vh] overflow-auto shadow-[4px_4px_0_#111]">
            {!!timeline.length && (
              <div className="space-y-2">
                <h3 className="font-bold text-[var(--mitako-ink)]">{t('admin.auditTimeline')}</h3>
                {timeline.map((ev, i) => (
                  <div key={`${ev.audit_source}-${ev.id || i}-${ev.event_type}`} className="rounded-[8px] border-2 border-[var(--mitako-ink)] bg-[#F7F7F2] p-2">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-bold text-[11px] break-all text-[var(--mitako-ink)]">{eventLabel(ev.event_type)}</span>
                      <span className="rounded-[8px] bg-white px-1.5 py-0.5 text-[10px] font-bold text-[var(--mitako-ink)] border border-[var(--mitako-ink)]">{sourceLabel(ev.audit_source)}</span>
                    </div>
                    <p className="mt-1 text-slate-600 break-words">{describeEvent(ev)}</p>
                    {(ev.session_id || ev.order_id) && (
                      <p className="mt-1 text-[10px] font-bold text-slate-500">{eventBusinessNo(ev)}</p>
                    )}
                  </div>
                ))}
              </div>
            )}
            {!!(transcript.business_events || []).length && (
              <div className="border-t-2 border-[var(--mitako-ink)] pt-3 space-y-2">
                <h3 className="font-bold text-[var(--mitako-ink)]">业务审计</h3>
                {transcript.business_events.map(ev => (
                  <details key={`${ev.id}-${ev.event_type}`} className="rounded-[8px] border-2 border-[var(--mitako-ink)] bg-[#F7F7F2] p-2">
                    <summary className="cursor-pointer text-[11px] font-bold text-[var(--mitako-ink)]">{eventLabel(ev.event_type)} · {statusLabel(ev.status)}</summary>
                    <p className="mt-2 text-[11px] text-slate-600 break-words">{describeEvent(ev) || '已记录业务处理进度'}</p>
                  </details>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
