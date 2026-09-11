import os, secrets, random, sqlite3, json, hmac, hashlib
from datetime import datetime, timezone
from urllib.parse import urlencode
import requests
from flask import Flask, redirect, request, session, render_template, jsonify, url_for
from dotenv import load_dotenv
try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None
    dict_row = None

load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY') or secrets.token_hex(32)
if os.getenv('RENDER'):
    app.config.update(SESSION_COOKIE_SECURE=True, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax')

TWITCH_CLIENT_ID=os.getenv('TWITCH_CLIENT_ID')
TWITCH_CLIENT_SECRET=os.getenv('TWITCH_CLIENT_SECRET')
TWITCH_REDIRECT_URI=os.getenv('TWITCH_REDIRECT_URI','http://localhost:5000/callback')
PUBLIC_URL=os.getenv('PUBLIC_URL','').rstrip('/')
EVENTSUB_SECRET=os.getenv('EVENTSUB_SECRET','')
TWITCH_SCOPE='moderator:read:followers channel:manage:redemptions'
DB_PATH=os.getenv('DB_PATH','lottery.db')
DATABASE_URL=os.getenv('DATABASE_URL','').strip()
USE_POSTGRES=bool(DATABASE_URL)
follower_cache={}

class DBWrapper:
    def __init__(self, conn, postgres=False):
        self.conn = conn
        self.postgres = postgres
    def _sql(self, query):
        return query.replace('?', '%s') if self.postgres else query
    def execute(self, query, params=()):
        return self.conn.execute(self._sql(query), params)
    def commit(self):
        return self.conn.commit()
    def close(self):
        return self.conn.close()

def db():
    if USE_POSTGRES:
        if psycopg is None:
            raise RuntimeError('DATABASE_URL 已設定，但 psycopg 尚未安裝')
        conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
        statements = [
            "CREATE TABLE IF NOT EXISTS channels(channel_id TEXT PRIMARY KEY, display_name TEXT, reward_id TEXT, reward_title TEXT DEFAULT '🎟️ 抽獎券', reward_cost INTEGER DEFAULT 500, max_extra BIGINT DEFAULT 10, created_at TEXT)" ,
            "CREATE TABLE IF NOT EXISTS tickets(channel_id TEXT, user_id TEXT, login TEXT, name TEXT, base_tickets INTEGER DEFAULT 1, redeemed_tickets BIGINT DEFAULT 0, admin_adjustment BIGINT DEFAULT 0, PRIMARY KEY(channel_id,user_id))" ,
            "CREATE TABLE IF NOT EXISTS redemptions(redemption_id TEXT PRIMARY KEY, channel_id TEXT, user_id TEXT, reward_id TEXT, redeemed_at TEXT)" ,
            "CREATE TABLE IF NOT EXISTS audit(id BIGSERIAL PRIMARY KEY, channel_id TEXT, user_id TEXT, name TEXT, old_adjustment BIGINT, new_adjustment BIGINT, reason TEXT, changed_at TEXT)" ,
            "CREATE TABLE IF NOT EXISTS lottery_settings(channel_id TEXT PRIMARY KEY, reward_cost INTEGER NOT NULL DEFAULT 500, max_extra BIGINT NOT NULL DEFAULT 10, updated_at TEXT)" ,
        ]
        for statement in statements:
            conn.execute(statement)
        conn.commit()
        return DBWrapper(conn, postgres=True)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS channels(channel_id TEXT PRIMARY KEY, display_name TEXT, reward_id TEXT, reward_title TEXT DEFAULT '🎟️ 抽獎券', reward_cost INTEGER DEFAULT 500, max_extra INTEGER DEFAULT 10, created_at TEXT);
    CREATE TABLE IF NOT EXISTS tickets(channel_id TEXT, user_id TEXT, login TEXT, name TEXT, base_tickets INTEGER DEFAULT 1, redeemed_tickets INTEGER DEFAULT 0, admin_adjustment INTEGER DEFAULT 0, PRIMARY KEY(channel_id,user_id));
    CREATE TABLE IF NOT EXISTS redemptions(redemption_id TEXT PRIMARY KEY, channel_id TEXT, user_id TEXT, reward_id TEXT, redeemed_at TEXT);
    CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id TEXT, user_id TEXT, name TEXT, old_adjustment INTEGER, new_adjustment INTEGER, reason TEXT, changed_at TEXT);
    CREATE TABLE IF NOT EXISTS lottery_settings(channel_id TEXT PRIMARY KEY, reward_cost INTEGER NOT NULL DEFAULT 500, max_extra INTEGER NOT NULL DEFAULT 10, updated_at TEXT);
    """)
    conn.commit()
    return DBWrapper(conn, postgres=False)

def now(): return datetime.now(timezone.utc).isoformat()
def require_config():
    missing=[x for x,v in [('TWITCH_CLIENT_ID',TWITCH_CLIENT_ID),('TWITCH_CLIENT_SECRET',TWITCH_CLIENT_SECRET)] if not v]
    if missing: raise RuntimeError('Missing environment variables: '+', '.join(missing))
def twitch_headers():
    token=session.get('access_token')
    return {'Authorization':f'Bearer {token}','Client-Id':TWITCH_CLIENT_ID} if token else None
def cache_key():
    if 'cache_key' not in session: session['cache_key']=secrets.token_urlsafe(24)
    return session['cache_key']
def require_user(): return session.get('user')

def ensure_channel(user):
    c=db()
    c.execute('INSERT INTO channels(channel_id,display_name,created_at) VALUES(?,?,?) ON CONFLICT(channel_id) DO NOTHING',(user['id'],user['display_name'],now()))
    c.execute('UPDATE channels SET display_name=? WHERE channel_id=?',(user['display_name'],user['id']))
    # Settings are stored separately so later logins/redeploys can never reset them.
    existing=c.execute('SELECT channel_id FROM lottery_settings WHERE channel_id=?',(user['id'],)).fetchone()
    if not existing:
        legacy=c.execute('SELECT reward_cost,max_extra FROM channels WHERE channel_id=?',(user['id'],)).fetchone()
        rc=(legacy['reward_cost'] if legacy and legacy['reward_cost'] is not None else 500)
        me=(legacy['max_extra'] if legacy and legacy['max_extra'] is not None else 10)
        c.execute('INSERT INTO lottery_settings(channel_id,reward_cost,max_extra,updated_at) VALUES(?,?,?,?)',(user['id'],rc,me,now()))
    c.commit(); c.close()

def upsert_ticket(channel_id,user_id,login,name,base=1):
    c=db(); c.execute('INSERT INTO tickets(channel_id,user_id,login,name,base_tickets) VALUES(?,?,?,?,?) ON CONFLICT(channel_id,user_id) DO NOTHING',(channel_id,user_id,login,name,base)); c.execute('UPDATE tickets SET login=?,name=? WHERE channel_id=? AND user_id=?',(login,name,channel_id,user_id)); c.commit(); c.close()

def public_ticket_data(channel_id):
    c=db(); rows=c.execute('SELECT * FROM tickets WHERE channel_id=?',(channel_id,)).fetchall(); c.close()
    out=[]; total=0
    for r in rows:
        t=max(0,r['base_tickets']+r['redeemed_tickets']+r['admin_adjustment']); total+=t
        out.append({'user_id':r['user_id'],'login':r['login'],'name':r['name'],'base':r['base_tickets'],'redeemed':r['redeemed_tickets'],'adjustment':r['admin_adjustment'],'tickets':t})
    out.sort(key=lambda x:(-x['tickets'],x['name'].lower()))
    for x in out: x['chance']=round((x['tickets']/total*100),3) if total else 0
    return out,total

@app.route('/')
def index(): return render_template('index.html',user=session.get('user'))
@app.route('/login')
def login():
    require_config(); state=secrets.token_urlsafe(32); session['oauth_state']=state
    return redirect('https://id.twitch.tv/oauth2/authorize?'+urlencode({'client_id':TWITCH_CLIENT_ID,'redirect_uri':TWITCH_REDIRECT_URI,'response_type':'code','scope':TWITCH_SCOPE,'state':state,'force_verify':'true'}))
@app.route('/callback')
def callback():
    require_config()
    if request.args.get('error'): return 'Twitch 授權失敗：'+request.args.get('error_description',request.args.get('error')),400
    code=request.args.get('code'); state=request.args.get('state'); expected=session.pop('oauth_state',None)
    if not code or not state or not expected or not secrets.compare_digest(state,expected): return 'OAuth 驗證失敗，請重新登入。',400
    tr=requests.post('https://id.twitch.tv/oauth2/token',data={'client_id':TWITCH_CLIENT_ID,'client_secret':TWITCH_CLIENT_SECRET,'code':code,'grant_type':'authorization_code','redirect_uri':TWITCH_REDIRECT_URI},timeout=20)
    if tr.status_code!=200: return '無法取得 Twitch Access Token：'+tr.text,400
    td=tr.json(); token=td['access_token']; headers={'Authorization':f'Bearer {token}','Client-Id':TWITCH_CLIENT_ID}
    ur=requests.get('https://api.twitch.tv/helix/users',headers=headers,timeout=20); users=ur.json().get('data',[]) if ur.ok else []
    if not users:return '找不到 Twitch 帳號資料',400
    u=users[0]; session['access_token']=token; session['refresh_token']=td.get('refresh_token'); session['user']={'id':u['id'],'login':u['login'],'display_name':u['display_name'],'profile_image_url':u['profile_image_url']}
    ensure_channel(session['user']); follower_cache.pop(cache_key(),None); return redirect(url_for('index'))
@app.route('/logout')
def logout():
    follower_cache.pop(session.get('cache_key'),None); session.clear(); return redirect(url_for('index'))

@app.route('/api/followers')
def followers():
    user=require_user(); headers=twitch_headers()
    if not user or not headers:return jsonify(ok=False,error='尚未登入 Twitch'),401
    arr=[]; cursor=None
    try:
        while True:
            p={'broadcaster_id':user['id'],'moderator_id':user['id'],'first':100};
            if cursor:p['after']=cursor
            r=requests.get('https://api.twitch.tv/helix/channels/followers',headers=headers,params=p,timeout=20)
            if r.status_code in (401,403):return jsonify(ok=False,error='Twitch 授權不足或已失效，請重新登入'),r.status_code
            r.raise_for_status(); d=r.json(); arr += [{'id':i['user_id'],'login':i['user_login'],'name':i['user_name'],'followed_at':i['followed_at']} for i in d.get('data',[])]
            cursor=d.get('pagination',{}).get('cursor')
            if not cursor:break
        follower_cache[cache_key()]=arr
        for p in arr: upsert_ticket(user['id'],p['id'],p['login'],p['name'],1)
        return jsonify(ok=True,count=len(arr),followers=arr)
    except requests.RequestException as e:return jsonify(ok=False,error=f'Twitch API 連線失敗：{e}'),502

@app.route('/api/settings',methods=['GET','PATCH'])
def settings():
    u=require_user()
    if not u:return jsonify(ok=False,error='尚未登入'),401
    ensure_channel(u)
    if request.method=='GET':
        c=db(); row=c.execute('SELECT reward_cost,max_extra,updated_at FROM lottery_settings WHERE channel_id=?',(u['id'],)).fetchone(); c.close()
        data=dict(row) if row else {'reward_cost':500,'max_extra':10}
        data['unlimited']=int(data.get('max_extra',10))<0
        return jsonify(ok=True,settings=data,storage='postgres' if USE_POSTGRES else 'sqlite')

    body=request.get_json(silent=True) or {}
    try:
        cost=max(1,int(body.get('reward_cost',500)))
        unlimited=bool(body.get('unlimited',False))
        max_extra=-1 if unlimited else max(1,int(body.get('max_extra',10)))
    except (TypeError,ValueError):
        return jsonify(ok=False,error='設定格式錯誤'),400

    c=db()
    c.execute('INSERT INTO lottery_settings(channel_id,reward_cost,max_extra,updated_at) VALUES(?,?,?,?) ON CONFLICT(channel_id) DO UPDATE SET reward_cost=excluded.reward_cost,max_extra=excluded.max_extra,updated_at=excluded.updated_at',(u['id'],cost,max_extra,now()))
    # Keep legacy columns in sync for reward creation / backwards compatibility.
    c.execute('UPDATE channels SET reward_cost=?,max_extra=? WHERE channel_id=?',(cost,max_extra,u['id']))
    row=c.execute('SELECT reward_id FROM channels WHERE channel_id=?',(u['id'],)).fetchone()
    c.commit(); c.close()

    twitch_updated=False; twitch_error=None
    if row and row['reward_id'] and body.get('sync_twitch',True):
        payload={'cost':cost,'is_max_per_user_per_stream_enabled':not unlimited}
        if not unlimited: payload['max_per_user_per_stream']=max_extra
        try:
            r=requests.patch('https://api.twitch.tv/helix/channel_points/custom_rewards',headers=twitch_headers(),params={'broadcaster_id':u['id'],'id':row['reward_id']},json=payload,timeout=20)
            twitch_updated=r.ok
            if not r.ok: twitch_error=r.text
        except requests.RequestException as e:
            twitch_error=str(e)
    return jsonify(ok=True,reward_cost=cost,max_extra=max_extra,unlimited=unlimited,twitch_updated=twitch_updated,twitch_error=twitch_error,storage='postgres' if USE_POSTGRES else 'sqlite')

@app.route('/api/reward',methods=['POST'])
def create_reward():
    u=require_user(); headers=twitch_headers()
    if not u:return jsonify(ok=False,error='尚未登入'),401
    body=request.get_json(silent=True) or {}; cost=max(1,int(body.get('cost',500))); unlimited=bool(body.get('unlimited',False)); limit=-1 if unlimited else max(1,int(body.get('max_extra',10))); title=(body.get('title') or '🎟️ 抽獎券')[:45]
    payload={'title':title,'cost':cost,'prompt':'兌換後會增加本次抽獎券 1 張','is_max_per_user_per_stream_enabled':not unlimited,'should_redemptions_skip_request_queue':True}
    if not unlimited: payload['max_per_user_per_stream']=limit
    r=requests.post('https://api.twitch.tv/helix/channel_points/custom_rewards',headers=headers,params={'broadcaster_id':u['id']},json=payload,timeout=20)
    if not r.ok:return jsonify(ok=False,error='建立 Twitch 頻道點數獎勵失敗：'+r.text),r.status_code
    reward=r.json()['data'][0]; c=db(); c.execute('UPDATE channels SET reward_id=?,reward_title=?,reward_cost=?,max_extra=? WHERE channel_id=?',(reward['id'],title,cost,limit,u['id'])); c.execute('INSERT INTO lottery_settings(channel_id,reward_cost,max_extra,updated_at) VALUES(?,?,?,?) ON CONFLICT(channel_id) DO UPDATE SET reward_cost=excluded.reward_cost,max_extra=excluded.max_extra,updated_at=excluded.updated_at',(u['id'],cost,limit,now())); c.commit(); c.close()
    sub_result=subscribe_eventsub(u['id'],reward['id'],session.get('access_token'))
    return jsonify(ok=True,reward=reward,eventsub=sub_result)

def subscribe_eventsub(channel_id,reward_id,token):
    if not PUBLIC_URL or not EVENTSUB_SECRET:return {'ok':False,'error':'尚未設定 PUBLIC_URL / EVENTSUB_SECRET'}
    payload={'type':'channel.channel_points_custom_reward_redemption.add','version':'1','condition':{'broadcaster_user_id':channel_id,'reward_id':reward_id},'transport':{'method':'webhook','callback':PUBLIC_URL+'/eventsub','secret':EVENTSUB_SECRET}}
    r=requests.post('https://api.twitch.tv/helix/eventsub/subscriptions',headers={'Authorization':f'Bearer {token}','Client-Id':TWITCH_CLIENT_ID,'Content-Type':'application/json'},json=payload,timeout=20)
    return {'ok':r.ok,'status':r.status_code,'body':r.json() if r.content else {}}

def valid_eventsub(raw):
    if not EVENTSUB_SECRET:return False
    mid=request.headers.get('Twitch-Eventsub-Message-Id',''); ts=request.headers.get('Twitch-Eventsub-Message-Timestamp',''); sig=request.headers.get('Twitch-Eventsub-Message-Signature','')
    expected='sha256='+hmac.new(EVENTSUB_SECRET.encode(),(mid+ts).encode()+raw,hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected,sig)

@app.route('/eventsub',methods=['POST'])
def eventsub():
    raw=request.get_data()
    if not valid_eventsub(raw):return 'invalid signature',403
    data=request.get_json(); typ=request.headers.get('Twitch-Eventsub-Message-Type')
    if typ=='webhook_callback_verification':return data.get('challenge',''),200
    if typ=='notification':
        e=data.get('event',{}); rid=e.get('id'); channel=e.get('broadcaster_user_id'); reward=e.get('reward',{}).get('id'); uid=e.get('user_id')
        c=db(); cfg=c.execute('SELECT reward_id,max_extra FROM channels WHERE channel_id=?',(channel,)).fetchone()
        if cfg and cfg['reward_id']==reward and rid:
            exists=c.execute('SELECT 1 FROM redemptions WHERE redemption_id=?',(rid,)).fetchone()
            if not exists:
                c.execute('INSERT INTO tickets(channel_id,user_id,login,name,base_tickets) VALUES(?,?,?,?,1) ON CONFLICT(channel_id,user_id) DO NOTHING',(channel,uid,e.get('user_login',''),e.get('user_name','')))
                row=c.execute('SELECT redeemed_tickets FROM tickets WHERE channel_id=? AND user_id=?',(channel,uid)).fetchone(); current=row['redeemed_tickets'] if row else 0
                if cfg['max_extra'] < 0 or current < cfg['max_extra']:
                    c.execute('UPDATE tickets SET redeemed_tickets=redeemed_tickets+1,login=?,name=? WHERE channel_id=? AND user_id=?',(e.get('user_login',''),e.get('user_name',''),channel,uid))
                c.execute('INSERT INTO redemptions VALUES(?,?,?,?,?)',(rid,channel,uid,reward,e.get('redeemed_at',now())))
                c.commit()
        c.close()
    return '',204

@app.route('/api/tickets')
def tickets_api():
    u=require_user();
    if not u:return jsonify(ok=False,error='尚未登入'),401
    rows,total=public_ticket_data(u['id']); return jsonify(ok=True,people=rows,total_tickets=total,participants=len([x for x in rows if x['tickets']>0]))

@app.route('/public/<channel_id>')
def public_page(channel_id):
    c=db(); ch=c.execute('SELECT * FROM channels WHERE channel_id=?',(channel_id,)).fetchone(); c.close()
    if not ch:return '找不到這個抽獎頻道',404
    return render_template('public.html',channel=dict(ch))
@app.route('/api/public/<channel_id>')
def public_api(channel_id):
    rows,total=public_ticket_data(channel_id); return jsonify(ok=True,people=rows,total_tickets=total,participants=len([x for x in rows if x['tickets']>0]))

@app.route('/api/admin/tickets/<user_id>',methods=['PATCH'])
def edit_ticket(user_id):
    u=require_user();
    if not u:return jsonify(ok=False,error='尚未登入'),401
    body=request.get_json(silent=True) or {}; reason=(body.get('reason') or '手動修正')[:200]
    c=db(); row=c.execute('SELECT * FROM tickets WHERE channel_id=? AND user_id=?',(u['id'],user_id)).fetchone()
    if not row:c.close(); return jsonify(ok=False,error='找不到這位觀眾'),404
    desired=max(0,int(body.get('total',row['base_tickets']+row['redeemed_tickets']+row['admin_adjustment']))); new_adj=desired-row['base_tickets']-row['redeemed_tickets']; old=row['admin_adjustment']
    c.execute('UPDATE tickets SET admin_adjustment=? WHERE channel_id=? AND user_id=?',(new_adj,u['id'],user_id)); c.execute('INSERT INTO audit(channel_id,user_id,name,old_adjustment,new_adjustment,reason,changed_at) VALUES(?,?,?,?,?,?,?)',(u['id'],user_id,row['name'],old,new_adj,reason,now())); c.commit(); c.close()
    return jsonify(ok=True,total=desired)
@app.route('/api/admin/audit')
def audit_api():
    u=require_user();
    if not u:return jsonify(ok=False,error='尚未登入'),401
    c=db(); rows=c.execute('SELECT * FROM audit WHERE channel_id=? ORDER BY id DESC LIMIT 100',(u['id'],)).fetchall(); c.close(); return jsonify(ok=True,items=[dict(r) for r in rows])

@app.route('/api/draw',methods=['POST'])
def draw():
    u=require_user();
    if not u:return jsonify(ok=False,error='尚未登入'),401
    people,total=public_ticket_data(u['id']); pool=[p for p in people if p['tickets']>0]
    if not pool or total<=0:return jsonify(ok=False,error='目前沒有可抽的票'),400
    pick=random.SystemRandom().randrange(total); running=0; winner=None
    for p in pool:
        running+=p['tickets']
        if pick<running:winner=p;break
    return jsonify(ok=True,winner=winner,total_tickets=total,participants=len(pool),drawn_at=now())
@app.route('/health')
def health():return jsonify(ok=True)
if __name__=='__main__': require_config(); app.run(host='0.0.0.0',port=int(os.getenv('PORT','5000')),debug=True)
