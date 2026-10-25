"""Local integration tests: real catalog/PNGs; the external API is mocked only."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import Image

import frankenstein
import logic
import parts_classification as classifier

ROOT = Path(__file__).resolve().parents[1]


def fixture(name="bear_peacock.json"):
    return json.loads((ROOT / "examples" / name).read_text(encoding="utf-8"))


def request_for(animal="dog", **extras):
    return {"parts": [{"slot": "torso", "animal": animal},
                      {"slot": "back_legs", "animal": animal, "count": 2}]
            + [{"slot": slot, **value} for slot, value in extras.items()]}


class MappingTests(unittest.TestCase):
    def test_real_filenames_and_front_rear_sockets(self):
        plan = logic.plan_creature(fixture(), strict=True)
        self.assertEqual(plan.leg_socket_indices, [0, 2, 1, 3])
        self.assertIn("peacock_tail.png", plan.filenames)
        self.assertEqual([n for n in plan.filenames if "_leg_" in n], [
            "bear_leg_front_near.png", "bear_leg_front_far.png",
            "bear_leg_rear_near.png", "bear_leg_rear_far.png"])
        for filename in plan.filenames:
            self.assertTrue(frankenstein.part_path(Path(filename).stem).is_file())

    def test_rear_legs_use_rear_sockets(self):
        plan = logic.plan_creature(request_for())
        self.assertEqual(plan.leg_socket_indices, [1, 3])
        self.assertIn("dog_leg_rear_near.png", plan.filenames)
        self.assertIn("dog_leg_rear_far.png", plan.filenames)

    def test_explicit_head_donor_is_preserved(self):
        plan = logic.plan_creature(request_for(head={"animal": "lion"}))
        self.assertIn("dog_torso.png", plan.filenames)
        self.assertIn("lion_head.png", plan.filenames)
        self.assertNotIn("dog_head.png", plan.filenames)

    def test_legacy_request_gets_a_head(self):
        self.assertIn("dog_head.png", logic.plan_creature(request_for()).filenames)

    def test_peacock_biped_uses_left_and_right_legs(self):
        plan = logic.plan_creature(request_for("peacock"))
        self.assertEqual(plan.leg_socket_indices, [0, 1])
        self.assertIn("peacock_leg_left.png", plan.filenames)
        self.assertIn("peacock_leg_right.png", plan.filenames)

    def test_missing_lizard_rear_far_reuses_a_real_rear_leg(self):
        plan = logic.plan_creature(request_for("lizard"))
        self.assertEqual(plan.filenames.count("lizard_leg_rear_near.png"), 2)

    def test_narwhal_legs_fall_back_without_inventing_filenames(self):
        plan = logic.plan_creature(request_for("narwhal"))
        self.assertEqual(len(plan.leg_socket_indices), 2)
        self.assertTrue(any("narwhal back_legs" in w for w in plan.warnings))
        self.assertFalse(any(n.startswith("narwhal_leg_") for n in plan.filenames))

    def test_fallback_never_adds_a_fourth_animal(self):
        data = request_for(head={"animal": "bear"}, tail={"animal": "monkey"},
                           horn={"animal": "dog"})
        plan = logic.plan_creature(data)
        self.assertFalse(any("horn" in n or "crest" in n for n in plan.filenames))
        self.assertTrue(any("3-animal limit" in w for w in plan.warnings))
        self.assertLessEqual(len({n.split("_")[0] for n in plan.filenames}), 3)

    def test_impossible_counts_are_reported_or_rejected(self):
        data = request_for(eyes={"animal": "dog", "count": 8},
                           tail={"animal": "dog", "count": 2})
        plan = logic.plan_creature(data)
        self.assertEqual(plan.filenames.count("dog_eye.png"), 4)
        self.assertEqual(plan.filenames.count("dog_tail.png"), 1)
        self.assertEqual(len(plan.warnings), 2)
        with self.assertRaisesRegex(ValueError, "Cannot exactly satisfy"):
            logic.plan_creature(data, strict=True)

    def test_embedded_ears_and_unsupported_swaps(self):
        self.assertFalse(logic.plan_creature(request_for(ears={"animal": "dog"})).warnings)
        plan = logic.plan_creature(request_for(ears={"animal": "elephant"}))
        self.assertTrue(any("No separate ear PNGs" in w for w in plan.warnings))

    def test_unavailable_required_traits_are_reported(self):
        plan = logic.plan_creature(request_for(eyes={"animal": "dog", "must": ["aquatic"]}))
        self.assertTrue(any("required traits: aquatic" in w for w in plan.warnings))

    def test_original_three_animal_and_two_leg_rules_are_validated(self):
        with self.assertRaisesRegex(ValueError, "at most 3"):
            logic.plan_creature(request_for(head={"animal": "bear"},
                                            tail={"animal": "monkey"},
                                            eyes={"animal": "fish"}))
        with self.assertRaisesRegex(ValueError, "at least 2 legs"):
            logic.plan_creature({"parts": [{"slot": "torso", "animal": "dog"}]})

    def test_truncated_arms_cannot_displace_the_minimum_legs(self):
        data = request_for("peacock", front_legs={"animal": "monkey", "variant": "arms", "count": 8})
        with self.assertRaisesRegex(ValueError, "cannot supply the required 2 legs"):
            logic.plan_creature(data)

    def test_fish_legs_are_not_allowed_on_other_torsos(self):
        data = request_for()
        data["parts"][1]["animal"] = "fish"
        with self.assertRaisesRegex(ValueError, "fish legs"):
            logic.plan_creature(data)

    def test_empty_prompt_does_not_contact_classifier(self):
        with patch.object(classifier, "classify") as classify:
            with self.assertRaisesRegex(ValueError, "non-empty"):
                logic.generate_creature("   ")
            classify.assert_not_called()

    def test_dry_run_does_not_render_or_write(self):
        with patch.object(frankenstein, "create_creature") as render:
            result = logic.generate_creature(request=fixture(), dry_run=True)
            render.assert_not_called()
            self.assertIsNone(result.image_path)
            self.assertIsNone(result.metadata_path)

    def test_invalid_request_does_not_render(self):
        with patch.object(frankenstein, "create_creature") as render:
            with self.assertRaises(ValueError):
                logic.generate_creature(request={"parts": []})
            render.assert_not_called()

    def test_missing_api_key_has_actionable_message(self):
        with patch.dict(os.environ, {}, clear=True), patch("dotenv.load_dotenv"):
            with self.assertRaisesRegex(ValueError, "GEMINI_API_KEY"):
                classifier.get_client()

    def test_old_provider_key_cannot_enable_gemini(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "unused-old-provider-key"}, clear=True), patch("dotenv.load_dotenv"):
            with self.assertRaisesRegex(ValueError, "GEMINI_API_KEY"):
                classifier.get_client()
            self.assertFalse(logic.check_setup()["api_key_configured"])

    def test_google_key_precedence_and_developer_client(self):
        from google import genai
        cases = [({"GEMINI_API_KEY": "gemini-test-key"}, "gemini-test-key"),
                 ({"GEMINI_API_KEY": "gemini-test-key", "GOOGLE_API_KEY": "google-test-key"}, "google-test-key")]
        for environment, expected_key in cases:
            with self.subTest(environment=list(environment)), patch.dict(os.environ, environment, clear=True), patch("dotenv.load_dotenv"), patch.object(genai, "Client") as constructor:
                classifier.get_client()
                self.assertEqual(constructor.call_args.kwargs["api_key"], expected_key)
                self.assertFalse(constructor.call_args.kwargs["vertexai"])

    def test_check_reports_a_missing_google_dependency(self):
        def find_spec(name):
            if name == "google.genai":
                raise ModuleNotFoundError("No module named google")
            return object()
        with patch("importlib.util.find_spec", side_effect=find_spec), patch("dotenv.load_dotenv"):
            status = logic.check_setup()
        self.assertFalse(status["dependencies"]["google.genai"])
        self.assertFalse(status["prompt_ready"])
        self.assertTrue(status["offline_ready"])

    def test_api_errors_are_sanitized_and_do_not_render(self):
        client = Mock()
        client.interactions.create.side_effect = RuntimeError("secret-placeholder")
        with patch.object(classifier, "get_client", return_value=client), patch.object(frankenstein, "create_creature") as render:
            with self.assertRaises(RuntimeError) as error:
                logic.generate_creature("A bear with a peacock tail")
            self.assertNotIn("secret-placeholder", str(error.exception))
            render.assert_not_called()
            client.close.assert_called_once()

    def test_empty_gemini_response_does_not_render(self):
        client = Mock()
        client.interactions.create.return_value = SimpleNamespace(status="completed", output_text="")
        with patch.object(classifier, "get_client", return_value=client), patch.object(frankenstein, "create_creature") as render:
            with self.assertRaisesRegex(RuntimeError, "no classification text"):
                logic.generate_creature("A bear with a peacock tail")
            render.assert_not_called()

    def test_invalid_gemini_classification_does_not_render(self):
        client = Mock()
        client.interactions.create.return_value = SimpleNamespace(status="completed", output_text='{"parts": []}')
        with patch.object(classifier, "get_client", return_value=client), patch.object(frankenstein, "create_creature") as render:
            with self.assertRaisesRegex(RuntimeError, "schema or creature constraints"):
                logic.generate_creature("A bear with a peacock tail")
            render.assert_not_called()

    def test_real_google_sdk_request_and_json_response_without_network(self):
        import httpx
        from google import genai
        captured = []
        def handler(request):
            captured.append((request, json.loads(request.content)))
            return httpx.Response(200, json={
                "id": "offline-sdk-check", "object": "interaction", "status": "completed",
                "steps": [{"type": "model_output", "content": [
                    {"type": "text", "text": json.dumps(fixture())}
                ]}],
            })
        with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as http_client:
            client = genai.Client(api_key="offline-sdk-test", vertexai=False,
                                  http_options={"httpx_client": http_client})
            with patch.object(classifier, "get_client", return_value=client), patch.dict(os.environ, {"GEMINI_MODEL": "gemini-3.8-flash"}):
                request = classifier.classify("A bear with a peacock tail")
        self.assertEqual(request.parts[0].animal.value, "bear")
        self.assertEqual(len(captured), 1)
        http_request, body = captured[0]
        self.assertTrue(http_request.url.path.endswith("/interactions"))
        self.assertEqual(http_request.headers["x-goog-api-key"], "offline-sdk-test")
        self.assertEqual(body["model"], "gemini-3.8-flash")
        self.assertEqual(body["response_format"]["schema"], classifier.MonsterRequest.model_json_schema())
        self.assertIn("A bear with a peacock tail", body["input"])
        self.assertFalse(body["store"])
        self.assertNotIn("temperature", body)

    def test_cli_and_import_work_from_another_folder_without_a_key(self):
        env = {k: v for k, v in os.environ.items() if k not in {"GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY", "OPEN_AI"}}
        with tempfile.TemporaryDirectory() as directory:
            completed = subprocess.run([
                sys.executable, str(ROOT / "logic.py"), "--request-json",
                str(ROOT / "examples" / "bear_peacock.json"), "--dry-run"
            ], cwd=directory, env=env, text=True, capture_output=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("peacock_tail.png", json.loads(completed.stdout)["filenames"])


class RenderingTests(unittest.TestCase):
    def test_bear_tail_is_actually_attached(self):
        plan = logic.plan_creature(fixture())
        image, attached = frankenstein.build(plan.filenames, leg_socket_indices=plan.leg_socket_indices)
        self.assertIn("peacock_tail", attached)
        self.assertEqual(image.size, (1000, 1000))
        self.assertIsNotNone(image.getbbox())

    def test_renderer_can_skip_white_outlines(self):
        plan = logic.plan_creature(fixture())
        with patch.object(frankenstein, "add_outline", side_effect=AssertionError("outline should be skipped")):
            image, _ = frankenstein.build(
                plan.filenames,
                leg_socket_indices=plan.leg_socket_indices,
                outline=False,
            )
        self.assertEqual(image.size, (1000, 1000))
        self.assertIsNotNone(image.getbbox())

    def test_repeated_eyes_horns_and_wings_are_all_attached(self):
        plan = logic.plan_creature(fixture("three_animal_monster.json"), strict=True)
        image, attached = frankenstein.build(plan.filenames,
                                             leg_socket_indices=plan.leg_socket_indices, pose=plan.pose)
        self.assertEqual(attached.count("lion_eye"), 4)
        self.assertEqual(attached.count("narwhal_horn"), 2)
        self.assertEqual(attached.count("peacock_wing"), 2)
        self.assertEqual(image.mode, "RGBA")

    def test_full_prompt_pipeline_saves_image_and_auditable_json(self):
        client = Mock()
        client.interactions.create.return_value = SimpleNamespace(status="completed", output_text=json.dumps(fixture()))
        with tempfile.TemporaryDirectory() as directory, patch.object(classifier, "get_client", return_value=client):
            output = Path(directory) / "nested" / "creature.png"
            result = logic.generate_creature("A bear with a peacock tail", output)
            with Image.open(output) as image:
                self.assertEqual(image.format, "PNG")
                self.assertEqual(image.size, (1000, 1000))
                self.assertIsNotNone(image.getbbox())
            details = json.loads(result.metadata_path.read_text())
            self.assertEqual(details["filenames"], result.plan.filenames)
            self.assertEqual(details["prompt"], "A bear with a peacock tail")
            arguments = client.interactions.create.call_args.kwargs
            self.assertIn("A bear with a peacock tail", arguments["input"])
            self.assertEqual(arguments["response_format"]["mime_type"], "application/json")
            client.close.assert_called_once()

    def test_no_outline_option_reaches_renderer_and_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "creature.png"
            with patch.object(frankenstein, "create_creature", wraps=frankenstein.create_creature) as render:
                result = logic.generate_creature(
                    request=fixture(),
                    output_path=output,
                    outline=False,
                )
            self.assertFalse(result.to_dict()["outline"])
            self.assertFalse(render.call_args.kwargs["outline"])

    def test_renderer_rejects_unknown_parts_and_duplicate_sockets(self):
        with self.assertRaisesRegex(ValueError, "Unknown parts"):
            frankenstein.build(["invented_torso.png"])
        with self.assertRaisesRegex(ValueError, "distinct existing socket"):
            frankenstein.build(["dog_torso.png", "dog_leg_rear_near.png", "dog_leg_rear_far.png"],
                               leg_socket_indices=[1, 1])


if __name__ == "__main__":
    unittest.main()
