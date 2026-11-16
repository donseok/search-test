import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.request import urlopen
from urllib.error import HTTPError
from urllib.parse import urlencode
from app import Handler, init_db

class HTTPTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()
        cls.base='http://127.0.0.1:'+str(cls.server.server_port)
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join()
    def test_search_endpoint(self):
        with urlopen(self.base+'/api/search?'+urlencode({'q':'후로젝트','category':'공통'})) as r:
            data=json.load(r)
            self.assertEqual([x['id'] for x in data['results']],['MES-001'])
    def test_static(self):
        for path,mime in [('/','text/html'),('/app.js','text/javascript'),('/style.css','text/css')]:
            with urlopen(self.base+path) as r:
                self.assertIn(mime,r.headers['Content-Type'])
                self.assertTrue(r.read())
    def test_private_paths(self):
        for path in ['/data/mes.sqlite3','/../app.py','/app.py']:
            with self.assertRaises(HTTPError) as ctx: urlopen(self.base+path)
            self.assertEqual(ctx.exception.code,404)
    def test_invalid_query(self):
        with self.assertRaises(HTTPError) as ctx: urlopen(self.base+'/api/search?q='+'a'*101)
        self.assertEqual(ctx.exception.code,400)
