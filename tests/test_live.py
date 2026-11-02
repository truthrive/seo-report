import unittest

from seo_report import live as LIVE


class Fake:
    def __init__(self, cid):
        self.id = cid

    def on_delete(self, fn):
        self.drop = fn


class LiveTest(unittest.TestCase):
    def setUp(self):
        LIVE._PAGES.clear()

    def test_targets_by_email_project_and_keep(self):
        for cid, who, p in (("a", "X@abc.vn", "p1"), ("b", "x@abc.vn", "p2"), ("c", "y@abc.vn", "p1")):
            LIVE.register(Fake(cid), who, p)
        self.assertEqual(sorted(LIVE.targets(email="x@abc.vn")), ["a", "b"])
        self.assertEqual(sorted(LIVE.targets(project="p1")), ["a", "c"])
        self.assertEqual(LIVE.targets(project="p1", keep="a"), ["c"])
        self.assertEqual(LIVE.kick(email="nobody@abc.vn"), 0)

    def test_deleted_page_is_forgotten(self):
        f = Fake("a")
        LIVE.register(f, "x@abc.vn", "p1")
        f.drop()
        self.assertEqual(LIVE.targets(), [])
