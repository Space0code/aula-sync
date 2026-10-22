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


class Schedule(unittest.TestCase):
    ICS = ("BEGIN:VCALENDAR\r\nX-WR-TIMEZONE:Europe/Madrid\r\n"
           "BEGIN:VEVENT\r\nDTSTART:20261022T113000\r\nSUMMARY:Symbolic reasoning\r\nEND:VEVENT\r\n"
           "BEGIN:VEVENT\r\nDTSTART;VALUE=DATE:20261101\r\nSUMMARY:Holiday\r\nEND:VEVENT\r\n"
           "BEGIN:VEVENT\r\nDTSTART:20261023T080000Z\r\nSUMMARY:x\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")

    def test_lecture_starts(self):
        utc = [t.astimezone(A.dt.timezone.utc).strftime("%d %H:%M") for t in A.lecture_starts(self.ICS)]
        self.assertEqual(utc, ["22 09:30", "23 08:00"])  # Madrid is UTC+2 in October; all-day skipped

    def test_due(self):
        utc = A.dt.timezone.utc
        t = A.dt.datetime(2026, 10, 22, 9, 30, tzinfo=utc)
        m = A.dt.timedelta(minutes=1)
        self.assertEqual(A.due(t, None, []), "interval")
        self.assertIsNone(A.due(t, t - 10 * m, []))
        self.assertEqual(A.due(t, t - 30 * m, []), "interval")
        self.assertTrue(A.due(t + 2 * m, t - 10 * m, [t]).startswith("lecture"))
        self.assertIsNone(A.due(t + 2 * m, t + m, [t]))  # already synced after that lecture start


if __name__ == "__main__":
    unittest.main()
