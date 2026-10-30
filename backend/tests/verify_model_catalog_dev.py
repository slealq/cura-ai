#!/usr/bin/env python3
"""Opt-in DEV verification: requires DEV_BACKEND_URL, DEV_ADMIN_EMAIL, DEV_ADMIN_PASSWORD,
Optional DEV_IMAGE_ID and DEV_CLUSTER_ID select the existing image and cluster. Dispatches billable jobs.
Run only after the reviewed release is deployed. Emits sanitized JSON under /private/tmp.
"""
import argparse
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true', required=True, help='authorize billable DEV operations')
    parser.add_argument('--timeout', type=int, default=600)
    parser.add_argument('--prompts', action='store_true', help='also run billable prompt expansion and suggestion')
    parser.add_argument('--output', type=Path, default=Path('/private/tmp/model-catalog-dev-results.json'))
    args = parser.parse_args()
    env = {k: os.environ.get(k) for k in ('DEV_BACKEND_URL', 'DEV_ADMIN_EMAIL', 'DEV_ADMIN_PASSWORD', 'DEV_IMAGE_ID', 'DEV_CLUSTER_ID')}
    if not all(env[k] for k in ('DEV_BACKEND_URL', 'DEV_ADMIN_EMAIL', 'DEV_ADMIN_PASSWORD')):
        parser.error('DEV_BACKEND_URL, DEV_ADMIN_EMAIL and DEV_ADMIN_PASSWORD are required')
    base = env['DEV_BACKEND_URL'].rstrip('/')
    report = {'date_utc': datetime.now(timezone.utc).isoformat(), 'checks': []}
    token = None

    def request(path, body=None):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        data = json.dumps(body).encode() if body is not None else None
        with urllib.request.urlopen(urllib.request.Request(base + path, data=data, headers=headers), timeout=30) as response:
            return json.load(response)

    def record(name, fn):
        try:
            details = fn()
            report['checks'].append({'name': name, 'ok': True, 'details': details})
        except Exception as exc:
            report['checks'].append({'name': name, 'ok': False, 'error_type': type(exc).__name__})
        args.output.write_text(json.dumps(report, indent=2) + '\n')

    def poll_job(job_id):
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            job = request(f'/api/jobs/{job_id}')
            if job['status'] in ('completed', 'failed', 'cancelled'):
                if job['status'] != 'completed':
                    raise RuntimeError('job did not complete')
                return {'job_id': job_id, 'status': job['status']}
            time.sleep(3)
        raise TimeoutError('job timeout')

    try:
        token = request('/api/auth/login', {'email': env['DEV_ADMIN_EMAIL'], 'password': env['DEV_ADMIN_PASSWORD']})['access_token']
    except Exception as exc:
        report['checks'].append({'name': 'login', 'ok': False, 'error_type': type(exc).__name__})
        args.output.write_text(json.dumps(report, indent=2) + '\n')
        return 1
    record('health', lambda: request('/health') if request('/health').get('status') == 'healthy' else (_ for _ in ()).throw(RuntimeError()))
    catalog = request('/api/settings/model-catalog')
    before = request('/api/billing/usage')
    initial_logs = request('/api/billing/admin/logs?limit=200')['items']
    last_log_id = max((row['id'] for row in initial_logs), default=0)
    image_id = int(env['DEV_IMAGE_ID']) if env['DEV_IMAGE_ID'] else request('/api/images?limit=1')['items'][0]['id']
    cluster_id = int(env['DEV_CLUSTER_ID']) if env['DEV_CLUSTER_ID'] else request('/api/clusters?limit=1')['items'][0]['id']
    record('tag_describe', lambda: poll_job(request(f'/api/images/{image_id}/reprocess', {'model': catalog['defaults']['vision_model']})['job_id']))

    def summarize():
        previous = request(f'/api/clusters/{cluster_id}')
        request(f'/api/clusters/{cluster_id}/summarize', {})
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            current = request(f'/api/clusters/{cluster_id}')
            if current.get('summary_title') and current.get('updated_at') and current.get('updated_at') != previous.get('updated_at'):
                return {'cluster_id': cluster_id, 'summary_present': True}
            time.sleep(3)
        raise TimeoutError('cluster update not observed')

    record('summarize', summarize)
    record('generate', lambda: poll_job(request('/api/generation/generate', {'prompt': 'A simple blue circle on white', 'base_model': catalog['defaults']['generation_model'], 'num_images': 1})['job_id']))
    record('edit', lambda: poll_job(request('/api/edit', {'prompt': 'Add a small blue circle', 'source_image_ids': [image_id], 'edit_model': catalog['defaults']['edit_model'], 'num_images': 1})['job_id']))
    def require_output(path, body, field):
        if not request(path, body).get(field):
            raise ValueError('empty response')
        return {'output_present': True}

    if args.prompts:
        record('expand_prompt', lambda: require_output('/api/generation/expand-prompt', {'prompt': 'a blue circle'}, 'expanded_prompt'))
        record('suggest_prompt', lambda: require_output('/api/settings/prompts/suggest', {'current_prompt': 'Describe this image', 'change_request': 'Be concise', 'prompt_type': 'description'}, 'suggested_prompt'))

    def usage():
        after = request('/api/billing/usage')
        changes = {op: after.get('by_operation', {}).get(op, 0) - before.get('by_operation', {}).get(op, 0)
                   for op in (('tag', 'describe', 'summarize', 'generate', 'edit', 'expand_prompt', 'suggest_prompt') if args.prompts else ('tag', 'describe', 'summarize', 'generate', 'edit'))}
        logs = request('/api/billing/admin/logs?limit=200')['items']
        recent = [row for row in logs if row['id'] > last_log_id and row['user_email'] == env['DEV_ADMIN_EMAIL']]
        verified = {op: any(row['operation'] == op and row['provider'] == 'fal' and row['charged_cost'] > 0 for row in recent)
                    for op in (('tag', 'describe', 'summarize', 'generate', 'edit', 'expand_prompt', 'suggest_prompt') if args.prompts else ('tag', 'describe', 'summarize', 'generate', 'edit'))}
        if any(value <= 0 for value in changes.values()) or not all(verified.values()):
            raise ValueError('missing non-zero fal usage for an operation')
        return {'new_records': after['record_count'] - before['record_count'], 'charged_cost_delta': after['total_cost'] - before['total_cost'], 'operation_deltas': changes, 'fal_operations_verified': verified}

    record('billing_usage', usage)
    record('error_log_query', lambda: {'reachable': isinstance(request('/api/logs?level=error'), (dict, list))})
    print(f'Saved sanitized results to {args.output}')
    return int(any(not c['ok'] for c in report['checks']))


if __name__ == '__main__':
    raise SystemExit(main())
