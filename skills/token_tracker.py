#!/usr/bin/env python3
"""
skills/token_tracker.py
Token usage tracker for LLM calls. Logs to /tmp/btc_5m_tokens.json
"""
import json
import os
from datetime import datetime, timezone
from threading import Lock

_TOKEN_FILE = '/tmp/btc_5m_tokens.json'
_lock = Lock()

class TokenTracker:
    def __init__(self, session_id: str = None):
        self.session_id = session_id or datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
        self._load()

    def _load(self):
        try:
            if os.path.exists(_TOKEN_FILE):
                with open(_TOKEN_FILE) as f:
                    self._data = json.load(f)
            else:
                self._data = {'sessions': {}, 'total': {'in': 0, 'out': 0, 'calls': 0}}
        except Exception:
            self._data = {'sessions': {}, 'total': {'in': 0, 'out': 0, 'calls': 0}}

    def _save(self):
        try:
            tmp = _TOKEN_FILE + '.tmp'
            with open(tmp, 'w') as f:
                json.dump(self._data, f, indent=2)
            os.replace(tmp, _TOKEN_FILE)
        except Exception:
            pass

    def log(self, model: str, input_tokens: int, output_tokens: int, task: str = ''):
        """Log a single LLM call"""
        with _lock:
            self._load()
            sess = self._data['sessions'].setdefault(self.session_id, {
                'started': datetime.now(timezone.utc).isoformat(),
                'in': 0, 'out': 0, 'calls': 0, 'tasks': []
            })
            sess['in'] += input_tokens
            sess['out'] += output_tokens
            sess['calls'] += 1
            sess['tasks'].append({
                'ts': datetime.now(timezone.utc).isoformat(),
                'model': model,
                'in': input_tokens,
                'out': output_tokens,
                'task': task
            })
            self._data['total']['in'] += input_tokens
            self._data['total']['out'] += output_tokens
            self._data['total']['calls'] += 1
            self._save()

    def get_summary(self) -> dict:
        """Return current session + total summary"""
        with _lock:
            self._load()
            sess = self._data['sessions'].get(self.session_id, {'in': 0, 'out': 0, 'calls': 0})
            return {
                'session': self.session_id,
                'session_in': sess.get('in', 0),
                'session_out': sess.get('out', 0),
                'session_calls': sess.get('calls', 0),
                'total_in': self._data['total']['in'],
                'total_out': self._data['total']['out'],
                'total_calls': self._data['total']['calls'],
                # Compatibility
                'in': sess.get('in', 0),
                'out': sess.get('out', 0),
                'calls': sess.get('calls', 0),
                'total': sess.get('in', 0) + sess.get('out', 0),
            }

if __name__ == "__main__":
    # Test
    t = TokenTracker('test')
    t.log('minimax/M2.7', 1000, 500, 'test')
    print(t.get_summary())
