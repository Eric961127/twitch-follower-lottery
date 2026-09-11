const $=id=>document.getElementById(id), msg=$('message');
let allPeople=[];
function esc(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function renderTickets(){
  const q=($('ticketSearch')?.value||'').trim().toLowerCase();
  const list=q?allPeople.filter(x=>(x.name||'').toLowerCase().includes(q)||(x.login||'').toLowerCase().includes(q)||String(x.user_id||'').includes(q)):allPeople;
  $('ticketBody').innerHTML=list.map(x=>`<tr><td>${esc(x.name)}<small class="login">@${esc(x.login||x.name)}</small></td><td>${x.base}</td><td>${x.redeemed}</td><td>${x.adjustment>0?'+':''}${x.adjustment}</td><td><b>${x.tickets}</b></td><td>${x.chance}%</td><td><button class="mini" onclick="editTicket('${x.user_id}',${x.tickets},${JSON.stringify(x.name)})">修改</button></td></tr>`).join('');
  if($('searchCount')) $('searchCount').textContent=q?`找到 ${list.length} 人`:`共 ${allPeople.length} 人`;
}
async function loadTickets(){const r=await fetch('/api/tickets'),d=await r.json();if(!d.ok)return;$('participantCount').textContent=d.participants;$('ticketCount').textContent=d.total_tickets;allPeople=d.people;renderTickets()}
async function loadSettings(){
  const r=await fetch('/api/settings'),d=await r.json(); if(!d.ok)return;
  const s=d.settings||{}; if(s.reward_cost!=null)$('rewardCost').value=s.reward_cost;
  const unlimited=Number(s.max_extra)<0; $('unlimitedExtra').checked=unlimited;
  if(!unlimited && s.max_extra!=null)$('maxExtra').value=s.max_extra;
  $('maxExtra').disabled=unlimited;
}
async function saveSettings(){
  const unlimited=$('unlimitedExtra').checked;
  $('settingsStatus').textContent='儲存中...';
  const r=await fetch('/api/settings',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({reward_cost:Number($('rewardCost').value),max_extra:Number($('maxExtra').value),unlimited,sync_twitch:true})});
  const d=await r.json();
  if(!d.ok){$('settingsStatus').textContent='❌ '+d.error;return}
  $('settingsStatus').textContent=d.twitch_error?'✅ 已永久保存；Twitch 獎勵同步失敗，可稍後再試':'✅ 已永久保存'+(d.twitch_updated?'，Twitch 獎勵也已同步':'');
}
async function editTicket(id,current,name){const total=prompt(`把 ${name} 的總票數改成多少？`,current);if(total===null)return;const reason=prompt('修改原因（例如：系統重複計票）','手動修正');if(reason===null)return;const r=await fetch('/api/admin/tickets/'+id,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({total:Number(total),reason})});const d=await r.json();msg.textContent=d.ok?'✅ 已修改票數':'❌ '+d.error;loadTickets()}
$('updateButton').onclick=async()=>{msg.textContent='正在更新追隨者...';const r=await fetch('/api/followers'),d=await r.json();msg.textContent=d.ok?`✅ 已同步 ${d.count} 位追隨者，每人基本 1 張票`:'❌ '+d.error;loadTickets()};
$('rewardButton').onclick=async()=>{if(!confirm('建立 Twitch 頻道點數「抽獎券」獎勵？'))return;await saveSettings();msg.textContent='建立中...';const r=await fetch('/api/reward',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cost:Number($('rewardCost').value),max_extra:Number($('maxExtra').value),unlimited:$('unlimitedExtra').checked})}),d=await r.json();msg.textContent=d.ok?(d.eventsub?.ok?'✅ 抽獎券建立完成，而且已開始自動收票':'⚠️ 獎勵建立成功，但自動收票尚未連線：'+(d.eventsub?.error||'請檢查 EventSub 設定')):'❌ '+d.error};
$('drawButton').onclick=async()=>{msg.textContent='🎰 加權抽獎中...';const r=await fetch('/api/draw',{method:'POST'}),d=await r.json();if(!d.ok){msg.textContent='❌ '+d.error;return}$('winner').textContent='🎉 '+d.winner.name+' 🎉';$('drawInfo').textContent=`${d.winner.tickets} 張票 / 全池 ${d.total_tickets} 張（抽獎當下機率 ${d.winner.chance}%）`;msg.textContent='🎊 抽獎完成！'};
$('saveSettingsButton').onclick=saveSettings;
$('unlimitedExtra').onchange=()=>{$('maxExtra').disabled=$('unlimitedExtra').checked};
$('ticketSearch').addEventListener('input',renderTickets);
loadSettings();loadTickets();setInterval(loadTickets,5000);
