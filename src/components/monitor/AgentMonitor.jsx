import React from 'react';
import { Activity, Check, Terminal, Trash2 } from 'lucide-react';
import t from '../../i18n/index.js';

const panelClass = 'rounded-lg border-2 border-slate-950 bg-white shadow-[6px_6px_0_rgba(17,20,17,0.95)]';
const inputClass = 'w-full rounded-lg border-2 border-slate-950 bg-white px-3 py-2 text-sm font-semibold text-slate-800 outline-none focus-visible:ring-2 focus-visible:ring-[var(--mitako-lime)]';

function StatusBadge({ status, label }) {
  const isWorking = status === 'requesting' || status === 'retrying';
  const isError = status === 'error';
  return (
    <span className={`rounded-md border-2 border-slate-950 px-2.5 py-1 text-xs font-black ${
      isError ? 'bg-white text-red-700' : isWorking ? 'bg-[var(--mitako-lime)] text-slate-950' : 'bg-white text-slate-950'
    }`}>
      {label}
    </span>
  );
}

function ApiLogPanel({ apiLogs, logStatus, logStatusText, onClear, onClearMessages, clearMessagesLabel }) {
  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden px-4 pb-3 pt-3">
      <div className="mb-2 flex flex-shrink-0 items-center justify-between border-b-2 border-slate-950 pb-2">
        <div className="flex items-center gap-2">
          <Terminal className="h-4 w-4 text-slate-950" aria-hidden="true" />
          <h3 className="text-sm font-black text-slate-900">{t('monitor.tabLogs')}</h3>
        </div>
        <StatusBadge status={logStatus} label={logStatusText} />
      </div>

      <div className="console-scroll min-h-0 flex-1 space-y-3 overflow-y-auto text-left">
        {apiLogs.length === 0 ? (
          <p className="py-10 text-center text-sm text-slate-400">{t('monitor.emptyLogs')}</p>
        ) : apiLogs.map(log => (
          <div
            key={log.id}
            className={`flex flex-col gap-2 rounded-lg border-2 border-slate-950 bg-white p-3 text-sm shadow-[4px_4px_0_rgba(17,20,17,0.95)] ${
              apiLogs.length === 1 ? 'min-h-full' : ''
            }`}
          >
            <div className="flex flex-shrink-0 items-center justify-between border-b border-slate-950 pb-2">
              <span className="font-black text-slate-950">{log.stage || t('monitor.defaultStage')}</span>
              <span className="rounded-md border border-slate-950 bg-[var(--mitako-lime)] px-2 py-0.5 text-xs font-bold text-slate-950">
                {log.statusLabel || t('monitor.statusWorking')}
              </span>
            </div>
            <div className="grid flex-shrink-0 grid-cols-3 gap-2 text-xs font-semibold text-slate-500">
              <div>{t('monitor.logStatus')}<div className="text-slate-900">{log.statusLabel || log.status}</div></div>
              <div>{t('monitor.logDuration')}<div className="font-mono tabular-nums text-slate-900">{log.duration ? `${(log.duration / 1000).toFixed(2)}s` : '-'}</div></div>
              <div>{t('monitor.logAttempt')}<div className="text-slate-900">{log.attempt || 1}/3</div></div>
            </div>
            <div className="rounded-lg border border-slate-950 bg-slate-50 p-3 text-xs leading-relaxed text-slate-600">
              {log.responseStream || t('monitor.logDefaultMessage')}
            </div>
          </div>
        ))}
      </div>

      <div className="mt-2 flex flex-shrink-0 flex-wrap justify-between gap-2 border-t border-slate-950 pt-2 text-xs font-semibold text-slate-500">
        <span>{t('monitor.publicTraceHint')}</span>
        <div className="flex items-center gap-3">
          {onClearMessages && (
            <button type="button" onClick={onClearMessages} aria-label={clearMessagesLabel} className="flex items-center gap-1 rounded focus-visible:ring-2 focus-visible:ring-[var(--mitako-lime)] hover:text-slate-950">
              <Trash2 className="h-3 w-3" aria-hidden="true" />{clearMessagesLabel}
            </button>
          )}
          <button type="button" onClick={onClear} aria-label={t('monitor.clearLogs')} className="flex items-center gap-1 rounded focus-visible:ring-2 focus-visible:ring-[var(--mitako-lime)] hover:text-slate-950">
            <Trash2 className="h-3 w-3" aria-hidden="true" />{t('monitor.clearLogs')}
          </button>
        </div>
      </div>
    </div>
  );
}

function NodeTracePanel({ nodeLogs }) {
  const publicStepLabel = (log, index) => {
    if (log.desc) return log.desc;
    return t('monitor.nodeStep', 'zh-CN', { index: index + 1 });
  };
  return (
    <div className="console-scroll h-full min-h-0 space-y-2 overflow-y-auto p-4 pb-3 font-mono text-sm">
      {nodeLogs.length === 0 ? (
        <div className="flex flex-col items-center gap-3 py-12 text-center text-slate-400">
          <Activity className="h-12 w-12 text-slate-950 opacity-20" aria-hidden="true" />
          <span className="text-sm">{t('monitor.emptyNodes')}</span>
        </div>
      ) : nodeLogs.map((log, i) => (
        <div key={i} className={`flex gap-2 border-l-2 py-1 pl-3 ${log.status === 'start' ? 'border-slate-950' : 'border-[var(--mitako-lime-deep)]'}`}>
          {log.status === 'start' ? (
            <span className="mt-1.5 h-1.5 w-1.5 flex-shrink-0 rounded-full bg-slate-950" />
          ) : (
            <Check className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-slate-950" aria-hidden="true" />
          )}
          <div>
            <span className="font-black text-slate-950">[{log.status === 'start' ? t('monitor.nodeRunning') : t('monitor.nodeDone')}]</span>
            <span className="ml-1 text-slate-600">{publicStepLabel(log, i)}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

function MemoryPanel({ memoryItems }) {
  const catLabel = {
    preference: '偏好',
    profile: '画像',
    need: '需求',
    interest: '兴趣',
  };
  return (
    <div className="console-scroll h-full min-h-0 space-y-2 overflow-y-auto p-4 pb-3">
      {!memoryItems?.length ? (
        <p className="py-10 text-center text-sm text-slate-400">{t('monitor.emptyMemory')}</p>
      ) : memoryItems.map(item => (
        <div key={item.id || item.fingerprint} className="rounded-lg border-2 border-slate-950 bg-white p-3 text-sm shadow-[4px_4px_0_rgba(17,20,17,0.95)]">
          <div className="mb-1 flex items-center justify-between gap-2">
            <span className="text-[10px] font-black uppercase text-slate-950">
              {catLabel[item.category] || item.category} / {item.memory_key}
            </span>
            <span className="text-[10px] tabular-nums text-slate-500">{Math.round((item.confidence || 0.75) * 100)}%</span>
          </div>
          <p className="font-semibold text-slate-800">{item.memory_value}</p>
          {item.source_message && (
            <p className="mt-1 line-clamp-2 text-[11px] text-slate-400">来源：{item.source_message}</p>
          )}
        </div>
      ))}
    </div>
  );
}

export default function AgentMonitor({
  monitorIntent,
  monitorEmotion,
  monitorEmotionColor,
  vikingCapsule,
  vikingStyle,
  intentCapsule,
  intentStyle,
  emotionCapsule,
  emotionStyle,
  activeTab,
  setActiveTab,
  apiLogs,
  setApiLogs,
  logStatus,
  logStatusText,
  nodeLogs,
  models,
  selectedModelId,
  onModelChange,
  streamReplyEnabled,
  onStreamReplyChange,
  orderPriorityWeights,
  onOrderWeightChange,
  onCloseMobile,
  memoryItems,
  onClearMessages,
  showServiceControls = false,
  showOrderPriority = true,
}) {
  const emotionDotStyle = typeof monitorEmotionColor === 'string' && monitorEmotionColor.trim().startsWith('#')
    ? { backgroundColor: monitorEmotionColor }
    : undefined;
  const emotionDotClass = emotionDotStyle ? '' : (monitorEmotionColor || 'bg-[var(--mitako-lime)]');
  const showMemoryTab = memoryItems != null;
  const tabs = showMemoryTab
    ? [
        { id: 'reasoning', label: t('monitor.tabLogs') },
        { id: 'nodes', label: t('monitor.tabNodes') },
        { id: 'memory', label: t('monitor.tabMemory') },
      ]
    : [
        { id: 'reasoning', label: t('monitor.tabLogs') },
        { id: 'nodes', label: t('monitor.tabNodes') },
      ];
  const weightFields = [
    { key: 'needs_attention', label: t('monitor.weightNeedsAttention') },
    { key: 'delay_risk', label: t('monitor.weightDelayRisk') },
    { key: 'had_consultation', label: t('monitor.weightConsultation') },
    { key: 'pending_shipment', label: t('monitor.weightPending') },
    { key: 'refund_history', label: t('monitor.weightRefund') },
    { key: 'delay_days', label: t('monitor.weightDelayDays'), step: 0.05 },
  ];
  const serviceProfiles = models.map((model, index) => ({
    ...model,
    publicLabel: model.label || (index === 0 ? t('monitor.standardReply') : index === 1 ? t('monitor.backupReply') : t('monitor.replyMode', 'zh-CN', { index: index + 1 })),
  }));

  return (
    <section className={`${panelClass} grid h-full min-h-0 overflow-hidden`} style={{ gridTemplateRows: 'auto auto auto minmax(0,1fr)' }}>
      <div className="flex-shrink-0 border-b-2 border-slate-950 bg-white px-4 py-2">
        <div className="flex items-center justify-between gap-2">
          <div className="min-w-0">
            <h2 className="text-base font-black text-slate-900">{t('monitor.title')}</h2>
            <p className="text-xs text-slate-500">{t('monitor.subtitle')}</p>
          </div>
          <div className="flex flex-shrink-0 items-center gap-2">
            <span className="rounded-md border-2 border-slate-950 bg-[var(--mitako-lime)] px-2 py-0.5 text-xs font-black text-slate-900">{t('monitor.realtime')}</span>
            {onCloseMobile && (
              <button type="button" onClick={onCloseMobile} className="rounded-lg border border-slate-950 px-2 py-1 text-xs font-bold text-slate-700 hover:bg-slate-100 lg:hidden">
                {t('monitor.collapse')}
              </button>
            )}
          </div>
        </div>

        <div className="mt-2 flex flex-col gap-2">
          {showServiceControls && (
            <>
              <label className="text-xs font-black uppercase tracking-wide text-slate-500" htmlFor="service-profile-select">
                {t('monitor.modelLabel')}
              </label>
              <select
                id="service-profile-select"
                name="service_profile"
                value={selectedModelId}
                onChange={event => onModelChange(event.target.value)}
                className={inputClass}
              >
                {serviceProfiles.map(model => (
                  <option key={model.id} value={model.id} disabled={!model.configured}>
                    {model.publicLabel}{!model.configured ? '（待配置）' : ''}
                  </option>
                ))}
              </select>

              <div className="flex items-center justify-between gap-2 rounded-lg border-2 border-slate-950 bg-white px-3 py-2">
                <div className="min-w-0">
                  <p className="text-xs font-black text-slate-800">{t('monitor.streamReply')}</p>
                  <p className="text-[11px] leading-snug text-slate-500">{t('monitor.streamReplyHint')}</p>
                </div>
                <button
                  type="button"
                  role="switch"
                  aria-label={t('monitor.streamReply')}
                  aria-checked={streamReplyEnabled}
                  onClick={() => onStreamReplyChange(!streamReplyEnabled)}
                  className={`relative h-11 w-14 flex-shrink-0 rounded-[8px] border-2 border-slate-950 transition-colors focus-visible:ring-2 focus-visible:ring-[var(--mitako-lime)] ${
                    streamReplyEnabled ? 'bg-[var(--mitako-lime)]' : 'bg-slate-300'
                  }`}
                >
                  <span className={`absolute left-1 top-2 h-6 w-6 rounded-[8px] bg-white shadow transition-transform ${
                    streamReplyEnabled ? 'translate-x-5' : 'translate-x-0'
                  }`} />
                </button>
              </div>
              <p className="text-xs font-semibold text-slate-500">{streamReplyEnabled ? t('monitor.streamOn') : t('monitor.streamOff')}</p>
            </>
          )}

          {showOrderPriority && (
            <div className="mt-2 rounded-lg border-2 border-slate-950 bg-slate-50 p-3">
              <p className="text-xs font-black text-slate-800">{t('monitor.orderPriorityTitle')}</p>
              <p className="mb-2 mt-0.5 text-[11px] leading-snug text-slate-500">{t('monitor.orderPriorityHint')}</p>
              <div className="grid grid-cols-2 gap-2">
                {weightFields.map(({ key, label, step }) => (
                  <label key={key} className="flex flex-col gap-0.5">
                    <span className="text-xs font-semibold text-slate-500">{label}</span>
                    <input
                      type="number"
                      step={step || 1}
                      min={0}
                      value={orderPriorityWeights?.[key] ?? 0}
                      onChange={event => onOrderWeightChange(key, event.target.value)}
                      className="h-9 w-full rounded-lg border border-slate-950 bg-white px-2 font-mono text-sm tabular-nums outline-none focus-visible:ring-2 focus-visible:ring-[var(--mitako-lime)]"
                    />
                  </label>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="grid flex-shrink-0 grid-cols-2 gap-2 border-b-2 border-slate-950 bg-slate-50 px-3 py-2">
        <div>
          <span className="text-xs font-black uppercase text-slate-500">{t('monitor.intentLabel')}</span>
          <div className="mt-0.5 line-clamp-2 break-words rounded-lg border border-slate-950 bg-white px-2 py-1.5 text-sm font-semibold text-slate-700">{monitorIntent}</div>
        </div>
        <div>
          <span className="text-xs font-black uppercase text-slate-500">{t('monitor.emotionLabel')}</span>
          <div className="mt-0.5 flex items-center justify-between gap-1 rounded-lg border border-slate-950 bg-white px-2 py-1.5 text-sm font-semibold text-slate-700">
            <span className="line-clamp-2 break-words">{monitorEmotion}</span>
            <span className={`h-2 w-2 flex-shrink-0 rounded-full ${emotionDotClass}`} style={emotionDotStyle} />
          </div>
        </div>
        <div className="col-span-2 flex flex-wrap gap-1">
          <span className={`rounded-md border px-2 py-0.5 text-xs font-black ${vikingStyle || 'border-slate-950 bg-white'}`}>{vikingCapsule}</span>
          <span className={`rounded-md border px-2 py-0.5 text-xs font-black ${intentStyle || 'border-slate-950 bg-white'}`}>{intentCapsule}</span>
          <span className={`rounded-md border px-2 py-0.5 text-xs font-black ${emotionStyle || 'border-slate-950 bg-[var(--mitako-lime)]'}`}>{emotionCapsule}</span>
        </div>
      </div>

      <div className="flex flex-shrink-0 border-b-2 border-slate-950 text-sm" role="tablist" aria-label={t('monitor.tabListLabel')}>
        {tabs.map(tab => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            id={`tab-${tab.id}`}
            aria-selected={activeTab === tab.id}
            aria-controls="monitor-tabpanel"
            onClick={() => setActiveTab(tab.id)}
            className={`flex-1 border-b-2 py-2 font-black transition-colors focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--mitako-lime)] ${
              activeTab === tab.id ? 'border-slate-950 bg-[var(--mitako-lime)] text-slate-950' : 'border-transparent text-slate-500'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div id="monitor-tabpanel" role="tabpanel" aria-labelledby={`tab-${activeTab}`} tabIndex={0} className="min-h-0 overflow-hidden bg-white">
        {activeTab === 'reasoning' ? (
          <ApiLogPanel
            apiLogs={apiLogs}
            logStatus={logStatus}
            logStatusText={logStatusText}
            onClear={() => setApiLogs([])}
            onClearMessages={onClearMessages}
            clearMessagesLabel={t('monitor.clearMessages')}
          />
        ) : activeTab === 'memory' ? (
          <MemoryPanel memoryItems={memoryItems} />
        ) : (
          <NodeTracePanel nodeLogs={nodeLogs} />
        )}
      </div>
    </section>
  );
}
