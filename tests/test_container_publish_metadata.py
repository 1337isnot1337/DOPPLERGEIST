"""Publication-policy checks; no audio, trajectories or image builds."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest
from unittest import mock


SOURCE = Path(__file__).resolve().parents[1] / "scripts/container_publish_metadata.py"
SPEC = importlib.util.spec_from_file_location("container_publish_metadata", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
REVISION = "dcd8cb73114af0a20be869e9e8c3295080b65ab8"
WORKFLOW = SOURCE.parents[1] / ".github/workflows/docker.yml"
# Exercise the actual publishing step, with registry/ref commands replaced by
# software controls. These checks neither build nor publish a container.
PUBLISH_STEP = WORKFLOW.read_text().split("      - name: Publish the validated image\n", 1)[1]
PUBLISH_SCRIPT = compile(textwrap.dedent(
    PUBLISH_STEP.split("          python - <<'PY'\n", 1)[1].split("          PY\n", 1)[0]),
    str(WORKFLOW), "exec")


class ContainerPublishMetadataTests(unittest.TestCase):
    def metadata(self, event, ref, repository=MODULE.REPOSITORY):
        return MODULE.metadata(repository, event, ref, REVISION)

    def test_main_push_and_dispatch_have_full_revision_and_main_tags(self):
        for event in ("push", "workflow_dispatch"):
            with self.subTest(event=event):
                result = self.metadata(event, "refs/heads/main")
                self.assertTrue(result["publish"])
                self.assertEqual(result["image"], "ghcr.io/1337isnot1337/dopplergeist")
                self.assertEqual(result["revision"], REVISION)
                self.assertEqual(result["tags"], [result["image"] + ":sha-" + REVISION,
                                                   result["image"] + ":main"])

    def test_release_and_prerelease_keep_the_exact_version(self):
        for version in ("v0.1.0", "v1.2.3", "v2.0.0-rc.1"):
            with self.subTest(version=version):
                result = self.metadata("push", "refs/tags/" + version)
                self.assertTrue(result["publish"])
                self.assertEqual(result["version"], version)
                self.assertEqual(result["tags"][-1], result["image"] + ":" + version)
                self.assertFalse(any(tag.endswith((":latest", ":main")) for tag in result["tags"]))

    def test_pull_requests_forks_and_other_events_cannot_publish(self):
        for event in ("pull_request", "pull_request_target", "workflow_run", "schedule"):
            for ref in ("refs/heads/main", "refs/tags/v1.2.3", "refs/pull/340/merge"):
                with self.subTest(event=event, ref=ref):
                    result = self.metadata(event, ref)
                    self.assertFalse(result["publish"])
                    self.assertEqual(result["tags"], [])
        for event in ("push", "workflow_dispatch"):
            with self.subTest(fork_event=event):
                result = self.metadata(event, "refs/heads/main", "a-fork/DOPPLERGEIST")
                self.assertFalse(result["publish"])
                self.assertEqual(result["tags"], [])

    def test_dispatch_on_other_refs_does_not_publish(self):
        for ref in ("refs/heads/topic", "refs/tags/v1.2.3", "refs/pull/340/head"):
            with self.subTest(ref=ref):
                self.assertFalse(self.metadata("workflow_dispatch", ref)["publish"])

    def test_malformed_or_unsupported_version_tags_do_not_publish(self):
        for version in ("vnext", "v1.2", "v01.2.3", "v1.2.3-01", "v1.2.3+build",
                        "v1.2.3-rc..1", "v1.2.3/extra", "v1.2.3-" + "a" * 128):
            with self.subTest(version=version):
                result = self.metadata("push", "refs/tags/" + version)
                self.assertFalse(result["publish"])
                self.assertEqual(result["tags"], [])

    def test_revision_cannot_be_abbreviated_or_contain_shell_text(self):
        for revision in (REVISION[:7], "$(whoami)", REVISION + "\nextra"):
            with self.subTest(revision=revision), self.assertRaises(ValueError):
                MODULE.metadata(MODULE.REPOSITORY, "push", "refs/heads/main", revision)


class ContainerPublishCurrentMainTests(unittest.TestCase):
    image = "ghcr.io/1337isnot1337/dopplergeist"
    sha_tag = image + ":sha-" + REVISION
    main_tag = image + ":main"
    digest = image + "@sha256:" + "a" * 64

    def run_publication(self, remote, tags=None):
        calls = []

        def run(arguments, **kwargs):
            calls.append(arguments)
            if arguments[0] == "git":
                self.assertEqual(arguments, ["git", "ls-remote", "--exit-code",
                    "https://github.com/1337isnot1337/DOPPLERGEIST.git", "refs/heads/main"])
                self.assertEqual(kwargs, {"check": True, "capture_output": True,
                                          "text": True, "timeout": 30})
                if isinstance(remote, Exception):
                    raise remote
                return subprocess.CompletedProcess(arguments, 0, stdout=remote)
            if arguments[:3] == ["docker", "image", "inspect"]:
                return subprocess.CompletedProcess(arguments, 0, stdout=json.dumps([self.digest]))
            self.assertIn(arguments[:2], (["docker", "tag"], ["docker", "push"]))
            return subprocess.CompletedProcess(arguments, 0)

        with tempfile.TemporaryDirectory() as directory:
            summary = Path(directory) / "summary.md"
            environment = {"IMAGE_TAGS": json.dumps(tags or [self.sha_tag, self.main_tag]),
                           "IMAGE_REVISION": REVISION, "GITHUB_STEP_SUMMARY": str(summary)}
            with mock.patch.dict(os.environ, environment), mock.patch.object(subprocess, "run", run):
                failure = None
                try:
                    exec(PUBLISH_SCRIPT, {})
                except RuntimeError as error:
                    failure = error
            return calls, failure, summary.read_text()

    def test_current_main_pushes_both_tags_with_last_moment_ref_check(self):
        calls, failure, summary = self.run_publication(REVISION + "\trefs/heads/main\n")
        self.assertIsNone(failure)
        pushes = [call[-1] for call in calls if call[:2] == ["docker", "push"]]
        self.assertEqual(pushes, [self.sha_tag, self.main_tag])
        main_push = calls.index(["docker", "push", self.main_tag])
        self.assertEqual(calls[main_push - 1][0], "git")
        self.assertIn(self.digest, summary)

    def test_stale_main_keeps_sha_and_records_skipped_mutable_tag(self):
        current = "6eca37d6208d5006551ae7be7b62053e7ace2dd6"
        calls, failure, summary = self.run_publication(current + "\trefs/heads/main\n")
        self.assertIsNone(failure)
        self.assertEqual([call[-1] for call in calls if call[:2] == ["docker", "push"]],
                         [self.sha_tag])
        self.assertIn("Skipped `" + self.main_tag + "`", summary)
        self.assertIn(current, summary)
        self.assertIn(REVISION, summary)

    def test_unreadable_main_fails_after_sha_without_pushing_main(self):
        for remote in ("", REVISION + "\trefs/heads/other\n", "invalid\trefs/heads/main\n",
                       subprocess.CalledProcessError(128, ["git", "ls-remote"]),
                       subprocess.TimeoutExpired(["git", "ls-remote"], 30)):
            with self.subTest(remote=remote):
                calls, failure, summary = self.run_publication(remote)
                self.assertIsInstance(failure, RuntimeError)
                self.assertEqual([call[-1] for call in calls if call[:2] == ["docker", "push"]],
                                 [self.sha_tag])
                self.assertIn("current public main could not be verified", summary)

    def test_release_publication_does_not_depend_on_main(self):
        tags = [self.sha_tag, self.image + ":v1.2.3"]
        calls, failure, summary = self.run_publication("", tags=tags)
        self.assertIsNone(failure)
        self.assertFalse(any(call[0] == "git" for call in calls))
        self.assertEqual([call[-1] for call in calls if call[:2] == ["docker", "push"]], tags)


if __name__ == "__main__":
    unittest.main()
