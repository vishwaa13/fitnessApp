# Food log

This branch holds `food.enc.json`, the log behind the dashboard's Food tab.
Your browser encrypts it with the dashboard passphrase (AES-256-GCM) before
saving it here through GitHub's contents API, so this public branch only ever
contains the scrambled file. No workflow runs on pushes to this branch.

Don't merge it into `main`.
