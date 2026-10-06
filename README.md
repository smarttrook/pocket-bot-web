Trade Radar V2.6
- Fixes Web Push 403 BadJwtToken by converting the Railway URL-safe VAPID private scalar to a standards-compliant P-256 PEM key before pywebpush signs JWTs.
- Uses a valid HTTPS VAPID subject by default.
- Existing VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY Railway variables can stay unchanged.
- After deploy: TURN OFF notifications once, TURN ON again, then press TEST.
