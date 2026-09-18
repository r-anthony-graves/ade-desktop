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
import tempfile

from PySide6.QtCore import QObject, Signal

from ade_desktop.conversation.replies import error_cause
from ade_desktop.sections.pm import model


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
        self._tmpdir = tmpdir or tempfile.gettempdir()
        self._pending: dict[str, tuple] = {}
        self.intake: dict | None = None
        self.source = ""
        self.notes = ""
        self.busy = False
        self._stop = False
        self._run: dict | None = None       # the package being authored
        self._chain = False                 # QA follows PM (the web runs both)
        self._pasted: str | None = None
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
        self._set_busy(True)
        if not file_path:
            file_path = os.path.join(self._tmpdir, f"{model.slug(name)}-requirements.md")
            with open(file_path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(pasted)
            self._pasted = file_path
        self.status.emit("Uploading requirements…")
        self._pending[self.files.upload(file_path)] = ("upload", name, mode)
        return True

    def stop(self) -> None:
        if self._run is not None:
            self._stop = True
            self.status.emit("Stopping after the document in flight — Ade OS "
                             "finishes that one; it cannot be recalled.")

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

    def _finish(self) -> None:
        self._run = None
        if self._pasted:
            try:
                os.remove(self._pasted)
            except OSError:
                pass
            self._pasted = None
        self._set_busy(False)

    # -- the steps ----------------------------------------------------------------

    def _author(self, pkg: str) -> None:
        intake = self.intake
        docs = (model.pm_docs(intake.get("artifacts") or []) if pkg == "pm"
                else list(model.QA_DOCS))
        self._run = {"pkg": pkg, "docs": docs, "i": 0, "failures": []}
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
            self.status.emit("Stopped.")
            self._finish()
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
        if pkg == "pm" and self._chain and not self._stop:
            self._chain = False
            self._author("qa")
            return
        self._chain = False
        self.status.emit("Done — the counts are below; the artifacts are editable now.")
        self._finish()

    # -- results ------------------------------------------------------------------

    def _on_done(self, rid: str, result) -> None:
        job = self._pending.pop(rid, None)
        if job is None:
            return
        ok = isinstance(result, dict) and "error" not in result
        kind = job[0]
        if kind == "upload":
            if not ok or not result.get("name"):
                self._fail(f"Upload failed: {error_cause(result)}")
                return
            self.source = result["name"]
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
            if not ok:
                self.package.emit("qa", "error", f"QA disk check failed: {error_cause(result)}")
            else:
                files = [e for e in result.get("entries") or [] if e.get("kind") == "file"]
                qa_kind, note = model.grade_qa(len(files), len(model.QA_DOCS),
                                               self.intake["qa_dir"])
                self.package.emit("qa", qa_kind, note)
            self._after_package("qa")

    def _fail(self, message: str) -> None:
        self.status.emit("")
        self.failed.emit(message)
        self._finish()
