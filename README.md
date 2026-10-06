# Trade Radar V2.4

- Fixed to 5-minute signals only.
- Starting the radar mid-window waits for the next exact 5-minute boundary before scanning/publishing signals.
- Maximum 3 qualifying signals per scan.
- Current Signals tab shows only active, unexpired signals; Results keeps closed outcomes.
- Web Push on/off remains in the page. Server requires VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY environment variables.
- VAPID_SUBJECT is optional and defaults to mailto:radar@localhost.
