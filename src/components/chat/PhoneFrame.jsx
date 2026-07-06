import React from 'react';

/** 桌面端仿手机竖屏外框 — PPT 风格黑边硬阴影 */
export default function PhoneFrame({ children }) {
  return (
    <div className="flex-1 min-h-0 h-full flex flex-col items-stretch justify-center lg:justify-stretch">
      <div className="w-full h-full max-w-[420px] lg:mx-auto flex flex-col min-h-0 flex-1 @container/phone">
        <div className="flex-1 min-h-0 flex flex-col lg:rounded-[8px] lg:border lg:border-slate-200 lg:shadow-[0_24px_56px_rgba(127,164,49,.18)] lg:overflow-hidden lg:bg-white relative">
          <div className="flex-1 min-h-0 flex flex-col bg-white lg:rounded-[6px] overflow-hidden h-full">
            {children}
          </div>
        </div>
      </div>
    </div>
  );
}
