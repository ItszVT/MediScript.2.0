// Shared settings wiring for both portals.
(function(){
  function init(){
    MS.get("/api/account/me").then(m=>{
      const set=(id,v)=>{ const el=document.getElementById(id); if(el) el.value=v||""; };
      set("s_full_name", m.full_name); set("s_pharmacy_name", m.pharmacy_name);
      const em=document.getElementById("s_email"); if(em) em.textContent=m.email;
      const rl=document.getElementById("s_role"); if(rl) rl.textContent=m.role;
    });
    const pf=document.getElementById("profileForm");
    if(pf) pf.addEventListener("submit", async e=>{
      e.preventDefault();
      const body={ full_name: document.getElementById("s_full_name").value };
      const ph=document.getElementById("s_pharmacy_name");
      if(ph) body.pharmacy_name = ph.value;
      try{ await MS.post("/api/account/profile", body); MS.flash("Profile saved."); }
      catch(err){ MS.flash(err.message); }
    });
    const pw=document.getElementById("passwordForm");
    if(pw) pw.addEventListener("submit", async e=>{
      e.preventDefault();
      try{
        await MS.post("/api/account/password", {
          current_password: document.getElementById("s_current").value,
          new_password: document.getElementById("s_new").value });
        MS.flash("Password changed."); pw.reset();
      }catch(err){ MS.flash(err.message); }
    });
  }
  if(document.readyState!=="loading") init();
  else document.addEventListener("DOMContentLoaded", init);
})();
