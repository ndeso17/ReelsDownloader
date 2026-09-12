                    ┌──────────────────┐
                    │      Telegram    │
                    │      User        │
                    └────────┬─────────┘
                             │
                             │ URL
                             ▼
                 ┌───────────────────────┐
                 │    Telegram Bot       │
                 │ python-telegram-bot  │
                 └───────────┬───────────┘
                             │
                             ▼
                 ┌───────────────────────┐
                 │     URL Validator     │
                 └───────────┬───────────┘
                             │
                     Instagram/Facebook
                             │
                             ▼
                 ┌───────────────────────┐
                 │   Download Service    │
                 │                       │
                 │       yt-dlp          │
                 └───────────┬───────────┘
                             │
                             ▼
                 ┌───────────────────────┐
                 │        FFmpeg         │
                 │ merge/process media   │
                 └───────────┬───────────┘
                             │
                             ▼
                 ┌───────────────────────┐
                 │     downloads/        │
                 │     temporary file    │
                 └───────────┬───────────┘
                             │
                             ▼
                 ┌───────────────────────┐
                 │ Telegram send_video() │
                 └───────────┬───────────┘
                             │
                             ▼
                       Telegram User
                             │
                             ▼
                     Cleanup temporary
