import React from 'react';
import { Terminal, Copy, Trash2, Check, Activity } from 'lucide-react';
import { copyToClipboard } from '../../utils/copyToClipboard.js';
import t from '../../i18n/index.js';

function ApiLogPanel({ apiLogs, logStatus, logStatusText, onClear, onClearMessages, clearMessagesLabel, currentModelLabel }) {
  return (
    <div className="h-full min-h-0 flex flex-col overflow-hidden px-4 pb-3 pt-3">
      <div className="flex items-center justify-between border-b border-slate-100 pb-2 mb-2 flex-shrink-0">
        <div className="flex items-center gap-2">
          <Terminal className="w-4 h-4 text-[var(--mitako-purple)]" />
          <h3 className="font-bold text-slate-800 text-sm">{t('monitor.tabLogs')}</h3>
        </div>
        <span className={`text-xs font-bold px-2.5 py-1 rounded-md border ${
          logStatus === 'error'
            ? 'text-rose-700 bg-rose-50 border-rose-200'
            : logStatus === 'requesting' || logStatus === 'retrying'
            ? 'text-amber-700 bg-amber-50 border-amber-200'
            : 'text-emerald-700 bg-emerald-50 border-emerald-200'
        }`}>
          {logStatusText}
        </span>
      </div>

      {/* 主滚动区：占满 Monitor 剩余高度 */}
      <div className="flex-1 min-h-0 overflow-y-auto console-scroll text-left space-y-3">
        {apiLogs.length === 0 ? (
          <p className="text-sm text-slate-400 text-center py-10">{t('monitor.emptyLogs')}</p>
        ) : apiLogs.map(log => (
          <div
            key={log.id}
            className={`border border-slate-200 rounded-xl p-3 bg-slate-50/80 flex flex-col gap-2 text-sm ${
              apiLogs.length === 1 ? 'min-h-full' : ''
            }`}
          >
            <div className="flex justify-between items-center border-b border-slate-200 pb-2 flex-shrink-0">
              <span className="font-bold text-[var(--mitako-purple)]">{log.stage}</span>
              <span className="font-mono text-slate-500 tabular-nums text-xs">{log.model}</span>
            </div>
            <div className="grid grid-cols-3 gap-2 text-xs font-semibold text-slate-500 flex-shrink-0">
              <div>状态 <div className="text-slate-800">{log.status}</div></div>
              <div>耗时 <div className="font-mono text-slate-800">{log.duration ? `${(log.duration / 1000).toFixed(2)}s` : '—'}</div></div>
              <div>尝试 <div className="text-slate-800">{log.attempt || 1}/3</div></div>
            </div>
            <div className={`flex-1 min-h-0 grid gap-2 ${apiLogs.length === 1 ? 'grid-rows-2' : 'grid-rows-[minmax(160px,1fr)_minmax(160px,1fr)]'}`}>
              <div className="flex flex-col min-h-[160px]">
                <div className="flex justify-between mb-1 flex-shrink-0">
                  <span className="font-semibold text-slate-500">Request</span>
                  <button type="button" id={`${log.id}_req`} aria-label={t('monitor.copyRequest')} onClick={() => copyToClipboard(JSON.stringify(log.payload, null, 2), `${log.id}_req`)} className="text-[var(--mitako-purple)] flex items-center gap-0.5 focus-visible:ring-2 focus-visible:ring-[var(--mitako-purple)]/30 rounded">
                    <Copy className="w-3 h-3" aria-hidden="true" />复制
                  </button>
                </div>
                <pre className="flex-1 min-h-[160px] font-mono bg-slate-950 text-slate-100 p-3 rounded-xl text-xs overflow-auto whitespace-pre-wrap break-all console-scroll">{JSON.stringify(log.payload, null, 2)}</pre>
              </div>
              <div className="flex flex-col min-h-[160px]">
                <div className="flex justify-between mb-1 flex-shrink-0">
                  <span className="font-semibold text-slate-500">Response</span>
                  <button type="button" id={`${log.id}_resp`} aria-label={t('monitor.copyResponse')} onClick={() => copyToClipboard(log.responseStream, `${log.id}_resp`)} className="text-[var(--mitako-purple)] flex items-center gap-0.5 focus-visible:ring-2 focus-visible:ring-[var(--mitako-purple)]/30 rounded">
                    <Copy className="w-3 h-3" aria-hidden="true" />复制
                  </button>
                </div>
                <div className="flex-1 min-h-[160px] font-mono bg-slate-950 text-slate-100 p-3 rounded-xl text-xs overflow-auto whitespace-pre-wrap break-all console-scroll">{log.responseStream}</div>
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="border-t border-slate-100 pt-2 mt-2 flex flex-wrap justify-between gap-2 text-xs text-slate-400 font-semibold flex-shrink-0">
        <span>{t('monitor.modelLabel')}: {currentModelLabel}</span>
        <div className="flex items-center gap-3">
          {onClearMessages && (
            <button type="button" onClick={onClearMessages} aria-label={clearMessagesLabel} className="hover:text-rose-500 flex items-center gap-1 focus-visible:ring-2 focus-visible:ring-rose-300 rounded">
              <Trash2 className="w-3 h-3" aria-hidden="true" />{clearMessagesLabel}
            </button>
          )}
          <button type="button" onClick={onClear} aria-label={t('monitor.clearLogs')} className="hover:text-rose-500 flex items-center gap-1 focus-visible:ring-2 focus-visible:ring-rose-300 rounded">
            <Trash2 className="w-3 h-3" aria-hidden="true" />{t('monitor.clearLogs')}
          </button>
        </div>
      </div>
    </div>
  );
}

function NodeTracePanel({ nodeLogs }) {
  return (
    <div className="h-full min-h-0 overflow-y-auto p-4 pb-3 space-y-2 font-mono text-sm console-scroll">
      {nodeLogs.length === 0 ? (
        <div className="text-slate-400 text-center py-12 flex flex-col items-center gap-3">
          <Activity className="w-12 h-12 opacity-20 text-[var(--mitako-purple)]" />
          <span className="text-sm">{t('monitor.emptyNodes')}</span>
        </div>
      ) : nodeLogs.map((log, i) => (
        <div key={i} className={`flex gap-2 border-l-2 pl-3 py-1 ${log.status === 'start' ? 'border-[var(--mitako-purple)]/40' : 'border-emerald-300'}`}>
          {log.status === 'start' ? (
            <span className="w-1.5 h-1.5 rounded-full bg-[var(--mitako-purple)] mt-1.5 animate-pulse flex-shrink-0" />
          ) : (
            <Check className="w-3.5 h-3.5 text-emerald-500 mt-0.5 flex-shrink-0" />
          )}
          <div>
            <span className={`font-bold ${log.status === 'start' ? 'text-[var(--mitako-purple)]' : 'text-emerald-600'}`}>
              [{log.status === 'start' ? '运行' : '完成'}] {log.node}
            </span>
            <span className="ml-1 text-slate-600">{log.desc || ''}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

function MemoryPanel({ memoryItems }) {
  const catLabel = {
    preference: '喜好',
    profile: '画像',
    need: '需求',
    interest: '兴趣',
  };
  return (
    <div className="h-full min-h-0 overflow-y-auto p-4 pb-3 space-y-2 console-scroll">
      {!memoryItems?.length ? (
        <p className="text-sm text-slate-400 text-center py-10">{t('monitor.emptyMemory')}</p>
      ) : memoryItems.map(item => (
        <div key={item.id || item.fingerprint} className="rounded-xl border border-violet-100 bg-violet-50/50 p-3 text-sm">
          <div className="flex items-center justify-between gap-2 mb-1">
            <span className="text-[10px] font-bold uppercase text-violet-600">
              {catLabel[item.category] || item.category} · {item.memory_key}
            </span>
            <span className="text-[10px] text-slate-400 tabular-nums">{Math.round((item.confidence || 0.75) * 100)}%</span>
          </div>
          <p className="font-semibold text-slate-800">{item.memory_value}</p>
          {item.source_message && (
            <p className="text-[11px] text-slate-400 mt-1 line-clamp-2">来源：{item.source_message}</p>
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
  showOrderPriority = true,
}) {
  const currentModel = models.find(m => m.id === selectedModelId) || models[0];
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

  return (
    <section
      className="glass-panel h-full min-h-0 overflow-hidden grid"
      style={{ gridTemplateRows: 'auto auto auto minmax(0,1fr)' }}
    >
      {/* 顶栏 + 模型（紧凑） */}
      <div className="px-4 py-2 border-b border-slate-100 bg-white/50 flex-shrink-0">
        <div className="flex items-center justify-between gap-2">
          <div className="min-w-0">
            <h2 className="text-base font-bold text-slate-800">{t('monitor.title')}</h2>
            <p className="text-xs text-slate-400">{t('monitor.subtitle')}</p>
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            <span className="text-xs font-bold text-[var(--mitako-purple)] bg-[#7B61FF]/10 border border-[#7B61FF]/20 px-2 py-0.5 rounded-md">SSE</span>
            {onCloseMobile && (
              <button type="button" onClick={onCloseMobile} className="lg:hidden text-xs font-bold text-slate-500 px-2 py-1 rounded-lg hover:bg-slate-100">
                收起
              </button>
            )}
          </div>
        </div>
        <div className="mt-2 flex flex-col gap-1">
          <label className="text-xs font-bold text-slate-400 uppercase tracking-wider" htmlFor="model-select">
            {t('monitor.modelSwitch')}
          </label>
          <select
            id="model-select"
            name="llm_model"
            value={selectedModelId}
            onChange={e => onModelChange(e.target.value)}
            className="w-full min-h-[42px] text-sm font-semibold bg-white border border-slate-200 rounded-xl px-3 py-2 text-slate-800 outline-none focus-visible:ring-2 focus-visible:ring-[var(--mitako-purple)]/30"
          >
            {models.map(m => (
              <option key={m.id} value={m.id} disabled={!m.configured}>
                {m.label}{!m.configured ? ` (${t('monitor.modelNotConfigured')})` : ''}
              </option>
            ))}
          </select>
          {currentModel?.rate_limit && (
            <p className="text-xs text-slate-500 font-mono tabular-nums truncate">
              {t('monitor.rateLimitRemaining', 'zh-CN', {
                remaining: currentModel.rate_limit.remaining,
                max: currentModel.rate_limit.max_requests,
              })}
            </p>
          )}
          <div className="mt-2 flex items-center justify-between gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2">
            <div className="min-w-0">
              <p className="text-xs font-bold text-slate-700">{t('monitor.streamReply')}</p>
              <p className="text-[11px] text-slate-400 leading-snug">{t('monitor.streamReplyHint')}</p>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={streamReplyEnabled}
              onClick={() => onStreamReplyChange(!streamReplyEnabled)}
              className={`relative flex-shrink-0 w-11 h-6 rounded-full transition-colors focus-visible:ring-2 focus-visible:ring-[var(--mitako-purple)]/40 ${
                streamReplyEnabled ? 'bg-[var(--mitako-purple)]' : 'bg-slate-300'
              }`}
            >
              <span
                className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white shadow transition-transform ${
                  streamReplyEnabled ? 'translate-x-5' : 'translate-x-0'
                }`}
              />
            </button>
          </div>
          <p className="text-xs text-slate-400 font-semibold">
            {streamReplyEnabled ? t('monitor.streamOn') : t('monitor.streamOff')}
          </p>

          {showOrderPriority && (
          <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50/80 p-3">
            <p className="text-xs font-bold text-slate-700">{t('monitor.orderPriorityTitle')}</p>
            <p className="text-[11px] text-slate-400 mt-0.5 mb-2 leading-snug">{t('monitor.orderPriorityHint')}</p>
            <div className="grid grid-cols-2 gap-2">
              {weightFields.map(({ key, label, step }) => (
                <label key={key} className="flex flex-col gap-0.5">
                  <span className="text-xs font-semibold text-slate-500">{label}</span>
                  <input
                    type="number"
                    step={step || 1}
                    min={0}
                    value={orderPriorityWeights?.[key] ?? 0}
                    onChange={e => onOrderWeightChange(key, e.target.value)}
                    className="w-full h-9 rounded-lg border border-slate-200 bg-white px-2 text-sm font-mono tabular-nums outline-none focus-visible:ring-2 focus-visible:ring-[var(--mitako-purple)]/30"
                  />
                </label>
              ))}
            </div>
          </div>
          )}
        </div>
      </div>

      <div className="px-3 py-2 border-b border-slate-100 grid grid-cols-2 gap-2 bg-slate-50/40 flex-shrink-0">
        <div>
          <span className="text-xs font-bold text-slate-400 uppercase">{t('monitor.intentLabel')}</span>
          <div className="text-sm font-semibold text-slate-700 bg-white border border-slate-200/80 px-2 py-1.5 rounded-lg mt-0.5 truncate">{monitorIntent}</div>
        </div>
        <div>
          <span className="text-xs font-bold text-slate-400 uppercase">{t('monitor.emotionLabel')}</span>
          <div className="text-sm font-semibold text-slate-700 bg-white border border-slate-200/80 px-2 py-1.5 rounded-lg mt-0.5 flex items-center justify-between gap-1">
            <span className="truncate">{monitorEmotion}</span>
            <span className={`w-2 h-2 rounded-full flex-shrink-0 ${monitorEmotionColor}`} />
          </div>
        </div>
        <div className="col-span-2 flex flex-wrap gap-1">
          <span className={`text-xs font-bold border px-2 py-0.5 rounded-full ${vikingStyle}`}>{vikingCapsule}</span>
          <span className={`text-xs font-bold border px-2 py-0.5 rounded-full ${intentStyle}`}>{intentCapsule}</span>
          <span className={`text-xs font-bold border px-2 py-0.5 rounded-full ${emotionStyle}`}>{emotionCapsule}</span>
        </div>
      </div>

      <div className="flex border-b border-slate-100 text-sm flex-shrink-0" role="tablist" aria-label={t('monitor.tabListLabel')}>
        {tabs.map(tab => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            id={`tab-${tab.id}`}
            aria-selected={activeTab === tab.id}
            aria-controls={`tabpanel-${tab.id}`}
            onClick={() => setActiveTab(tab.id)}
            className={`flex-1 py-2 font-bold border-b-2 transition-colors focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--mitako-purple)]/30 ${
              activeTab === tab.id ? 'text-[var(--mitako-purple)] border-[var(--mitako-purple)]' : 'text-slate-400 border-transparent'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* 日志/节点/记忆区：grid 最后一行，强制吃满剩余高度 */}
      <div className="min-h-0 overflow-hidden bg-white/60">
        {activeTab === 'reasoning' ? (
          <ApiLogPanel
            apiLogs={apiLogs}
            logStatus={logStatus}
            logStatusText={logStatusText}
            onClear={() => setApiLogs([])}
            onClearMessages={onClearMessages}
            clearMessagesLabel={t('monitor.clearMessages')}
            currentModelLabel={currentModel?.label || selectedModelId}
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
