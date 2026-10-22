import hashlib
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import aula_sync as A  # noqa: E402


class Naming(unittest.TestCase):
    def test_auto_name(self):
        self.assertEqual(A.auto_name("L1.pdf"), "L1_auto.pdf")
        self.assertEqual(A.auto_name("data.tar.gz"), "data_auto.tar.gz")
        self.assertEqual(A.auto_name("Makefile"), "Makefile_auto")
        self.assertEqual(A.auto_name("a.b.ipynb"), "a.b_auto.ipynb")

    def test_clean_name(self):
        self.assertEqual(A.clean_name('<div class="x">L4 ASR - Lab: Delivery</div>'), "L4 ASR - Lab_ Delivery")
        self.assertEqual(A.clean_name("ASR &amp; TTS"), "ASR & TTS")


class Categories(unittest.TestCase):
    def cases(self):
        return {
            ("L1.pdf", "resource"): "slides",
            ("ASTheory1.pdf", "resource"): "slides",
            ("S02SR.pdf", "resource"): "slides",
            ("RL_emai_26_1.pdf", "resource"): "slides",
            ("SR2026_problem_set02.pdf", "resource"): "exercises",
            ("homeworks_1.pdf", "resource"): "exercises",
            ("programming_project.pdf", "resource"): "exercises",
            ("Msc_Dec24.pdf", "resource"): "exercises",
            ("Mitchell _Krakauer_PNAS2023.pdf", "resource"): "readings",
            ("Building_machines_that_learn_and_think_with_people.pdf", "resource"): "readings",
            ("2.Reglas ortograficas_explicacion.ppsx", "resource"): "slides",
            ("DP_lab.ipynb", "resource"): "code",
            ("channelsV0.lp", "folder"): "code",
            ("imdb-sentiment-2011.arff", "resource"): "code",
            ("anything.pdf", "assign"): "assignments",
            ("poster.png", "label"): "other",
        }

    def test_categorize(self):
        for (fn, mod), want in self.cases().items():
            self.assertEqual(A.categorize(fn, mod), want, fn)

    def test_subfolder_override(self):
        A.DEST = "/D"
        item = dict(module="resource", context="", subdir="")
        self.assertEqual(A.target_path(item, "symbolic_reasoning", {"subfolders": {"slides": "lectures"}}, "S01SR.pdf"),
                         "/D/symbolic_reasoning/lectures/S01SR_auto.pdf")
        item = dict(module="assign", context="", subdir="L4/submission")
        self.assertEqual(A.target_path(item, "nli", {}, "x.ipynb"), "/D/nli/assignments/L4/submission/x_auto.ipynb")


class Dedupe(unittest.TestCase):
    def test_finds_identical_user_file_only(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(f"{d}/lectures")
            open(f"{d}/lectures/L1.pdf", "wb").write(b"hello")
            open(f"{d}/L1_auto.pdf", "wb").write(b"hello")   # our own copy is never a dedupe target
            open(f"{d}/other.pdf", "wb").write(b"world")
            idx = A.CourseIndex(d)
            digest = hashlib.sha256(b"hello").hexdigest()
            self.assertEqual(idx.find_identical(5, digest), f"{d}/lectures/L1.pdf")
            self.assertIsNone(idx.find_identical(5, hashlib.sha256(b"other").hexdigest()))
            self.assertEqual(len(idx.by_size[5]), 2)  # L1.pdf and other.pdf, not L1_auto.pdf


class NoClobber(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        A.DEST = self.d.name
        self.f = os.path.join(self.d.name, "c", "slides", "L3_auto.pdf")
        os.makedirs(os.path.dirname(self.f))
        with open(self.f, "wb") as fh:
            fh.write(b"v1")
        self.rec = {"path": "c/slides/L3_auto.pdf", "sha256": hashlib.sha256(b"v1").hexdigest()}

    def tearDown(self):
        self.d.cleanup()

    def test_free_path_is_used(self):
        free = os.path.join(self.d.name, "c", "slides", "new_auto.pdf")
        self.assertEqual(A.safe_dst(free, None), free)

    def test_own_unmodified_copy_is_replaced(self):
        self.assertEqual(A.safe_dst(self.f, self.rec), self.f)

    def test_user_edited_copy_is_kept(self):
        with open(self.f, "wb") as fh:
            fh.write(b"v1 + iPad annotations")
        self.assertTrue(A.safe_dst(self.f, self.rec).endswith("L3_auto (2).pdf"))

    def test_other_items_file_is_kept(self):  # two Moodle files mapping to the same name
        self.assertTrue(A.safe_dst(self.f, None).endswith("L3_auto (2).pdf"))
        self.assertTrue(A.safe_dst(self.f, {"path": "elsewhere", "sha256": self.rec["sha256"]})
                        .endswith("L3_auto (2).pdf"))


class MailRendering(unittest.TestCase):
    def test_display_name(self):
        self.assertEqual(A.display_name("nli/slides/L3_auto.pdf"), "L3.pdf")
        self.assertEqual(A.display_name("nli/slides/L3_auto (2).pdf"), "L3 (2).pdf")
        self.assertEqual(A.display_name("x/other/Makefile_auto"), "Makefile")

    def test_html_groups_and_escapes(self):
        q = {"NLI <x>": [["new", "nli/slides/L3_auto.pdf", 14_080_400],
                         ["updated", "nli/assignments/L4 ASR/submission/a_auto.ipynb", 609_068]]}
        html = A.changes_html(q, {"courses": {"94487": {"name": "NLI <x>"}}})
        self.assertIn("NLI &lt;x&gt;", html)
        self.assertIn("course/view.php?id=94487", html)
        self.assertIn("Assignment · L4 ASR", html)
        self.assertIn("14.1 MB", html)
        self.assertIn("UPDATED", html)
        self.assertTrue(A.change_subject(q).startswith("📚 2 new files"))


class AtomicPlace(unittest.TestCase):
    def test_place_creates_dirs_and_replaces(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = f"{d}/x.part"
            open(tmp, "w").write("new")
            A.place(tmp, f"{d}/a/b/f_auto.txt")
            self.assertFalse(os.path.exists(tmp))
            self.assertEqual(open(f"{d}/a/b/f_auto.txt").read(), "new")


class HtmlFingerprint(unittest.TestCase):
    PAGE = ('<h1>problem set 1</h1><div id="assign_files_tree{}"><img src="https://x/theme/image.php/boost/core/{}/f/pdf">'
            '<a href="https://x/pluginfile.php/1/problem1.pdf?forcedownload=1">problem1.pdf</a></div>')

    def test_ignores_regenerated_markup(self):
        self.assertEqual(A.html_fingerprint(self.PAGE.format("6ad9f42cddf301", 1)),
                         A.html_fingerprint(self.PAGE.format("7be0a53deef412", 2)))

    def test_sees_real_changes(self):
        self.assertNotEqual(A.html_fingerprint(self.PAGE.format("a", 1)),
                            A.html_fingerprint(self.PAGE.format("a", 1).replace("set 1", "set 2")))


class AssignmentBrief(unittest.TestCase):
    def test_discover_assign_yields_attachments_but_no_brief(self):
        page = ('<div id="region-main"><div class="activity-dates">Due: Friday</div><div id="intro">Do it'
                '<a href="https://aulaglobal.upf.edu/pluginfile.php/1/mod_assign/introattachment/0/p1.pdf?forcedownload=1">'
                'p1.pdf</a></div></div>')
        m = type("M", (), {"get": lambda self, url: type("R", (), {"text": page})()})()
        items = list(A.discover_assign(m, {"id": 7, "url": "https://x/mod/assign/view.php?id=7"}, "PS 1"))
        self.assertEqual([i["filename"] for i in items], ["p1.pdf"])

    def test_drop_assignment_briefs(self):
        with tempfile.TemporaryDirectory() as d:
            old, A.DEST = A.DEST, d
            try:
                os.makedirs(f"{d}/c/assignments/only brief")
                os.makedirs(f"{d}/c/assignments/with files")
                for p in ("c/assignments/only brief/brief_auto.html", "c/assignments/with files/brief_auto (2).html",
                          "c/assignments/with files/p1_auto.pdf", "c/assignments/with files/brief.html"):
                    with open(f"{d}/{p}", "w") as f:
                        f.write("x")
                state = {"files": {
                    "1:cm1:brief": {"path": "c/assignments/only brief/brief_auto.html"},
                    "1:cm2:brief": {"path": "c/assignments/with files/brief_auto (2).html"},
                    "1:cm3:brief": {"path": "c/assignments/with files/brief.html"},  # not ours: kept on disk
                    "1:cm2:p1": {"path": "c/assignments/with files/p1_auto.pdf"}}}
                A.drop_assignment_briefs(state)
                self.assertEqual(list(state["files"]), ["1:cm2:p1"])
                self.assertFalse(os.path.exists(f"{d}/c/assignments/only brief"))  # emptied folder removed
                self.assertEqual(sorted(os.listdir(f"{d}/c/assignments/with files")), ["brief.html", "p1_auto.pdf"])
            finally:
                A.DEST = old

    def test_schedule_hint(self):
        old = A.SYNC_WINDOWS, A.CALENDAR_URL
        try:
            A.SYNC_WINDOWS, A.CALENDAR_URL = [["08:00", "16:00", 30], ["16:00", "20:00", 120]], "https://x/c.ics"
            self.assertEqual(A.schedule_hint(), "syncs 08:00–20:00 and at lecture starts")
            A.CALENDAR_URL = ""
            self.assertEqual(A.schedule_hint(), "syncs 08:00–20:00")
        finally:
            A.SYNC_WINDOWS, A.CALENDAR_URL = old


class Forum(unittest.TestCase):
    @staticmethod
    def row(did, last, title, subscribed=True):
        return (f'<tr class="discussion{" subscribed" if subscribed else ""}" data-discussionid="{did}">'
                f'<th class="topic"><a href="https://x/mod/forum/discuss.php?d={did}">{title}</a></th>'
                f'<td><a href="https://x/mod/forum/discuss.php?d={did}&amp;parent={last}">t</a></td></tr>')

    class FakeMoodle:
        def __init__(self, page):
            self.page = page

        def get(self, url):
            body = self.page if "view.php" in url else '<article id="p9"><header>T by PROF</header>' \
                '<div class="post-content-container">Hello</div></article>'
            return type("R", (), {"text": f'<div id="region-main"><table>{body}</table></div>'})()

    def run_check(self, state, rows):
        item = dict(key="forum1", url="https://x/mod/forum/view.php?id=1", name="Notice board")
        A.check_forum(self.FakeMoodle("".join(rows)), item, {"name": "RL"}, state)
        return state.get("pending_posts", {}).get("mail", [])

    def test_first_look_is_silent_then_only_unsubscribed_posts(self):
        state = {}
        self.assertEqual(self.run_check(state, [self.row(1, 5, "old")]), [])
        rows = [self.row(1, 5, "old"), self.row(2, 7, "emailed by Moodle"), self.row(3, 9, "not emailed", False)]
        posts = self.run_check(state, rows)
        self.assertEqual([p["title"] for p in posts], ["not emailed"])
        self.assertEqual(posts[0]["text"], "Hello")
        self.assertEqual(len(self.run_check(state, rows)), 1)  # nothing new: queue unchanged, no repeat


class Schedule(unittest.TestCase):
    ICS = ("BEGIN:VCALENDAR\r\nX-WR-TIMEZONE:Europe/Madrid\r\n"
           "BEGIN:VEVENT\r\nDTSTART:20261022T113000\r\nSUMMARY:Symbolic reasoning\r\nEND:VEVENT\r\n"
           "BEGIN:VEVENT\r\nDTSTART;VALUE=DATE:20261101\r\nSUMMARY:Holiday\r\nEND:VEVENT\r\n"
           "BEGIN:VEVENT\r\nDTSTART:20261023T080000Z\r\nSUMMARY:x\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")

    def test_lecture_starts(self):
        utc = [t.astimezone(A.dt.timezone.utc).strftime("%d %H:%M") for t in A.lecture_starts(self.ICS)]
        self.assertEqual(utc, ["22 09:30", "23 08:00"])  # Madrid is UTC+2 in October; all-day skipped

    def test_window_slots(self):
        slots = [t.strftime("%H:%M") for t in A.window_slots(A.dt.date(2026, 10, 22),
                                                              [["08:00", "16:00", 30], ["16:00", "20:00", 120]])]
        self.assertEqual(slots[:3], ["08:00", "08:30", "09:00"])
        self.assertEqual(slots[-5:], ["15:00", "15:30", "16:00", "18:00", "20:00"])
        self.assertEqual(len(slots), 19)

    def test_due(self):
        utc = A.dt.timezone.utc
        t = A.dt.datetime(2026, 10, 22, 9, 30, tzinfo=utc)
        m = A.dt.timedelta(minutes=1)
        trig = [(t, "lecture")]
        self.assertEqual(A.due(t, None, []), "first run")
        self.assertIsNone(A.due(t, t - 10 * m, []))
        self.assertTrue(A.due(t + 2 * m, t - 10 * m, trig).startswith("lecture"))
        self.assertIsNone(A.due(t + 2 * m, t + m, trig))  # already synced after that slot
        self.assertIsNone(A.due(t + 600 * m, t + m, trig))  # no slot since: night stays quiet


if __name__ == "__main__":
    unittest.main()
