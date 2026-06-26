import{c as i}from"./index-DkOaKey7.js";/**
 * @license lucide-react v0.300.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const f=i("LogIn",[["path",{d:"M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4",key:"u53s6r"}],["polyline",{points:"10 17 15 12 10 7",key:"1ail0h"}],["line",{x1:"15",x2:"3",y1:"12",y2:"12",key:"v6grx8"}]]);/**
 * @license lucide-react v0.300.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const g=i("Users",[["path",{d:"M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2",key:"1yyitq"}],["circle",{cx:"9",cy:"7",r:"4",key:"nufk8"}],["path",{d:"M22 21v-2a4 4 0 0 0-3-3.87",key:"kshegd"}],["path",{d:"M16 3.13a4 4 0 0 1 0 7.75",key:"1da9ce"}]]),o="mitako_auth_token_v1",r="mitako_auth_user_v1";function c(){try{return sessionStorage.getItem(o)||""}catch{return""}}function k(){try{const t=sessionStorage.getItem(r);return t?JSON.parse(t):null}catch{return null}}function u(t,e){try{sessionStorage.setItem(o,t),sessionStorage.setItem(r,JSON.stringify(e))}catch{}}function h(){try{sessionStorage.removeItem(o),sessionStorage.removeItem(r)}catch{}}function y(t={}){const e=c(),a={...t};return e&&(a.Authorization=`Bearer ${e}`),a}async function l(){return!!(await(await fetch("/api/v1/auth/status")).json()).auth_required}async function m(t,e,a="mitako"){const n=await(await fetch("/api/v1/auth/login",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({username:t,password:e,tenant_id:a})})).json();if(!n.ok)throw new Error(n.error||"login_failed");return u(n.token,n.user),n.user}async function p(t,e={}){const a=y(e.headers||{}),s=await fetch(t,{...e,headers:a});return s.status===401&&(h(),window.dispatchEvent(new CustomEvent("mitako:auth:logout"))),s}export{f as L,g as U,p as a,k as b,h as c,l as f,c as g,m as l,u as s};
