import tempfile
import unittest
from pathlib import Path
from app import init_db, search

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
        self.assertEqual(len(self.ids('   ')),12)
    def test_limit(self):
        with self.assertRaises(ValueError): search('a'*101,path=self.db)
    def test_persistence(self):
        init_db(self.db)
        self.assertEqual(len(self.ids('')),12)

if __name__=='__main__': unittest.main()
