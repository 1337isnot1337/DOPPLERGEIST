"""Publication-policy checks; no audio, trajectories or image builds."""
import importlib.util
from pathlib import Path
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "scripts/container_publish_metadata.py"
SPEC = importlib.util.spec_from_file_location("container_publish_metadata", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
REVISION = "dcd8cb73114af0a20be869e9e8c3295080b65ab8"


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


if __name__ == "__main__":
    unittest.main()
