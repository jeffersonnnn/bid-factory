"""Run locally. Resolve the optional macOS credential without a plaintext key file."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load_keychain():
    if os.getenv('AI_PROVIDER') == 'openrouter' and not os.getenv('OPENROUTER_API_KEY'):
        if sys.platform != 'darwin':
            raise SystemExit('Set OPENROUTER_API_KEY in the server environment.')
        result = subprocess.run(['/usr/bin/security', 'find-generic-password', '-a', 'bid-factory',
                                 '-s', 'bid-factory.openrouter', '-w'], capture_output=True, text=True)
        if result.returncode or not result.stdout.strip():
            raise SystemExit('OpenRouter credential was not found in macOS Keychain.')
        os.environ['OPENROUTER_API_KEY'] = result.stdout.strip()


if __name__ == '__main__':
    import uvicorn
    load_keychain()
    uvicorn.run('app.main:app', host='127.0.0.1', port=int(os.getenv('PORT', '8765')), proxy_headers=False)
