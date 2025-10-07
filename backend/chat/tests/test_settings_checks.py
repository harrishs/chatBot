from django.core import checks
from django.test import SimpleTestCase, override_settings


class ProductionDebugCheckTests(SimpleTestCase):
    def _run_check(self):
        return [error for error in checks.run_checks() if error.id == 'chat.E001']

    def test_error_when_debug_true_in_production(self):
        with override_settings(ENV='production', DEBUG=True):
            errors = self._run_check()
            self.assertTrue(errors)

    def test_no_error_when_debug_false_in_production(self):
        with override_settings(ENV='production', DEBUG=False):
            errors = self._run_check()
            self.assertFalse(errors)

    def test_no_error_for_non_production_env(self):
        with override_settings(ENV='development', DEBUG=True):
            errors = self._run_check()
            self.assertFalse(errors)
