import subprocess
import unittest

import solver


class NavigationGuardTests(unittest.TestCase):
    def test_navigation_without_angular_returns_no_nav(self):
        class Tab:
            def js(self, expression):
                script = 'global.window = {}; global.document = {querySelectorAll: () => [], querySelector: () => null}; console.log(' + expression + ');'
                return subprocess.check_output(['node', '-e', script], text=True).strip()
        self.assertEqual(solver.set_next_step(Tab()), 'cannot advance step')
        # set_step now tries navigationService, then the dropdown component, and
        # only then reports the missing index. Without Angular the dropdown is
        # absent too, so the message is the index-specific one.
        self.assertEqual(solver.set_step(Tab(), 0), 'no step 0')
