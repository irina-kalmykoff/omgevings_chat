"""Shared, standard-library-only I/O and Model Client class."""
import hashlib
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def read_jsonl(path):
    with Path(path).open(encoding='utf-8') as file:
        return [json.loads(line) for line in file if line.strip()]


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temp.replace(path)


def write_jsonl(path, values):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(''.join(canonical(v) + '\n' for v in values), encoding='utf-8')
    temp.replace(path)


def append_jsonl(path, value):
    with Path(path).open('a', encoding='utf-8') as file:
        file.write(canonical(value) + '\n')
        file.flush()
        os.fsync(file.fileno())


def model_input(article):
    # Explicit allow-list: identifiers and provenance remain outside model input.
    return {key: article[key] for key in ('number', 'context', 'text')}


def parse_response(raw):
    raw = raw.strip()
    if raw.startswith('```'):
        lines = raw.splitlines()
        if lines[-1].strip() == '```':
            raw = '\n'.join(lines[1:-1])
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError('Model must return a JSON object')
    return result


class ModelClient:
    def __init__(self, backend, model, log_path, timeout=120, retries=1, temperature=0):
        self.backend, self.model, self.log_path = backend, model, Path(log_path)
        self.timeout, self.retries, self.temperature = timeout, retries, temperature
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        if backend == 'openai':
            self.url = 'https://api.openai.com/v1/chat/completions'
            self.key = os.environ.get('OPENAI_API_KEY')
            if not self.key:
                raise ValueError('Set OPENAI_API_KEY for the OpenAI backend')
        elif backend == 'ollama':
            self.url, self.key = 'http://localhost:11434/v1/chat/completions', 'ollama'
        else:
            raise ValueError('Unsupported backend')

    def call(self, stage, record_id, system, payload, examples=()):
        messages = [{'role': 'system', 'content': system}]
        for user, answer in examples:
            messages.extend([{'role': 'user', 'content': canonical(user)},
                             {'role': 'assistant', 'content': canonical(answer)}])
        messages.append({'role': 'user', 'content': canonical(payload)})
        body = {'model': self.model, 'temperature': self.temperature,
                'response_format': {'type': 'json_object'}, 'messages': messages}
        for attempt in range(self.retries + 1):
            start = time.monotonic()
            log = {'stage': stage, 'record_id': record_id, 'attempt': attempt,
                   'started_utc': datetime.now(timezone.utc).isoformat(),
                   'request': body, 'request_sha256': fingerprint(body)}
            try:
                request = urllib.request.Request(self.url, data=canonical(body).encode('utf-8'),
                    headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + self.key})
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    raw = response.read().decode('utf-8')
                log['response_raw'] = raw
                envelope = json.loads(raw)
                log['usage'] = envelope.get('usage', {})
                parsed = parse_response(envelope['choices'][0]['message']['content'])
                log['ok'] = True
                return parsed
            except Exception as error:
                # Never log authorization headers, environment variables or HTTP error bodies.
                log['ok'] = False
                log['error'] = type(error).__name__
                if isinstance(error, urllib.error.HTTPError):
                    log['http_status'] = error.code
                if attempt == self.retries:
                    raise RuntimeError(f'{stage} failed after {attempt + 1} attempts ({type(error).__name__})') from None
                time.sleep(min(2 ** attempt, 8))
            finally:
                log['elapsed_seconds'] = round(time.monotonic() - start, 4)
                append_jsonl(self.log_path, log)
