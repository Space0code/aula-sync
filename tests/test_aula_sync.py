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


class AtomicPlace(unittest.TestCase):
    def test_place_creates_dirs_and_replaces(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = f"{d}/x.part"
            open(tmp, "w").write("new")
            A.place(tmp, f"{d}/a/b/f_auto.txt")
            self.assertFalse(os.path.exists(tmp))
            self.assertEqual(open(f"{d}/a/b/f_auto.txt").read(), "new")


if __name__ == "__main__":
    unittest.main()
