"""MES 검색 실험실 (로컬 PoC). Python 3.9 이상, 외부 패키지 없음.

전체 흐름 (자세한 그림은 docs/HOW_SEARCH_WORKS.md 참고)

    브라우저(app.js) --GET /api/search?q=...--> Handler.do_GET()
        --> search()
              1) normalize(검색어)            : 입력 표기 차이를 없앤 "검색 키" 생성
              2) SQLite 에서 문서 읽기        : 업무 범위(category) 필터만 SQL 로 처리
              3) 문서마다 match_terms() 실행  : 제목·문서ID·별칭과 비교해 점수 계산
              4) 본문 부분 일치 확인
              5) 점수 내림차순 정렬 후 JSON 응답
"""
import json
import os
import re
import sqlite3
import time
import unicodedata
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
DB = ROOT / 'data' / 'mes.sqlite3'

# ---------------------------------------------------------------------------
# 샘플 데이터 (합성 데이터, 실제 공장 데이터 아님)
# (문서ID, 제목, 업무 범위, 본문, 별칭 목록)
# 별칭(aliases)은 "이 문서를 찾을 때 사람들이 칠 법한 단어" 사전입니다.
# ---------------------------------------------------------------------------
SEED = [
    ('MES-001', 'MES 재구축 프로젝트', '공통', '냉연 공장 생산 실행 시스템 재구축과 단계별 전환 계획', ['프로젝트', 'project', 'MES', '재구축']),
    ('MES-002', '냉간 압연 작업 지시', '생산', '압연기별 코일 투입 순서와 목표 두께 관리', ['냉연', 'cold rolling', '압연', 'rolling', '작업지시']),
    ('MES-003', '코일 이력 조회', '품질', '입고부터 출하까지 코일의 공정 및 품질 이력 추적', ['코일', 'coil', '이력', 'history']),
    ('MES-004', '소둔 공정 실적', '생산', '소둔로 온도와 유지 시간 및 배치 실적 관리', ['소둔', 'annealing', '실적']),
    ('MES-005', '산세 라인 모니터링', '설비', '산세 라인의 산 농도 및 설비 운전 상태 확인', ['산세', 'pickling', '모니터링', 'monitoring']),
    ('MES-006', '조질 압연 품질 검사', '품질', '표면 조도와 연신율 및 평탄도 검사 결과', ['조질', 'temper rolling', '품질', 'quality', '검사', 'inspection']),
    ('MES-007', '출하 및 포장 지시', '물류', '제품 포장 사양과 출하 일정 및 상차 정보', ['출하', 'shipping', '포장', 'packing']),
    ('MES-008', '설비 예방 정비', '설비', '압연기 롤 교체 주기 및 예방 정비 일정', ['설비', 'equipment', '정비', 'maintenance']),
    ('MES-009', '생산 계획 및 진도', '생산', '수주별 생산 계획과 공정별 진도 확인', ['생산', 'production', '계획', 'plan']),
    ('MES-010', '재고 및 창고 위치', '물류', '코일 재고 수량과 창고 적치 위치 조회', ['재고', 'inventory', '창고', 'warehouse', 'coil']),
    ('MES-011', '품질 개선 프로젝트', '품질', '냉연 강판 표면 결함 감소를 위한 개선 활동', ['프로젝트', 'project', '품질', 'quality']),
    ('MES-012', '강종 및 제품 규격', '공통', 'SPCC 및 SPCD 강종별 두께 폭 허용 공차', ['강종', 'steel grade', '규격', 'specification', 'SPCC', 'SPCD']),
    # 색상 코드 예시: 사용자가 RAL_9006 / ral-9006 / rAl 9006 처럼 다르게 입력해도 찾아야 함.
    # MES-014(RAL9016)는 "숫자 한 자리만 달라도 다른 색"이므로 섞여 나오면 안 되는 비교 대상.
    ('MES-013', '컬러강판 도장 색상 RAL9006', '품질', '화이트 알루미늄 RAL9006 색상 도막 두께 및 색차 관리', ['RAL9006', '화이트 알루미늄', 'white aluminium', '도장', '컬러강판']),
    ('MES-014', '컬러강판 도장 색상 RAL9016', '품질', '트래픽 화이트 RAL9016 색상 도막 두께 및 색차 관리', ['RAL9016', '트래픽 화이트', 'traffic white', '도장', '컬러강판']),
]

# ---------------------------------------------------------------------------
# 1단계: 정규화 (normalize)
# ---------------------------------------------------------------------------
# 검색어와 문서 단어를 "같은 규칙"으로 변환한 뒤 비교합니다.
# 아래 문자는 코드·단어를 끊어 쓸 때만 쓰이는 구분자로 보고 지웁니다.
#   \s      : 공백, 탭, 줄바꿈 (전각 공백은 NFKC 단계에서 일반 공백으로 바뀜)
#   _       : 밑줄 (RAL_9006)
#   -       : 하이픈 (RAL-9006, MES-001)
#   ‐~―, − : 워드·엑셀에서 자동으로 바뀌는 각종 대시(‐ ‑ ‒ – — ―)와 수학 마이너스(−)
# 일부러 지우지 않는 문자:
#   .  : 두께 1.2 와 12 가 같아지면 안 됨
#   /  : '폭/두께' 처럼 의미 있는 구분에 쓰임
#   %, ', = 등 : 지우면 '%' 같은 검색어가 빈 문자열이 되어 전체 문서가 나올 수 있음
SEPARATORS = re.compile(r'[\s_\-‐-―−]+')


def normalize(text):
    """사람마다 다른 입력 표기를 하나의 '검색 키'로 바꿉니다.

    처리 순서 (예: 'ｒＡｌ＿９００６')
      1. NFKC   : 전각 문자를 반각으로, 분해된 한글을 조합형으로  -> 'rAl_9006'
      2. casefold: 대소문자 통일 (lower 보다 강한 유니코드 규칙)    -> 'ral_9006'
      3. 구분자 제거: 공백, _, -, 각종 대시 제거                    -> 'ral9006'
    """
    text = unicodedata.normalize('NFKC', text).casefold()
    return SEPARATORS.sub('', text)


# ---------------------------------------------------------------------------
# 오타 보정용 편집 거리
# ---------------------------------------------------------------------------
def distance(a, b):
    """Levenshtein 거리: a 를 b 로 바꾸는 데 필요한 최소 삽입·삭제·교체 횟수.

    예) '후로젝트' -> '프로젝트' = 1 (첫 글자 교체 1회)
    동적 계획법(DP)으로 한 행씩 계산합니다. 길이는 호출하는 쪽에서 30자 이하로 제한합니다.
    """
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(cur[-1] + 1,          # 삽입
                           prev[j] + 1,          # 삭제
                           prev[j - 1] + (x != y)))  # 교체 (같으면 0)
        prev = cur
    return prev[-1]


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------
def connect(path=DB):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row  # 컬럼 이름으로 접근 (row['title'])
    return con


def init_db(path=DB):
    """테이블이 없으면 만들고 샘플 데이터를 넣습니다.

    INSERT OR IGNORE: 같은 문서ID가 이미 있으면 건너뜀 -> 기존 데이터 보존, 새 샘플만 추가.
    closing(...) : 사용 후 연결을 반드시 닫음. (Windows 에서는 열린 DB 파일을 지울 수 없음)
    """
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with closing(connect(path)) as con, con:  # 두 번째 con: 트랜잭션 자동 commit
        con.execute('CREATE TABLE IF NOT EXISTS documents ('
                    'id TEXT PRIMARY KEY, title TEXT NOT NULL, category TEXT NOT NULL, '
                    'body TEXT NOT NULL, aliases TEXT NOT NULL)')
        con.executemany('INSERT OR IGNORE INTO documents VALUES (?,?,?,?,?)',
                        [(i, t, c, b, json.dumps(a, ensure_ascii=False)) for i, t, c, b, a in SEED])


# ---------------------------------------------------------------------------
# 2단계: 단어별 비교 규칙과 점수
# ---------------------------------------------------------------------------
SCORE_EXACT = 100    # 정규화 후 완전히 같음
SCORE_PARTIAL = 85   # 검색어가 단어 안에 포함됨 (프로젝 -> 프로젝트)
SCORE_BODY = 75      # 본문에 포함됨
SCORE_FUZZY = 70     # 오타 보정. 편집 1회마다 8점 감점 -> 62, 54
NO_FUZZY_TERMS = ('SPCC', 'SPCD')  # 강종 코드: 한 글자 차이도 다른 강종이므로 오타 보정 금지


def fuzzy_allowed(q, n, term):
    """오타 보정을 시도해도 안전한 경우인지 판단합니다.

    숫자가 섞인 값(RAL9006, MES-001, 코일번호)은 숫자 한 자리만 달라도 전혀 다른 대상이므로
    오타 보정을 하지 않습니다. RAL9007 을 쳤을 때 RAL9006 이 나오면 오검색입니다.
    """
    return (term not in NO_FUZZY_TERMS
            and 3 <= len(q) <= 30                       # 너무 짧으면 아무 단어나 걸림
            and not any(ch.isdigit() for ch in q + n)   # 숫자 포함 값 제외
            and abs(len(q) - len(n)) <= 2)              # 길이가 많이 다르면 계산할 필요 없음


def match_terms(q, terms, fuzzy):
    """정규화된 검색어 q 를 문서의 단어(제목·ID·별칭)들과 비교해 (점수, 이유, 단어) 목록을 돌려줍니다."""
    matches = []
    for term in terms:
        n = normalize(term)
        if q == n:
            matches.append((SCORE_EXACT, '정확·정규화 일치', term))
        elif q in n:
            matches.append((SCORE_PARTIAL, '부분 일치', term))
        elif fuzzy and fuzzy_allowed(q, n, term):
            d = distance(q, n)
            limit = 1 if len(q) < 6 else 2               # 3~5자: 1회, 6~30자: 2회까지 허용
            if d <= limit and d / max(len(q), len(n)) <= 0.34:  # 길이 대비 34% 이하만
                matches.append((SCORE_FUZZY - d * 8, '오타 유사 일치', term))
    return matches


# ---------------------------------------------------------------------------
# 3단계: 검색 본체
# ---------------------------------------------------------------------------
def search(query, category='', fuzzy=True, path=DB):
    start = time.perf_counter()
    if len(query) > 100:
        raise ValueError('검색어는 100자 이하로 입력하세요.')
    q = normalize(query)
    show_all = not query.strip()  # 빈 입력(공백만)일 때만 전체 목록. '---' 같은 구분자만 입력하면 결과 없음.

    # 업무 범위 필터만 SQL 에서 처리하고(파라미터 바인딩 -> SQL 인젝션 방지), 비교는 파이썬에서 합니다.
    with closing(connect(path)) as con:
        rows = con.execute("SELECT * FROM documents WHERE (? = '' OR category = ?) ORDER BY id",
                           (category, category)).fetchall()

    results = []
    for row in rows:
        doc = dict(row)
        aliases = json.loads(doc.pop('aliases'))
        if show_all:
            score, reason, term = 0, '전체 문서', ''
        else:
            if not q:  # 구분자만 입력됨
                continue
            matches = match_terms(q, [doc['title'], doc['id']] + aliases, fuzzy)
            if q in normalize(doc['body']):
                matches.append((SCORE_BODY, '본문 부분 일치', query))
            if not matches:
                continue
            # 여러 단어가 맞으면 가장 높은 점수 하나만 그 문서의 점수로 사용
            score, reason, term = max(matches, key=lambda m: m[0])
            # 한글 제목 문서를 영문 별칭으로 찾은 경우 표시 (예: coil -> 코일 이력 조회)
            if term in aliases and re.search('[a-zA-Z]', term) and not re.search('[a-zA-Z]', doc['title']):
                reason += ' · 한영 사전'
        results.append({**doc, 'aliases': aliases, 'score': score, 'reason': reason, 'matched': term})

    results.sort(key=lambda d: (-d['score'], d['id']))  # 점수 높은 순, 같으면 문서ID 순
    return {'query': query, 'normalized': q, 'total': len(results),
            'elapsed_ms': round((time.perf_counter() - start) * 1000, 2), 'results': results}


# ---------------------------------------------------------------------------
# HTTP 서버: /api/search 와 정적 파일 3개만 제공 (DB 파일 등 다른 경로는 404)
# ---------------------------------------------------------------------------
STATIC = {'/': ('index.html', 'text/html'),
          '/app.js': ('app.js', 'text/javascript'),
          '/style.css': ('style.css', 'text/css')}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urlparse(self.path)
        try:
            if url.path == '/api/search':
                args = parse_qs(url.query)
                data = search(args.get('q', [''])[0], args.get('category', [''])[0],
                              args.get('fuzzy', ['1'])[0] == '1')
                self.respond(200, json.dumps(data, ensure_ascii=False).encode(), 'application/json; charset=utf-8')
            elif url.path in STATIC:
                name, mime = STATIC[url.path]
                self.respond(200, (ROOT / 'static' / name).read_bytes(), mime + '; charset=utf-8')
            else:
                self.respond(404, b'Not found', 'text/plain')
        except ValueError as e:
            self.respond(400, json.dumps({'error': str(e)}, ensure_ascii=False).encode(), 'application/json; charset=utf-8')

    def respond(self, status, body, mime):
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)


if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', '8000'))
    print(f'MES Search Lab: http://127.0.0.1:{port}', flush=True)
    ThreadingHTTPServer(('127.0.0.1', port), Handler).serve_forever()  # 127.0.0.1: 내 PC 에서만 접속 가능
