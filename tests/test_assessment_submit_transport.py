"""Exercise assessment submission through real CDP driver with a fake websocket."""
import itertools
import json
import os
import shutil
import subprocess
import unittest
from unittest.mock import patch

import auto
import driver

NODE = shutil.which('node')
JS = r"""
const s = JSON.parse(process.argv[1]);
const actions = [];
const button = {click(){actions.push('dom');}};
const nav = {submitTest(){actions.push('nav');}};
const app = {};
const document = {
 querySelector(sel){if(sel==='app') return app; return s.button ? button : null;},
 querySelectorAll(sel){return [];},
};
const window = {location:{href:'https://offline.invalid/Runtime/TestArea.html'},
 ng:{probe(){return {componentInstance:{isTestEnv:true,navigationService:nav}};}}};
let res = eval(s.expr);
process.stdout.write(JSON.stringify({actions, result:res ?? null}));
"""


class FakeSocket:
    def __init__(self, actions, *, button, lose_kind, lose_error, first=True):
        self.actions = actions
        self.button = button
        self.lose_kind = lose_kind
        self.lose_error = lose_error
        self.first = first
        self.pending = None
        self.lost = False
        self.socket = self

    def settimeout(self, _):
        pass

    def close(self):
        pass

    def send(self, data):
        msg = json.loads(data)
        val = None
        self.lost = False
        if msg['method'] == 'Runtime.evaluate':
            p = subprocess.run([NODE, '-e', JS, json.dumps({'expr': msg['params']['expression'], 'button': self.button})],
                               check=True, text=True, capture_output=True)
            out = json.loads(p.stdout)
            self.actions.extend(out['actions'])
            val = out['result']
            self.lost = self.first and self.lose_kind in out['actions']
        self.pending = {'id': msg['id'], 'result': {'result': {'value': val}}}

    def recv(self, timeout=None):
        if self.lost:
            self.lost = False
            raise self.lose_error
        return json.dumps(self.pending)


@unittest.skipUnless(NODE, 'node required')
class AssessmentSubmitTransportTests(unittest.TestCase):
    def test_lost_response_never_replays_assessment_dom_click(self):
        actions = []
        first = FakeSocket(actions, button=True, lose_kind='dom', lose_error=driver.ConnectionClosed(None, None))
        second = FakeSocket(actions, button=True, lose_kind='dom', lose_error=driver.ConnectionClosed(None, None), first=False)
        tab = driver.Tab.__new__(driver.Tab)
        tab.url, tab.ws, tab.ids, tab.dialogs, tab.events = 'ws://offline', first, itertools.count(1), [], []
        guarded = auto.GuardedTab(tab, True)
        with patch.object(driver, 'connect', return_value=second), \
             patch.dict(os.environ, {'ED_ASSESSMENT': '1'}), \
             patch.object(auto, 'is_test_area', return_value=True), \
             patch.object(auto, 'assessment_submit_state', return_value='ready'), \
             patch.object(auto, 'require_action_mode'), \
             patch.object(auto.solver, 'attach_transcript', return_value={}), \
             patch.object(auto.solver, 'do_task', return_value='mcq: A'), \
             patch.object(auto, 'q', return_value=0), \
             patch.object(auto, 'st', return_value={'total': '30', 'counter': '30'}), \
             patch.object(auto.poll, 'wait_until', side_effect=[0, '']), \
             patch.object(auto.time, 'sleep'):
            result = auto.handle_test(guarded, {})
        self.assertEqual(result, 'test-submit-unverified')
        self.assertEqual(actions, ['dom'])
