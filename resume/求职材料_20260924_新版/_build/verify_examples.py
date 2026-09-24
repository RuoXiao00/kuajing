from pathlib import Path
import re, asyncio, sqlite3
ROOT=Path(__file__).resolve().parent.parent
ai=next(ROOT.glob('05*.md')).read_text(encoding='utf-8')
fde=next(ROOT.glob('06*.md')).read_text(encoding='utf-8')
ns={}
for text in [ai,fde]:
    for source in re.findall(r'```python\n(.*?)```',text,re.S):
        exec(compile(source,'interview_exercise','exec'),ns)

cases=[{'asin':'a','price':0},{'asin':' A ','price':'2.50'},
       {'asin':'a','price':'5'},{'asin':'b','price':True},
       {'asin':'c','price':'NaN'},{'asin':'d','price':'Infinity'},
       {'asin':'e','price':None},None]
res=ns['valid_products'](cases)
assert len(res)==1 and res[0]['asin']=='A' and str(res[0]['price'])=='2.50'
assert ns['valid_products']([])==[]
res=ns['normalize_products']([{'id':0,'price':'3.25'},{'id':0,'price':'5'},
   {'id':1,'price':0},{'id':1,'price':'2'}, {'id':2,'price':True},
   {'id':3,'price':'NaN'},{'id':4,'price':'Infinity'},None])
assert res==[{'id':'0','price':'3.25'},{'id':'1','price':'2'}]

async def check_batch():
    active=peak=0
    async def call(x):
        nonlocal active,peak
        active+=1; peak=max(peak,active)
        try:
            await asyncio.sleep(.01)
            if x==2: raise ValueError('fixture')
            return x*10
        finally: active-=1
    res=await ns['batch_call'](list(range(7)),call)
    assert peak==3 and active==0 and len(res)==7
    assert res[2]=={'ok':False,'error':'upstream_error'}
    assert [res[i]['value'] for i in [0,1,3,4,5,6]]==[0,10,30,40,50,60]
    async def slow(x): await asyncio.sleep(20)
    task=asyncio.create_task(ns['batch_call']([1],slow))
    await asyncio.sleep(.01); task.cancel()
    try: await task
    except asyncio.CancelledError: pass
    else: raise AssertionError('cancel must propagate')
asyncio.run(check_batch())

db=sqlite3.connect(':memory:')
db.execute('CREATE TABLE image_jobs(id INTEGER, owner TEXT, status TEXT, updated_at TEXT)')
db.executemany('INSERT INTO image_jobs VALUES(?,?,?,?)',[
    (1,'a','completed','2026-09-23'),(2,'a','completed','2026-09-23'),
    (3,'a','failed','2026-09-24'),(4,'b','completed','2026-09-22')])
query=re.search(r'```sql\n(.*?)```',ai,re.S)[1]
assert sorted(db.execute(query).fetchall())==[(2,'a','2026-09-23'),(4,'b','2026-09-22')]
db.execute('CREATE TABLE tasks(tenant_id TEXT, status TEXT, created_at TEXT)')
db.executemany('INSERT INTO tasks VALUES(?,?,?)',[
    ('a','failed','2026-09-24T00:00:00Z'),('a','completed','2026-09-24T00:00:00Z'),
    ('b','completed','2026-09-24T00:00:00Z'),('a','failed','2026-09-01T00:00:00Z')])
query=re.search(r'```sql\n(.*?)```',fde,re.S)[1]
assert sorted(db.execute(query,{'since_utc':'2026-09-23T00:00:00Z'}).fetchall())==[
    ('a',2,1,.5),('b',1,0,0.)]
print('Offline interview exercises passed: filtering, deduplication, concurrency, cancellation, and both SQL queries.')
