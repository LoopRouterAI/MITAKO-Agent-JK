import React from 'react';

/** 桌面端仿手机竖屏外框 — 占满左侧栏可用高度 */
export default function PhoneFrame({ children }) {
  return (
    <div className="flex-1 min-h-0 h-full flex flex-col items-stretch justify-center lg:justify-stretch">
      <div className="w-full h-full max-w-[420px] lg:mx-auto flex flex-col min-h-0 flex-1 @container/phone">
        <div className="flex-1 min-h-0 flex flex-col lg:rounded-[2.25rem] lg:border-[10px] lg:border-slate-900 lg:shadow-[0_24px_80px_rgba(15,23,42,0.18)] lg:overflow-hidden lg:bg-slate-900 relative">
          <div className="flex-1 min-h-0 flex flex-col bg-white lg:rounded-[1.5rem] overflow-hidden h-full">
            {children}
          </div>
        </div>
      </div>
    </div>
  );
}
