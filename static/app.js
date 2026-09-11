const $=id=>document.getElementById(id), msg=$('message');
let allPeople=[];
function esc(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function renderTickets(){
  const q=($('ticketSearch')?.value||'').trim().toLowerCase();
  const list=q?allPeople.filter(x=>(x.name||'').toLowerCase().includes(q)||(x.login||'').toLowerCase().includes(q)||String(x.user_id||'').includes(q)):allPeople;
  $('ticketBody').innerHTML=list.map(x=>`<tr><td>${esc(x.name)}<small class="login">@${esc(x.login||x.name)}</small></td><td>${x.base}</td><td>${x.redeemed}</td><td>${x.adjustment>0?'+':''}${x.adjustment}</td><td><b>${x.tickets}</b></td><td>${x.chance}%</td><td><button class="mini edit-ticket" data-user-id="${esc(x.user_id)}">修改</button></td></tr>`).join('');
  document.querySelectorAll('.edit-ticket').forEach(btn=>{
    btn.addEventListener('click',()=>{
      const person=allPeople.find(x=>String(x.user_id)===String(btn.dataset.userId));
      if(person) editTicket(person.user_id,person.tickets,person.name);
    });
  });
  if($('searchCount')) $('searchCount').textContent=q?`找到 ${list.length} 人`:`共 ${allPeople.length} 人`;
}
async function loadTickets(){const r=await fetch('/api/tickets'),d=await r.json();if(!d.ok)return;$('participantCount').textContent=d.participants;$('ticketCount').textContent=d.total_tickets;allPeople=d.people;renderTickets()}
async function loadSettings(){
  const r=await fetch('/api/settings?ts='+Date.now(),{cache:'no-store'}),d=await r.json(); if(!d.ok)return;
  const s=d.settings||{};
  if(s.reward_cost!=null)$('rewardCost').value=s.reward_cost;
  const unlimited=Boolean(s.unlimited)||Number(s.max_extra)<0; $('unlimitedExtra').checked=unlimited;
  if(!unlimited && s.max_extra!=null)$('maxExtra').value=s.max_extra;
  $('maxExtra').disabled=unlimited;
  localStorage.setItem('lotterySettings',JSON.stringify({reward_cost:Number($('rewardCost').value),max_extra:Number($('maxExtra').value),unlimited}));
  $('settingsStatus').textContent=`✅ 已載入永久設定（${d.storage==='postgres'?'Supabase':'本機資料庫'}）`;
}
async function saveSettings(){
  const unlimited=$('unlimitedExtra').checked;
  $('settingsStatus').textContent='儲存中...';
  const r=await fetch('/api/settings',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({reward_cost:Number($('rewardCost').value),max_extra:Number($('maxExtra').value),unlimited,sync_twitch:true})});
  const d=await r.json();
  if(!d.ok){$('settingsStatus').textContent='❌ '+d.error;return}
  localStorage.setItem('lotterySettings',JSON.stringify({reward_cost:d.reward_cost,max_extra:d.max_extra,unlimited:d.unlimited}));
  $('settingsStatus').textContent=d.twitch_error?`✅ 已永久保存到 ${d.storage==='postgres'?'Supabase':'資料庫'}；Twitch 獎勵同步失敗，可稍後再試`:`✅ 已永久保存到 ${d.storage==='postgres'?'Supabase':'資料庫'}`+(d.twitch_updated?'，Twitch 獎勵也已同步':'');
}
async function editTicket(id,current,name){
  const total=prompt(`把 ${name} 的總票數改成多少？`,current);
  if(total===null)return;
  const n=Number(total);
  if(!Number.isInteger(n)||n<0){msg.textContent='❌ 票數必須是 0 以上的整數';return}
  const reason=prompt('修改原因（例如：系統重複計票）','手動修正');
  if(reason===null)return;
  try{
    msg.textContent='正在修改票數...';
    const r=await fetch('/api/admin/tickets/'+encodeURIComponent(id),{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({total:n,reason})});
    const d=await r.json();
    if(!r.ok||!d.ok){msg.textContent='❌ '+(d.error||`修改失敗（HTTP ${r.status}）`);return}
    msg.textContent=`✅ ${name} 的總票數已改成 ${d.total}`;
    await loadTickets();
  }catch(e){msg.textContent='❌ 修改票數時發生錯誤：'+e.message}
}
$('updateButton').onclick=async()=>{msg.textContent='正在更新追隨者...';const r=await fetch('/api/followers'),d=await r.json();msg.textContent=d.ok?`✅ 已同步 ${d.count} 位追隨者，每人基本 1 張票`:'❌ '+d.error;loadTickets()};
$('rewardButton').onclick=async()=>{if(!confirm('建立 Twitch 頻道點數「抽獎券」獎勵？'))return;await saveSettings();msg.textContent='建立中...';const r=await fetch('/api/reward',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cost:Number($('rewardCost').value),max_extra:Number($('maxExtra').value),unlimited:$('unlimitedExtra').checked})}),d=await r.json();msg.textContent=d.ok?(d.eventsub?.ok?'✅ 抽獎券建立完成，而且已開始自動收票':'⚠️ 獎勵建立成功，但自動收票尚未連線：'+(d.eventsub?.error||'請檢查 EventSub 設定')):'❌ '+d.error};
$('drawButton').onclick=async()=>{msg.textContent='🎰 加權抽獎中...';const r=await fetch('/api/draw',{method:'POST'}),d=await r.json();if(!d.ok){msg.textContent='❌ '+d.error;return}$('winner').textContent='🎉 '+d.winner.name+' 🎉';$('drawInfo').textContent=`${d.winner.tickets} 張票 / 全池 ${d.total_tickets} 張（抽獎當下機率 ${d.winner.chance}%）`;msg.textContent='🎊 抽獎完成！'};
$('saveSettingsButton').onclick=saveSettings;
$('unlimitedExtra').onchange=()=>{$('maxExtra').disabled=$('unlimitedExtra').checked};
$('ticketSearch').addEventListener('input',renderTickets);
try{const x=JSON.parse(localStorage.getItem('lotterySettings')||'null');if(x){$('rewardCost').value=x.reward_cost||500;$('unlimitedExtra').checked=!!x.unlimited;if(!x.unlimited&&x.max_extra>0)$('maxExtra').value=x.max_extra;$('maxExtra').disabled=!!x.unlimited}}catch(e){}
loadSettings();loadTickets();setInterval(loadTickets,5000);

// ----- 管理員修改紀錄 -----
let auditItems=[];
function fmtAuditTime(value){
  if(!value)return '-';
  const d=new Date(value);
  if(Number.isNaN(d.getTime()))return value;
  return new Intl.DateTimeFormat('zh-TW',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(d);
}
function renderAudit(){
  const q=($('auditSearch')?.value||'').trim().toLowerCase();
  const list=q?auditItems.filter(x=>(x.name||'').toLowerCase().includes(q)||(x.reason||'').toLowerCase().includes(q)||String(x.user_id||'').includes(q)):auditItems;
  $('auditBody').innerHTML=list.map(x=>{
    const oldTotal=x.old_total==null?null:Number(x.old_total), newTotal=x.new_total==null?null:Number(x.new_total);
    const oldAdj=Number(x.old_adjustment||0), newAdj=Number(x.new_adjustment||0);
    const before=oldTotal==null?`修正 ${oldAdj>0?'+':''}${oldAdj}`:oldTotal;
    const after=newTotal==null?`修正 ${newAdj>0?'+':''}${newAdj}`:newTotal;
    const delta=(newTotal!=null&&oldTotal!=null)?newTotal-oldTotal:newAdj-oldAdj;
    const cls=delta>0?'change-pos':delta<0?'change-neg':'change-zero';
    const deltaText=delta>0?`+${delta}`:String(delta);
    return `<tr><td>${esc(fmtAuditTime(x.changed_at))}</td><td>${esc(x.name||x.user_id)}<small class="login">${esc(x.user_id||'')}</small></td><td>${esc(before)}</td><td><b>${esc(after)}</b></td><td class="${cls}">${esc(deltaText)}</td><td class="reason-cell">${esc(x.reason||'手動修正')}</td></tr>`;
  }).join('') || '<tr><td colspan="6">目前沒有符合的修改紀錄</td></tr>';
  $('auditStatus').textContent=`共 ${auditItems.length} 筆紀錄${q?`，目前顯示 ${list.length} 筆`:''}`;
}
async function loadAudit(){
  $('auditStatus').textContent='載入修改紀錄中...';
  try{
    const r=await fetch('/api/admin/audit?ts='+Date.now(),{cache:'no-store'}),d=await r.json();
    if(!r.ok||!d.ok){$('auditStatus').textContent='❌ '+(d.error||`讀取失敗（HTTP ${r.status}）`);return}
    auditItems=d.items||[]; renderAudit();
  }catch(e){$('auditStatus').textContent='❌ 讀取修改紀錄失敗：'+e.message}
}
function openAudit(){
  $('auditModal').classList.add('open'); $('auditModal').setAttribute('aria-hidden','false'); document.body.style.overflow='hidden'; loadAudit();
}
function closeAudit(){
  $('auditModal').classList.remove('open'); $('auditModal').setAttribute('aria-hidden','true'); document.body.style.overflow='';
}
$('auditButton')?.addEventListener('click',openAudit);
$('auditClose')?.addEventListener('click',closeAudit);
document.querySelectorAll('[data-close-audit]').forEach(x=>x.addEventListener('click',closeAudit));
$('auditRefresh')?.addEventListener('click',loadAudit);
$('auditSearch')?.addEventListener('input',renderAudit);
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&$('auditModal')?.classList.contains('open'))closeAudit()});
