"""Offline execution of the actual assessment submit JavaScript in Node."""
import json
import os
import shutil
import subprocess
import unittest
from unittest.mock import patch

import auto

NODE = shutil.which("node")

# No network or browser: record the consequences of each actual emitted script.
HARNESS = r"""
const spec = JSON.parse(process.argv[1]);
const events = spec.events;
const button = {click() { events.push('dom'); if (spec.throws) throw Error('click failed'); }};
const nav = {};
if (spec.hasNav) nav.submitTest = () => { events.push('nav'); if (spec.navThrows) throw Error('nav failed'); };
const app = {};
const document = {querySelector(s) { return s === 'app' ? app : (spec.hasButton ? button : null); }};
const angular = {element() { return {triggerHandler() { events.push('angular'); }}; }};
const window = {angular, ng: {probe() { return {componentInstance: {navigationService: nav}}; }}};
let result = null, error = false;
try { result = eval(spec.script); } catch (e) { error = true; }
process.stdout.write(JSON.stringify({events, result: result ?? null, error}));
"""


class SubmitTab:
    def __init__(self, *, has_button=True, has_nav=True, throws=False, nav_throws=False, button_appears=False):
        self.events = []
        self.confirm_checks = 0
        self.has_button, self.has_nav, self.throws = has_button, has_nav, throws
        self.nav_throws, self.button_appears = nav_throws, button_appears

    def js(self, expr):
        if 'e.click(); return 1;' in expr or "triggerHandler('click')" in expr or 'navigationService?.submitTest' in expr:
            has_button = self.has_button or (self.button_appears and 'e.click(); return 1;' not in expr)
            spec = dict(script=expr, events=self.events, hasButton=has_button,
                        hasNav=self.has_nav, throws=self.throws, navThrows=self.nav_throws)
            proc = subprocess.run([NODE, '-e', HARNESS, json.dumps(spec)], capture_output=True, text=True, check=True)
            output = json.loads(proc.stdout)
            self.events = output['events']
            if output['error']:
                raise RuntimeError('JS click failed after side effect')
            return output['result']
        if "iframe-clicked" in expr:
            self.confirm_checks += 1
        if expr == auto.NAV_STATE_SIG_JS:
            return 'same-state'
        if 'document.body?.innerText' in expr:
            return 'Question 30 of 30'
        return ''


@unittest.skipUnless(NODE, 'node required')
class AssessmentSingleSubmitTests(unittest.TestCase):
    def run_submit(self, tab):
        with patch.dict(os.environ, {'ED_ASSESSMENT': '1'}), \
             patch.object(auto, 'is_test_area', return_value=True), \
             patch.object(auto, 'assessment_submit_state', return_value='ready'), \
             patch.object(auto, 'require_action_mode'), \
             patch.object(auto.solver, 'attach_transcript', return_value={}), \
             patch.object(auto.solver, 'do_task', return_value='mcq: A'), \
             patch.object(auto, 'q', return_value=0), \
             patch.object(auto, 'st', return_value={'total': '30', 'counter': '30'}), \
             patch.object(auto.poll, 'wait_until', side_effect=[0, '']), \
             patch.object(auto.time, 'sleep'):
            return auto.handle_test(tab, {})

    def test_dom_click_is_the_only_submission_trigger(self):
        tab = SubmitTab()
        self.assertEqual(self.run_submit(tab), 'test-submit-unverified')
        self.assertEqual(tab.events, ['dom'])
        self.assertEqual(tab.confirm_checks, 1)

    def test_missing_button_falls_back_to_navigation_once_and_checks_result(self):
        tab = SubmitTab(has_button=False)
        self.assertEqual(self.run_submit(tab), 'test-submit-unverified')
        self.assertEqual(tab.events, ['nav'])
        self.assertEqual(tab.confirm_checks, 1)

    def test_fallback_completion_is_verified_before_success(self):
        tab = SubmitTab(has_button=False)
        with patch.dict(os.environ, {'ED_ASSESSMENT': '1'}), \
             patch.object(auto, 'is_test_area', return_value=True), \
             patch.object(auto, 'assessment_submit_state', return_value='ready'), \
             patch.object(auto, 'require_action_mode'), \
             patch.object(auto.solver, 'attach_transcript', return_value={}), \
             patch.object(auto.solver, 'do_task', return_value='mcq: A'), \
             patch.object(auto, 'q', return_value=0), \
             patch.object(auto, 'st', return_value={'total': '30', 'counter': '30'}), \
             patch.object(auto.poll, 'wait_until', side_effect=[1, 'Your score is 90%.']), \
             patch.object(auto, 'is_final_assessment_complete', return_value=True) as verified, \
             patch.object(auto.time, 'sleep'):
            result = auto.handle_test(tab, {})
        self.assertTrue(result.startswith('test-submit-final'))
        self.assertEqual(tab.events, ['nav'])
        verified.assert_called_once()

    def test_fallback_is_blocked_if_readiness_changes(self):
        tab = SubmitTab(has_button=False)
        with patch.dict(os.environ, {'ED_ASSESSMENT': '1'}), \
             patch.object(auto, 'is_test_area', return_value=True), \
             patch.object(auto, 'assessment_submit_state', side_effect=['ready', 'unknown']), \
             patch.object(auto, 'require_action_mode'), \
             patch.object(auto.solver, 'attach_transcript', return_value={}), \
             patch.object(auto.solver, 'do_task', return_value='mcq: A'), \
             patch.object(auto, 'q', return_value=0), \
             patch.object(auto, 'st', return_value={'total': '30', 'counter': '30'}):
            self.assertEqual(auto.handle_test(tab, {}), 'test-submit-unverified')
        self.assertEqual(tab.events, [])
        self.assertEqual(tab.confirm_checks, 0)

    def test_missing_button_and_navigation_fails_closed(self):
        tab = SubmitTab(has_button=False, has_nav=False)
        self.assertEqual(self.run_submit(tab), 'test-submit-unverified')
        self.assertEqual(tab.events, [])
        self.assertEqual(tab.confirm_checks, 0)

    def test_appearing_button_blocks_navigation_fallback(self):
        tab = SubmitTab(has_button=False, button_appears=True)
        self.assertEqual(self.run_submit(tab), 'test-submit-unverified')
        self.assertEqual(tab.events, [])
        self.assertEqual(tab.confirm_checks, 0)

    def test_navigation_exception_is_not_retried(self):
        tab = SubmitTab(has_button=False, nav_throws=True)
        self.assertEqual(self.run_submit(tab), 'test-submit-unverified')
        self.assertEqual(tab.events, ['nav'])
        self.assertEqual(tab.confirm_checks, 0)

    def test_click_exception_never_triggers_fallback(self):
        tab = SubmitTab(throws=True)
        self.assertEqual(self.run_submit(tab), 'test-submit-unverified')
        self.assertEqual(tab.events, ['dom'])
        self.assertEqual(tab.confirm_checks, 0)
