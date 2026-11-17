import json
import sqlite3
import tempfile
import unicodedata
import unittest
from pathlib import Path
from app import SEED, init_db, search


def fullwidth(text):
    """ABC-1 -> ＡＢＣ－１ (한글 키보드 전각 모드 입력 흉내)"""
    return ''.join(chr(ord(c) + 0xFEE0) if '!' <= c <= '~' else c for c in text)


def variants(term):
    """한 단어로 사람들이 칠 법한 표기를 자동 생성. 특정 단어를 가정하지 않음."""
    joined = term.replace(' ', '')
    return {term, term.upper(), term.lower(), term.swapcase(),
            term.replace(' ', '_'), term.replace(' ', '-'), joined,
            '_'.join(joined), '-'.join(joined), ' '.join(joined),   # 글자마다 구분자
            fullwidth(term), unicodedata.normalize('NFD', term)}     # 전각, 분해형 한글

class SearchTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=Path(self.tmp.name)/'test.sqlite3'
        init_db(self.db)
    def tearDown(self):
        self.tmp.cleanup()
    def ids(self,q,**kw):
        return [r['id'] for r in search(q,path=self.db,**kw)['results']]
    def test_requested_variants(self):
        for q in ['프로젝트','프 로 젝 트','project','Project','PROJECT','프로 젝트','프로젝','후로젝트']:
            with self.subTest(q=q):
                self.assertEqual(self.ids(q),['MES-001','MES-011'])
    def test_fuzzy_switch(self):
        self.assertEqual(self.ids('후로젝트',fuzzy=False),[])
    def test_aliases(self):
        self.assertEqual(self.ids('ＣＯＩＬ'),['MES-003','MES-010'])
    def test_filter(self):
        self.assertEqual(self.ids('project',category='품질'),['MES-011'])
    def test_no_false_positive(self):
        for q in ['없는검색어','%','\' OR 1=1 --','MES-099','후','SPCE']:
            self.assertEqual(self.ids(q),[],q)
    def test_unicode_and_empty(self):
        import unicodedata
        self.assertEqual(self.ids(unicodedata.normalize('NFD','프로젝트')),self.ids('프로젝트'))
        self.assertEqual(len(self.ids('   ')),14)
    def test_code_separator_variants(self):
        # 사용자가 실제로 입력하는 다양한 색상 코드 표기 -> 모두 RAL9006 문서 하나만
        variants=['RAL9006','RAL_9006','RAL-9006','RAL 9006','ral_9006','ral-9006','ral 9006','rAl 9006',
                  'RAL  9006',' RAL9006 ','R-A-L 9006','RAL–9006','RAL−9006','ＲＡＬ－９００６','ＲＡＬ＿９００６']
        for q in variants:
            with self.subTest(q=q):
                r=search(q,path=self.db)
                self.assertEqual(r['normalized'],'ral9006')
                self.assertEqual([x['id'] for x in r['results']],['MES-013'])
                self.assertEqual(r['results'][0]['score'],100)
    def test_separator_variants_all_fields(self):
        # 구분자 무시는 RAL 전용이 아니라 모든 검색어·모든 필드(제목, 문서ID, 별칭, 본문)에 적용됨
        cases={'MES-001':['mes_001','mes 001','Mes001','ＭＥＳ－００１'],          # 문서ID
               'MES-002':['COLD_ROLLING','cold-rolling','ColdRolling',           # 영문 별칭
                          '작업_지시','작업-지시','목표_두께','cold_roling'],      # 한글 별칭, 본문, 오타+구분자
               'MES-012':['SP-CC','s_p_c_c','steel_grade']}                      # 강종 코드
        for doc,qs in cases.items():
            for q in qs:
                with self.subTest(q=q):
                    self.assertEqual(self.ids(q),[doc])
        self.assertEqual(self.ids('후로젝-트'),['MES-001','MES-011'])
    def test_every_stored_term_all_variants(self):
        # DB 에 있는 모든 문서의 모든 단어(제목, 문서ID, 별칭)를 자동으로 변형해서 검색
        # -> 단어별 하드코딩 없이 같은 규칙이 적용됨을 확인
        count=0
        for doc_id,title,_,_,aliases in SEED:
            for term in [title,doc_id]+aliases:
                for q in variants(term):
                    with self.subTest(term=term,q=q):
                        hit={r['id']:r['score'] for r in search(q,path=self.db)['results']}
                        self.assertEqual(hit.get(doc_id),100)
                        count+=1
        self.assertGreater(count,500)
    def test_new_word_needs_no_code_change(self):
        # 소스코드에 없는 새 문서를 DB 에만 추가해도 같은 규칙으로 검색됨
        with sqlite3.connect(self.db) as con:
            con.execute('INSERT INTO documents VALUES (?,?,?,?,?)',('NEW-001','용융아연도금 강판','품질',
                        '도금 부착량 Z275 관리',json.dumps(['Galvanized Steel','GI-275','용융아연도금'])))
        con.close()
        for q in ['galvanized_steel','GALVANIZED-STEEL','Galvanized  Steel','gi 275','gi_275','ＧＩ－２７５',
                  'z_275','용융_아연_도금','용융-아연도금','galvanised steel']:   # 마지막은 오타 보정
            with self.subTest(q=q):
                self.assertEqual(self.ids(q),['NEW-001'])
        self.assertEqual(self.ids('GI-276'),[])   # 숫자 다르면 다른 코드
    def test_code_detection_is_generic(self):
        from app import is_code
        for t in ['SPCC','SPCD','MES','RAL9006','MES-001','GI-275','SGCC','ＳＰＣＣ']:
            self.assertTrue(is_code(t),t)
        for t in ['project','cold rolling','Coil','프로젝트','Galvanized Steel','1234']:
            self.assertFalse(is_code(t),t)
        self.assertEqual(self.ids('SPCE'),[])   # 코드라서 오타 보정 안 함
    def test_code_no_false_positive(self):
        # 숫자 한 자리 차이는 다른 색 -> 오타 보정으로 섞이면 안 됨
        self.assertEqual(self.ids('RAL-9016'),['MES-014'])
        for q in ['RAL9007','ral_9005','RAL-9060']:
            self.assertEqual(self.ids(q),[],q)
    def test_code_partial(self):
        self.assertEqual(self.ids('ral'),['MES-013','MES-014'])
        self.assertEqual(self.ids('9006'),['MES-013'])
        self.assertEqual(self.ids('mes 001'),['MES-001'])
    def test_separator_only(self):
        for q in ['-','___',' - _ ']:
            self.assertEqual(self.ids(q),[],q)
    def test_limit(self):
        with self.assertRaises(ValueError): search('a'*101,path=self.db)
    def test_persistence(self):
        init_db(self.db)
        self.assertEqual(len(self.ids('')),14)

if __name__=='__main__': unittest.main()
