#!/usr/bin/env python3
"""Opt-in paid catalog verification. Run from backend: python tests/verify_model_catalog.py --paid.

Makes real fal calls. Results contain no prompts, URLs returned by fal, keys, or raw exceptions.
Use --research-only to fetch OpenRouter metadata and fal OpenAPI without paid calls.
"""
import argparse
import base64
import io
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import dotenv_values  # noqa: E402
from PIL import Image  # noqa: E402

from app.providers.fal_provider import build_image_request  # noqa: E402
from app.providers.fal_vision_provider import build_router_request  # noqa: E402
from app.services.model_catalog import IMAGE_MODELS, LANGUAGE_MODELS  # noqa: E402

OUTPUT = Path('/private/tmp/model-catalog-live-results.json')


def fetch_json(url):
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.load(response)


def run(endpoint, arguments, timeout):
    import fal_client
    from fal_client.client import Completed

    handle = fal_client.submit(endpoint, arguments=arguments)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if isinstance(handle.status(with_logs=False), Completed):
            return handle.get()
        time.sleep(2)
    try:
        handle.cancel()
    finally:
        raise TimeoutError('poll deadline exceeded')


def image_uri():
    image = Image.new('RGB', (512, 512), 'red')
    buf = io.BytesIO()
    image.save(buf, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()


def verify_image(result):
    images = result.get('images') or ([result['image']] if result.get('image') else [])
    if not images:
        raise ValueError('no image returned')
    url = images[0].get('url') if isinstance(images[0], dict) else images[0]
    if not isinstance(url, str) or not url.startswith(('https://', 'http://')):
        raise ValueError('missing output image URL')
    with urllib.request.urlopen(url, timeout=30) as response:
        image = Image.open(io.BytesIO(response.read(20_000_000)))
        image.verify()
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--paid', action='store_true')
    group.add_argument('--research-only', action='store_true')
    parser.add_argument('--timeout', type=int, default=300)
    parser.add_argument('--skip-research', action='store_true')
    parser.add_argument('--only-failed', action='store_true', help='rerun failures in the existing output')
    parser.add_argument('--model', action='append', help='model ID or key; repeat to select several')
    parser.add_argument('--output', type=Path, default=OUTPUT)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error('--timeout must be positive')
    if args.only_failed and not args.output.exists():
        parser.error('--only-failed requires an existing output file')
    report = json.loads(args.output.read_text()) if args.output.exists() and (args.only_failed or args.model) else {'research': [], 'smoke': []}
    report.update(date_utc=datetime.now(timezone.utc).isoformat(), paid=args.paid)
    failed = {(r.get('kind'), r.get('model')) for r in report['smoke'] if not r.get('ok')}

    def selected(kind, model):
        return (not args.model or model in args.model) and (not args.only_failed or (kind, model) in failed)

    def save(record):
        report['smoke'] = [r for r in report['smoke'] if (r.get('kind'), r.get('model')) != (record['kind'], record['model'])]
        report['smoke'].append(record)
        args.output.write_text(json.dumps(report, indent=2) + '\n')

    def error(record, exc):
        # Allow only fixed diagnostic phrases; never serialize provider response bodies.
        message = str(exc).lower()
        record['error_type'] = type(exc).__name__
        for phrase in ('content_policy_violation', 'guardrail restrictions', 'zdr violation', 'zdr', 'image_too_small', 'minimum image size', 'semantic response check failed', 'reasoning is mandatory', 'invalid api key', 'unauthorized', 'insufficient balance', 'validation error', 'model not found', 'deprecated', 'timeout'):
            if phrase in message:
                record['error_category'] = phrase
                break
        else:
            record['error_category'] = 'unclassified'

    if not args.skip_research:
      try:
        directory = {m['id']: m for m in fetch_json('https://openrouter.ai/api/v1/models')['data']}
        for model in LANGUAGE_MODELS:
            item = directory.get(model.id)
            report['research'].append({'kind': 'language', 'id': model.id, 'listed': bool(item),
                'vision': bool(item and 'image' in item.get('architecture', {}).get('input_modalities', [])),
                'pricing': item.get('pricing') if item else None,
                'temperature': bool(item and 'temperature' in item.get('supported_parameters', [])),
                'reasoning_mandatory': (item.get('reasoning') or {}).get('mandatory') if item else None})
      except Exception as exc:
        report['research'].append({'kind': 'openrouter', 'error_type': type(exc).__name__})
    for model in ([] if args.skip_research else IMAGE_MODELS):
        for endpoint in filter(None, (model.endpoint, model.lora_endpoint, model.trainer_endpoint)):
            try:
                metadata = fetch_json('https://api.fal.ai/v1/models?' + urllib.parse.urlencode({'endpoint_id': endpoint}))
                matches = metadata.get('models') or []
                item = matches[0] if matches else {}
                report['research'].append({'kind': 'fal_status', 'endpoint': endpoint,
                    'status': (item.get('metadata') or {}).get('status'),
                    'category': (item.get('metadata') or {}).get('category'),
                    'deprecated': bool(item.get('deprecated_at')),
                    'listed': bool(item)})
            except Exception as exc:
                report['research'].append({'kind': 'fal_status', 'endpoint': endpoint, 'error_type': type(exc).__name__})
            try:
                schema = fetch_json('https://fal.ai/api/openapi/queue/openapi.json?' + urllib.parse.urlencode({'endpoint_id': endpoint}))
                report['research'].append({'kind': 'fal_schema', 'endpoint': endpoint, 'available': bool(schema.get('paths'))})
            except Exception as exc:
                report['research'].append({'kind': 'fal_schema', 'endpoint': endpoint, 'error_type': type(exc).__name__})
    if args.paid:
        key = os.environ.get('FAL_API_KEY') or os.environ.get('FAL_KEY') or dotenv_values(Path(__file__).resolve().parents[2] / '.env').get('FAL_API_KEY')
        if not key:
            parser.error('FAL_API_KEY missing from environment and repository .env')
        os.environ['FAL_KEY'] = key
        source = image_uri()
        for model in LANGUAGE_MODELS:
            for mode in ('text', 'vision'):
                if not selected(mode, model.id):
                    continue
                record = {'kind': mode, 'model': model.id, 'ok': False}
                try:
                    prompt = 'Reply with exactly RED.' if mode == 'text' else 'Name the dominant color of the image in one word.'
                    endpoint, payload = build_router_request(model.id, prompt, 4096 if model.requires_reasoning else 256, [source] if mode == 'vision' else None, 0)
                    result = run(endpoint, payload, args.timeout)
                    text = str(result.get('output') or result.get('text') or '')
                    if 'red' not in text.lower():
                        raise ValueError('semantic response check failed')
                    record.update(ok=True, cost=(result.get('usage') or {}).get('cost'))
                except Exception as exc:
                    error(record, exc)
                save(record)
        for model in IMAGE_MODELS:
            if not selected(model.kind, model.key):
                continue
            record = {'kind': model.kind, 'model': model.key, 'endpoint': model.endpoint, 'ok': False}
            try:
                values = {'num_images': 1}
                for name, spec in model.params.items():
                    options = spec.get('options', [])
                    if name == 'resolution' and options:
                        values[name] = options[0]
                    elif name == 'quality' and options:
                        values[name] = options[0]
                    elif name == 'image_size' and options:
                        values[name] = 'square' if 'square' in options else options[0]
                endpoint, payload = build_image_request(model, 'A simple blue circle on a white background', values,
                    source_urls=[source] if model.kind == 'edit' else None)
                result = run(endpoint, payload, args.timeout)
                verify_image(result)
                record.update(ok=True, cost=(result.get('usage') or {}).get('cost'))
            except Exception as exc:
                error(record, exc)
            save(record)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(f"Saved sanitized results to {args.output}; {sum(not r.get('ok') for r in report['smoke'])} smoke failures")
    return int(any(not r.get('ok') for r in report['smoke']))


if __name__ == '__main__':
    raise SystemExit(main())
