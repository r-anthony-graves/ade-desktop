"""Add a project from requirements: the web's AddProjectPanel flow, step
for step, as a state machine driven by the clients' `done` signals.

    upload (or the pasted text, written to a temp file and uploaded)
    -> POST /v1/pm/intake          records row + 16 PMI skeletons, instant
    -> POST /v1/pm/author  x N     the PM docs, one at a time
    -> verify on disk              `Fill status: filled` per doc
    -> POST /v1/pm/author  x 13    the QA package
    -> verify on disk              files under qa/<slug>/

A document that fails does not stop its package: the rest still get their
turn and the failed ones are named. A package whose every call said ok but
whose disk still says skeleton is graded STALE with a Re-run offered --
the mission layer once answered ok:true having written nothing
(2026-08-11). Stop ends the loop after the document in flight; that one
cannot be recalled, and the status says so.
"""

from __future__ import annotations

import os
import shutil
import tempfile

from PySide6.QtCore import QObject, Signal

from ade_desktop.conversation.replies import error_cause, failed
from ade_desktop.sections.pm import model
from ade_desktop.workspace.files import is_missing
from ade_desktop.workspace.filling import filling


class AddProjectFlow(QObject):
    status = Signal(str)                    # the one-line status
    failed = Signal(str)                    # the flow stopped: why
    created = Signal(str)                   # the project's name, after intake
    package = Signal(str, str, str)         # pkg ("pm"/"qa"), kind, note
    progress = Signal(str, int, int, str)   # pkg, done, total, current doc
    busy_changed = Signal(bool)

    def __init__(self, pm, files, *, tmpdir=None, parent=None) -> None:
        super().__init__(parent)
        self.pm, self.files = pm, files
        self._tmpdir = tmpdir            # None: a private folder per run (mkdtemp)
        self._pending: dict[str, tuple] = {}
        self.intake: dict | None = None
        self.source = ""
        self.notes = ""
        self.busy = False
        self._stop = False
        self._run: dict | None = None       # the package being authored
        self._chain = False                 # QA follows PM (the web runs both)
        self._pasted_dir: str | None = None
        self.package_dir: str | None = None   # the folder Ade is writing into, while it does
        pm.done.connect(self._on_done)
        files.done.connect(self._on_done)

    # -- starting ---------------------------------------------------------------

    def start(self, name: str, file_path: str | None, pasted: str, notes: str) -> bool:
        """The whole flow: a NEW project, its PMI package, then its QA package."""
        return self._begin("project", name, file_path, pasted, notes)

    def start_qa(self, name: str, file_path: str | None, pasted: str, notes: str) -> bool:
        """The QA package alone, for an EXISTING project, into
        qa/<slug(project)>/ -- where the QA desk reads. (The web's QA panel
        wrote to the slug of the uploaded FILE, which the desk never opens.)
        /v1/pm/author needs no skeleton for package qa: it makes the folder
        and its README itself."""
        return self._begin("qa", name, file_path, pasted, notes)

    def _begin(self, mode: str, name: str, file_path, pasted: str, notes: str) -> bool:
        name = (name or "").strip()
        if self.busy:
            return False
        if not name:
            self.failed.emit("Project name is required.")
            return False
        if not file_path and not (pasted or "").strip():
            self.failed.emit("Choose a file or paste requirements text.")
            return False
        self.intake, self.notes, self._stop = None, notes or "", False
        if not file_path:
            # A private folder per run: a fixed name in %TEMP% would overwrite,
            # then delete, any file that happened to share it (review).
            try:
                self._pasted_dir = tempfile.mkdtemp(prefix="ade-desktop-req-",
                                                    dir=self._tmpdir)
                file_path = os.path.join(self._pasted_dir,
                                         f"{model.slug(name)}-requirements.md")
                with open(file_path, "w", encoding="utf-8", newline="\n") as handle:
                    handle.write(pasted)
            except OSError as exc:
                self._cleanup()
                self.failed.emit(f"Could not stage the pasted text for upload: {exc}")
                return False
        self._set_busy(True)
        self.status.emit("Uploading requirements…")
        self._pending[self.files.upload(file_path)] = ("upload", name, mode)
        return True

    def stop(self) -> None:
        """Honoured at every step: during the upload or the intake the flow
        ends when that call answers (review: Stop used to be ignored until
        authoring began, and all ~28 documents then ran)."""
        if not self.busy:
            return
        self._stop = True
        if self._run is not None:
            self.status.emit("Stopping after the document in flight — Ade OS "
                             "finishes that one; it cannot be recalled.")
        else:
            self.status.emit("Stopping when Ade OS answers the call in flight…")

    def rerun(self, pkg: str) -> bool:
        if self.busy or self.intake is None:
            return False
        self._stop, self._chain = False, False
        self._set_busy(True)
        self._author(pkg)
        return True

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.busy_changed.emit(busy)

    def _cleanup(self) -> None:
        if self._pasted_dir:
            shutil.rmtree(self._pasted_dir, ignore_errors=True)
            self._pasted_dir = None

    def close(self) -> None:
        """At quit, or when the panel goes: nothing more is started, the
        staged file goes, and the folder is no longer marked as written."""
        self._stop = True
        self._set_package_dir(None)
        self._cleanup()

    def _set_package_dir(self, folder: str | None) -> None:
        """Marked app-wide while Ade writes it, so no editor anywhere saves
        a document in it meanwhile."""
        if self.package_dir:
            filling().clear(self.package_dir)
        self.package_dir = folder
        if folder:
            filling().mark(folder)

    def _finish(self) -> None:
        self._run = None
        self._set_package_dir(None)
        self._cleanup()
        self._set_busy(False)

    # -- the steps ----------------------------------------------------------------

    def _author(self, pkg: str) -> None:
        intake = self.intake
        docs = (model.pm_docs(intake.get("artifacts") or []) if pkg == "pm"
                else list(model.QA_DOCS))
        self._run = {"pkg": pkg, "docs": docs, "i": 0, "failures": []}
        self._set_package_dir(intake["dir"] if pkg == "pm" else intake["qa_dir"])
        self.package.emit(pkg, "running", "")
        self._next_doc()

    def _next_doc(self) -> None:
        run, intake = self._run, self.intake
        docs, i = run["docs"], run["i"]
        if i >= len(docs) or (self._stop and i > 0):
            self._package_done()
            return
        self.progress.emit(run["pkg"], i, len(docs), docs[i])
        rid = self.pm.author(run["pkg"], intake["slug"], docs[i], self.source,
                             intake["project"]["name"], self.notes)
        self._pending[rid] = ("author", docs[i])

    def _package_done(self) -> None:
        run = self._run
        pkg, docs, failures = run["pkg"], run["docs"], run["failures"]
        done = run["i"]
        if self._stop and done < len(docs):
            self.package.emit(pkg, "error", f"stopped after {done}/{len(docs)}; "
                              f"not authored: {', '.join(docs[done:])}")
            self._stopped(pkg)
            return
        if failures:
            self.package.emit(pkg, "error", f"{len(docs) - len(failures)}/{len(docs)} "
                              f"authored; failed: {', '.join(d for d, _ in failures)}")
            self._after_package(pkg)
            return
        self._verify(pkg)

    def _verify(self, pkg: str) -> None:
        intake = self.intake
        if pkg == "pm":
            paths = model.pm_paths(intake.get("artifacts") or [])
            self._run.update(verify=paths, filled=0, checked=0)
            if not paths:
                self._verified_pm()
                return
            for path in paths:
                self._pending[self.files.read(path)] = ("verify_pm", path)
        else:
            self._pending[self.files.list_dir(intake["qa_dir"])] = ("verify_qa",)

    def _verified_pm(self) -> None:
        run = self._run
        kind, note = model.grade_pm(run["filled"], len(run["verify"]))
        self.package.emit("pm", kind, note)
        self._after_package("pm")

    def _after_package(self, pkg: str) -> None:
        """QA follows PM whatever PM's grade, as the web's run() does;
        a Re-run repeats one package only."""
        if self._stop:
            self._stopped(pkg)
            return
        if pkg == "pm" and self._chain:
            self._chain = False
            self._author("qa")
            return
        self._chain = False
        self.status.emit("Done — the counts are below; the artifacts are editable now.")
        self._finish()

    def _stopped(self, pkg: str | None) -> None:
        """A Stop that cut the chain says so for the package it never
        reached, so that package still gets a Re-run (review: after a Stop
        near the end of PM, QA could never be run from the panel)."""
        if pkg == "pm" and self._chain:
            self.package.emit("qa", "error", "not started — Stop was pressed")
        self._chain = False
        self.status.emit("Stopped.")
        self._finish()

    # -- results ------------------------------------------------------------------

    def _on_done(self, rid: str, result) -> None:
        job = self._pending.pop(rid, None)
        if job is None:
            return
        ok = not failed(result)
        kind = job[0]
        if kind == "upload":
            if not ok or not result.get("name"):
                self._fail(f"Upload failed: {error_cause(result)}")
                return
            self.source = result["name"]
            if self._stop:
                self.status.emit("")
                self.failed.emit(f"Stopped. Nothing was created; the upload stays at "
                                 f"{self.source}.")
                self._finish()
                return
            if job[2] == "qa":
                slug = model.slug(job[1])
                self.intake = {"project": {"name": job[1]}, "slug": slug, "artifacts": [],
                               "dir": f"pm/{slug}", "qa_dir": f"qa/{slug}"}
                self.status.emit(f"Authoring the QA package under qa/{slug}/…")
                self._chain = False
                self._author("qa")
                return
            self.status.emit("Creating the project and its PMI skeleton package…")
            self._pending[self.pm.intake(job[1], self.source)] = ("intake",)
        elif kind == "intake":
            if not ok:
                self._fail(f"Could not create the project: {error_cause(result)}")
                return
            self.intake = result
            self.created.emit(result["project"]["name"])
            if self._stop:
                self.package.emit("pm", "error", "not started — Stop was pressed")
                self.package.emit("qa", "error", "not started — Stop was pressed")
                self.status.emit(f"Stopped. The project and its skeletons exist under "
                                 f"{result['dir']}/; nothing was authored.")
                self._finish()
                return
            self.status.emit(f"Skeletons ready under {result['dir']}/ — authoring documents…")
            self._chain = True
            self._author("pm")
        elif kind == "author":
            run = self._run
            if run is None:
                return
            if not ok:
                run["failures"].append((job[1], error_cause(result)))
            run["i"] += 1
            self._next_doc()
        elif kind == "verify_pm":
            run = self._run
            if run is None:
                return
            run["checked"] += 1
            if ok and not result.get("cached") and model.is_filled(result.get("text", "")):
                run["filled"] += 1
            if run["checked"] == len(run["verify"]):
                self._verified_pm()
        elif kind == "verify_qa":
            if not ok and not is_missing(result):
                self.package.emit("qa", "error", f"QA disk check failed: {error_cause(result)}")
            else:
                # The 13 documents only: author_doc writes README.md itself,
                # so counting it graded one file on disk as a whole package.
                names = {e.get("name") for e in (result.get("entries") or [])
                         if e.get("kind") == "file"} if ok else set()
                qa_kind, note = model.grade_qa(len(names & set(model.QA_DOCS)),
                                               len(model.QA_DOCS), self.intake["qa_dir"])
                self.package.emit("qa", qa_kind, note)
            self._after_package("qa")

    def _fail(self, message: str) -> None:
        self.status.emit("")
        self.failed.emit(message)
        self._finish()
