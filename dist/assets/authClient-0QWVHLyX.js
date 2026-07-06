import{c as o}from"./index-Di7UovU1.js";/**
 * @license lucide-react v0.300.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const f=o("LogIn",[["path",{d:"M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4",key:"u53s6r"}],["polyline",{points:"10 17 15 12 10 7",key:"1ail0h"}],["line",{x1:"15",x2:"3",y1:"12",y2:"12",key:"v6grx8"}]]);/**
 * @license lucide-react v0.300.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const k=o("RefreshCw",[["path",{d:"M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8",key:"v9h5vc"}],["path",{d:"M21 3v5h-5",key:"1q7to0"}],["path",{d:"M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16",key:"3uifl3"}],["path",{d:"M8 16H3v5",key:"1cv678"}]]);/**
 * @license lucide-react v0.300.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const g=o("Users",[["path",{d:"M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2",key:"1yyitq"}],["circle",{cx:"9",cy:"7",r:"4",key:"nufk8"}],["path",{d:"M22 21v-2a4 4 0 0 0-3-3.87",key:"kshegd"}],["path",{d:"M16 3.13a4 4 0 0 1 0 7.75",key:"1da9ce"}]]),r="mitako_auth_token_v1",i="mitako_auth_user_v1";function c(){try{return sessionStorage.getItem(r)||""}catch{return""}}function p(){try{const e=sessionStorage.getItem(i);return e?JSON.parse(e):null}catch{return null}}function u(e,t){try{sessionStorage.setItem(r,e),sessionStorage.setItem(i,JSON.stringify(t))}catch{}}function h(){try{sessionStorage.removeItem(r),sessionStorage.removeItem(i)}catch{}}function d(e={}){const t=c(),a={...e};return t&&(a.Authorization=`Bearer ${t}`),a}async function l(){const t=await(await fetch("/api/v1/auth/status")).json();return!!(t.protected_api_auth_required??t.auth_required)}async function v(e,t,a="mitako"){const s=await(await fetch("/api/v1/auth/login",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({username:e,password:t,tenant_id:a})})).json();if(!s.ok)throw new Error(s.error||"login_failed");return u(s.token,s.user),s.user}async function m(e,t={}){const a=d(t.headers||{}),n=await fetch(e,{...t,headers:a});return n.status===401?(h(),window.dispatchEvent(new CustomEvent("mitako:auth:logout"))):n.status===403&&window.dispatchEvent(new CustomEvent("mitako:auth:forbidden")),n}export{f as L,k as R,g as U,m as a,p as b,h as c,l as f,c as g,v as l,u as s};
