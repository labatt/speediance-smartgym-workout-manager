# Publication Safety Notes

This candidate is intended to be published as a standalone Speediance/SmartGym connector fork without exposing unrelated fitness-report code.

Before publishing:

- Publish from this clean copy, not from a private monorepo or personal working tree.
- Do not include `.git` history from any private repo.
- Keep credentials in environment variables or local ignored config files only.
- Keep `config.json`, `.env`, workout exports, cached library files, logs, databases, screenshots, and personal fitness data out of git.
- Treat the Speediance integration as unofficial and unstable because vendor auth/API behavior can change.
- Preserve upstream attribution to `hbui3/UnofficialSpeedianceWorkoutManager`.
