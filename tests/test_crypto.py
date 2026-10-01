import json
import shutil
import subprocess
from pathlib import Path

import pytest

from fitapp.crypto import decrypt_json, encrypt_json


def test_roundtrip_and_wrong_passphrase():
    env = encrypt_json({"hrv": 61}, "correct horse", iterations=1000)
    assert decrypt_json(env, "correct horse") == {"hrv": 61}
    with pytest.raises(Exception):
        decrypt_json(env, "wrong")


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_browser_webcrypto_can_decrypt(tmp_path: Path):
    """The exact decrypt routine from site/app.js, run under Node's WebCrypto."""
    env = encrypt_json({"status": "red", "ü": "ok"}, "pass phrase", iterations=2000)
    (tmp_path / "env.json").write_text(json.dumps(env))
    script = tmp_path / "dec.mjs"
    script.write_text("""
import { readFileSync } from 'node:fs';
const env = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const b64 = s => Uint8Array.from(atob(s), c => c.charCodeAt(0));
const enc = new TextEncoder();
const base = await crypto.subtle.importKey('raw', enc.encode('pass phrase'), 'PBKDF2', false, ['deriveKey']);
const key = await crypto.subtle.deriveKey({ name: 'PBKDF2', salt: b64(env.salt), iterations: env.iter, hash: 'SHA-256' },
  base, { name: 'AES-GCM', length: 256 }, false, ['decrypt']);
const plain = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: b64(env.iv) }, key, b64(env.ct));
console.log(new TextDecoder().decode(plain));
""")
    out = subprocess.run(["node", str(script), str(tmp_path / "env.json")], capture_output=True, text=True, check=True)
    assert json.loads(out.stdout) == {"status": "red", "ü": "ok"}
