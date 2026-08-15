import json
import tempfile
import unittest
from pathlib import Path

from studio.platform.capabilities import detect_capabilities
from studio.platform.config import ApplicationConfig, ConfigurationError
from studio.platform.models import ModelManager


class PlatformFoundationTests(unittest.TestCase):
    def test_configuration_merges_defaults_and_preserves_unknown_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(json.dumps({"device": "auto", "future_setting": 7}), encoding="utf-8")
            config = ApplicationConfig.load(path, {"whisper_model": "small"})
        self.assertEqual(config.get_str("whisper_model"), "small")
        self.assertEqual(config.get_str("device"), "auto")
        self.assertEqual(config.get_int("future_setting", minimum=1), 7)

    def test_invalid_boolean_is_rejected(self):
        config = ApplicationConfig({"enabled": "perhaps"})
        with self.assertRaises(ConfigurationError):
            config.get_bool("enabled")

    def test_save_round_trip_keeps_unknown_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            config = ApplicationConfig({"future_setting": "kept", "device": "cpu"}, path)
            config.save()
            restored = ApplicationConfig.load(path)
        self.assertEqual(restored.get_str("future_setting"), "kept")
        self.assertEqual(restored.get_str("device"), "cpu")

    def test_capability_detection_and_model_fallback_are_safe(self):
        capabilities = detect_capabilities()
        self.assertIn(capabilities.recommended_device, {"cpu", "cuda"})
        compute_type = ModelManager().recommend_compute_type("large-v3", capabilities)
        self.assertIn(compute_type, {"int8", "float16"})


if __name__ == "__main__":
    unittest.main()
