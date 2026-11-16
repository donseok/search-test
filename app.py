"""Local MES search laboratory. Python 3.9+, no dependencies."""
import json
import os
import re
import sqlite3
import time
import unicodedata
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parent
DB = ROOT / 'data' / 'mes.sqlite3'
SEED = [
 ('MES-001','MES 재구축 프로젝트','공통','냉연 공장 생산 실행 시스템 재구축과 단계별 전환 계획',['프로젝트','project','MES','재구축']),
 ('MES-002','냉간 압연 작업 지시','생산','압연기별 코일 투입 순서와 목표 두께 관리',['냉연','cold rolling','압연','rolling','작업지시']),
 ('MES-003','코일 이력 조회','품질','입고부터 출하까지 코일의 공정 및 품질 이력 추적',['코일','coil','이력','history']),
 ('MES-004','소둔 공정 실적','생산','소둔로 온도와 유지 시간 및 배치 실적 관리',['소둔','annealing','실적']),
 ('MES-005','산세 라인 모니터링','설비','산세 라인의 산 농도 및 설비 운전 상태 확인',['산세','pickling','모니터링','monitoring']),
 ('MES-006','조질 압연 품질 검사','품질','표면 조도와 연신율 및 평탄도 검사 결과',['조질','temper rolling','품질','quality','검사','inspection']),
 ('MES-007','출하 및 포장 지시','물류','제품 포장 사양과 출하 일정 및 상차 정보',['출하','shipping','포장','packing']),
 ('MES-008','설비 예방 정비','설비','압연기 롤 교체 주기 및 예방 정비 일정',['설비','equipment','정비','maintenance']),
 ('MES-009','생산 계획 및 진도','생산','수주별 생산 계획과 공정별 진도 확인',['생산','production','계획','plan']),
 ('MES-010','재고 및 창고 위치','물류','코일 재고 수량과 창고 적치 위치 조회',['재고','inventory','창고','warehouse','coil']),
 ('MES-011','품질 개선 프로젝트','품질','냉연 강판 표면 결함 감소를 위한 개선 활동',['프로젝트','project','품질','quality']),
 ('MES-012','강종 및 제품 규격','공통','SPCC 및 SPCD 강종별 두께 폭 허용 공차',['강종','steel grade','규격','specification','SPCC','SPCD']),
]

def normalize(text):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', text).casefold())

def distance(a, b):
    """Levenshtein distance; lengths are bounded by the caller."""
    prev = list(range(len(b)+1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(cur[-1]+1, prev[j]+1, prev[j-1]+(x != y)))
        prev = cur
    return prev[-1]

def connect(path=DB):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con

def init_db(path=DB):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as con:
        con.execute('CREATE TABLE IF NOT EXISTS documents (id TEXT PRIMARY KEY,title TEXT NOT NULL,category TEXT NOT NULL,body TEXT NOT NULL,aliases TEXT NOT NULL)')
        con.executemany('INSERT OR IGNORE INTO documents VALUES (?,?,?,?,?)', [(i,t,c,b,json.dumps(a,ensure_ascii=False)) for i,t,c,b,a in SEED])

def search(query, category='', fuzzy=True, path=DB):
    start = time.perf_counter()
    if len(query) > 100:
        raise ValueError('검색어는 100자 이하로 입력하세요.')
    q = normalize(query)
    with connect(path) as con:
        rows = con.execute('SELECT * FROM documents WHERE (? = \'\' OR category = ?) ORDER BY id', (category,category)).fetchall()
    results=[]
    for row in rows:
        doc=dict(row); aliases=json.loads(doc.pop('aliases'))
        terms=[doc['title'],doc['id']]+aliases
        matches=[]
        if q:
            for term in terms:
                n=normalize(term)
                if q==n:
                    matches.append((100,'정확·정규화 일치',term))
                elif q in n:
                    matches.append((85,'부분 일치',term))
                # Never fuzzy-match identifiers, numbers, or very short input.
                elif fuzzy and term not in ('SPCC','SPCD') and 3<=len(q)<=30 and not any(ch.isdigit() for ch in q+n) and abs(len(q)-len(n))<=2:
                    d=distance(q,n); limit=1 if len(q)<6 else 2
                    if d<=limit and d/max(len(q),len(n))<=0.34:
                        matches.append((70-d*8,'오타 유사 일치',term))
            if q in normalize(doc['body']):
                matches.append((75,'본문 부분 일치',query))
            if not matches:
                continue
            score,reason,term=max(matches,key=lambda m:m[0])
            if term in aliases and re.search('[a-zA-Z]',term) and not re.search('[a-zA-Z]',doc['title']):
                reason += ' · 한영 사전'
        else:
            score,reason,term=0,'전체 문서',''
        results.append({**doc,'aliases':aliases,'score':score,'reason':reason,'matched':term})
    results.sort(key=lambda d:(-d['score'],d['id']))
    return {'query':query,'normalized':q,'total':len(results),'elapsed_ms':round((time.perf_counter()-start)*1000,2),'results':results}

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url=urlparse(self.path)
        try:
            if url.path=='/api/search':
                args=parse_qs(url.query)
                data=search(args.get('q',[''])[0],args.get('category',[''])[0],args.get('fuzzy',['1'])[0]=='1')
                self.respond(200,json.dumps(data,ensure_ascii=False).encode(),'application/json; charset=utf-8')
            elif url.path in ('/','/app.js','/style.css'):
                name={'/':'index.html','/app.js':'app.js','/style.css':'style.css'}[url.path]
                mime={'index.html':'text/html','app.js':'text/javascript','style.css':'text/css'}[name]
                self.respond(200,(ROOT/'static'/name).read_bytes(),mime+'; charset=utf-8')
            else:
                self.respond(404,b'Not found','text/plain')
        except ValueError as e:
            self.respond(400,json.dumps({'error':str(e)},ensure_ascii=False).encode(),'application/json; charset=utf-8')
    def respond(self,status,body,mime):
        self.send_response(status); self.send_header('Content-Type',mime)
        self.send_header('Content-Length',str(len(body))); self.send_header('Cache-Control','no-store')
        self.end_headers(); self.wfile.write(body)

if __name__=='__main__':
    init_db()
    port=int(os.environ.get('PORT','8000'))
    print(f'MES Search Lab: http://127.0.0.1:{port}',flush=True)
    ThreadingHTTPServer(('127.0.0.1',port),Handler).serve_forever()
