import React, { useCallback, useEffect, useState } from 'react';
import t from '../../i18n/index.js';
import { authFetch } from '../../lib/authClient.js';

export default function AuditLog() {
  const [events, setEvents] = useState([]);
  const [selected, setSelected] = useState('');
  const [transcript, setTranscript] = useState(null);

  const load = useCallback(async () => {
    const r = await authFetch('/api/v1/admin/audit/events?limit=80');
    const data = await r.json();
    if (data.ok) setEvents(data.events || []);
  }, []);

  useEffect(() => { load(); }, [load]);

  const openSession = async (sid) => {
    setSelected(sid);
    const r = await authFetch(`/api/v1/admin/audit/sessions/${encodeURIComponent(sid)}/transcript`);
    const data = await r.json();
    if (data.ok) setTranscript(data);
  };

  return (
    <div className="p-6 grid lg:grid-cols-2 gap-6">
      <div>
        <h1 className="text-xl font-bold mb-4">{t('admin.navAudit')}</h1>
        <ul className="space-y-2 max-h-[70vh] overflow-auto">
          {events.map(ev => (
            <li key={`${ev.session_id}-${ev.id}-${ev.created_at}`}>
              <button type="button" onClick={() => openSession(ev.session_id)} className="w-full text-left rounded-lg border bg-white px-3 py-2 text-xs hover:bg-slate-50">
                <span className="font-mono font-bold">{ev.event_type}</span> · {ev.session_id}
              </button>
            </li>
          ))}
        </ul>
      </div>
      <div>
        <h2 className="font-bold text-sm mb-2">{selected || t('admin.pickSessionAudit')}</h2>
        {transcript && (
          <div className="rounded-xl border bg-white p-4 text-xs space-y-2 max-h-[70vh] overflow-auto">
            {(transcript.messages || []).map(m => (
              <p key={m.id}><strong>{m.role}:</strong> {m.content?.slice(0, 200)}</p>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
