// Shared front-end helpers for MediScript.
const MS = {
  async get(url){ const r = await fetch(url); return r.json(); },
  async post(url, body, isForm=false){
    const opt = { method:"POST" };
    if (isForm){ opt.body = body; }
    else { opt.headers = {"Content-Type":"application/json"}; opt.body = JSON.stringify(body||{}); }
    const r = await fetch(url, opt);
    let data = {}; try { data = await r.json(); } catch(e){}
    if (!r.ok) throw new Error(data.detail || ("Request failed ("+r.status+")"));
    return data;
  },
  async del(url){ const r = await fetch(url,{method:"DELETE"}); return r.json(); },
  async patch(url, body){ const r = await fetch(url,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify(body||{})}); let d={}; try{d=await r.json();}catch(e){} if(!r.ok) throw new Error(d.detail||("Request failed ("+r.status+")")); return d; },
  flash(msg){
    let el = document.querySelector(".flash");
    if(!el){ el = document.createElement("div"); el.className="flash"; document.body.appendChild(el); }
    el.textContent = msg; el.classList.add("show");
    clearTimeout(el._t); el._t = setTimeout(()=>el.classList.remove("show"), 2600);
  },
  esc(s){ return (s||"").replace(/[&<>"]/g, c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c])); }
};

// Wire auth forms if present
document.addEventListener("DOMContentLoaded", ()=>{
  const lf = document.getElementById("loginForm");
  if (lf) lf.addEventListener("submit", async e=>{
    e.preventDefault();
    const btn = lf.querySelector("button"); btn.disabled = true;
    try {
      const data = await MS.post("/api/auth/login", {
        email: lf.email.value.trim(), password: lf.password.value });
      window.location = data.redirect;
    } catch(err){ MS.flash(err.message); btn.disabled = false; }
  });

  const rf = document.getElementById("registerForm");
  if (rf) rf.addEventListener("submit", async e=>{
    e.preventDefault();
    const btn = rf.querySelector("button"); btn.disabled = true;
    try {
      const body = {
        email: rf.email.value.trim(), password: rf.password.value,
        full_name: rf.full_name.value.trim(), role: rf.role.value,
        pharmacy_name: rf.pharmacy_name ? rf.pharmacy_name.value.trim() : ""
      };
      const data = await MS.post("/api/auth/register", body);
      window.location = data.redirect;
    } catch(err){ MS.flash(err.message); btn.disabled = false; }
  });

  const roleSel = document.getElementById("role");
  const pharmWrap = document.getElementById("pharmacyWrap");
  if (roleSel && pharmWrap){
    const sync = ()=>{ pharmWrap.style.display = roleSel.value==="chemist" ? "block":"none"; };
    roleSel.addEventListener("change", sync); sync();
  }

  const logout = document.getElementById("logoutBtn");
  if (logout) logout.addEventListener("click", async ()=>{
    await MS.post("/api/auth/logout", {}); window.location = "/";
  });
});
