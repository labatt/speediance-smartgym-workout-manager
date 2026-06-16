# Unofficial SmartGym Workout Manager — OpenClaw / Aria Public Fork

> **This is a personal fork** of the original project by [hbui3](https://github.com/hbui3/UnofficialSpeedianceWorkoutManager).
> All credit for the original work goes to him and to the contributors who built the public Speediance/SmartGym manager foundation.
> There is no intention to take credit for or create confusion with the original project.

---

## Notice from the Original Developer

> This project is being discontinued as Speediance is implementing security upgrades to their API infrastructure. Official alternatives for custom template management and desktop workflows are currently under development by the vendor's team.
> Thank you to everyone who contributed feedback, ideas, and support.

*— [hbui3](https://github.com/hbui3/UnofficialSpeedianceWorkoutManager)*

---

This fork may continue to function as long as the API remains accessible, but is subject to the same limitations described above. Use at your own risk.

---

## Credit and Lineage

This repository is a public, non-secret publication copy used by OpenClaw / Aria as a Speediance connector and planning reference.

### Original project: hbui3

Credit to [hbui3/UnofficialSpeedianceWorkoutManager](https://github.com/hbui3/UnofficialSpeedianceWorkoutManager) for the original unofficial Speediance desktop manager, including the core Flask app, Speediance API client, login/config flow, settings UI, custom workout management, exercise/library screens, workout builder foundations, prompt/export workflow, and test scaffolding.

### Practical continuation: ANPC86 fork

Credit to [ANPC86/SmartGymWorkoutManager](https://github.com/ANPC86/SmartGymWorkoutManager) for the practical fork this public copy was based on. The ANPC86 fork added and/or carried forward many of the day-to-day usability improvements listed below, including workout-builder polish, history/export work, calendar fixes, debug tooling, Docker setup, and regression coverage.

### OpenClaw / Aria additions

This public fork adds the OpenClaw / Aria-specific pieces needed for agent-readable fitness automation without publishing credentials, cached vendor payloads, or personal exports.

---

## Current Changes and Features

### OpenClaw / Aria additions in this public repo

- **Adaptive Speediance planner** — `adaptive_training.py` builds readiness-aware Speediance plans from normalized training signals.
- **Readiness buckets** — classifies days into build, maintain, recover, protect, or post-BJJ-brutal modes.
- **Single-implement Speediance workouts** — selects one implement per on-device workout, usually handles, barbell, or rope.
- **On-device plus off-device split** — keeps 10 on-device Speediance exercises and optionally adds 0-2 off-Speediance accessories outside the device payload.
- **Plan uniqueness window** — compares recent training-plan signatures so generated workouts do not repeat too quickly.
- **Speediance payload conversion** — converts the planner output into the `SpeedianceClient.save_workout` exercise contract.
- **Run and step guidance** — emits a run prescription and step target alongside the strength plan.
- **Preferred coach variant selection** — defaults unspecified exercise variants to Liz / coach id `31` when available, while preserving explicit manual variant choices.
- **Auth and protocol hardening** — adds structured API/auth/protocol exceptions, reusable request sessions, better Speediance API-code handling, and optional environment-backed re-login.
- **Public safety scaffolding** — includes `.env.example`, `PUBLICATION_SAFETY.md`, and ignore rules for config files, library caches, exports, logs, databases, and virtualenvs.
- **Self-contained tests** — adaptive planner tests use fake movement pools and temp directories instead of requiring local OpenClaw data.

### ANPC86 fork additions preserved here

#### Workout Builder Enhancements
- **Live stats bar** — shows total exercises, estimated volume, total time, and rest time as you build
- **Move to top / bottom buttons** — quickly reorder exercises without repeated dragging
- **Redesigned header** — two-row layout with stats aligned to the right for a cleaner look
- **Est. Burn chip** — displays estimated calorie burn alongside other stats
- **Target Muscles radar chart** — visual breakdown of which muscle groups your workout covers
- **Vita exercise support** — correctly handles Vita exercises (level 1–10) in the builder and when saving
- **Cardio/timed exercises** — time input and dynamic preset dropdown work correctly for row, ski, and kcal modes
- **Condensed workout cards** — all key stats shown in a single line per exercise

#### Workout History
- **Full history page** — view all past workouts with date, duration, calories, and exercise details
- **Export options** — download your workout history as a file
- **Accurate timestamps** — dates display in your local timezone rather than a fixed region

#### My Workouts (Home Page)
- **Workout count** — heading shows how many custom workouts you have at a glance
- **Improved layout** — reorganized and sorted for easier navigation

#### Calendar
- **Day offset correction** — calendar highlights the correct day regardless of your timezone
- **Drag/drop scheduling support** — schedule, move, and remove custom workouts on the calendar UI

#### API Debug Console
- **Debug panel** — floating button reveals the last raw API response, useful for troubleshooting connection or data issues

#### Weight Unit Handling (Imperial / Metric)
- **Accurate LBS storage** — weights entered in Imperial are stored and retrieved correctly without incorrect unit conversion being applied
- **Preset ID preservation** — preset IDs, including `0`, are preserved when saving workouts instead of being coerced to custom mode

---

## What Is Intentionally Not Published

This repo should not contain:

- real `config.json` credentials
- `.env` files with secrets
- Speediance tokens or user IDs
- cached library payloads such as `library_cache*.json`
- workout exports, CSV files, logs, screenshots, databases, or personal fitness data
- private OpenClaw report outputs

Use `.env.example` and `config.example.json` as templates only.

---

## Running Tests

Python unit tests:

```bash
python3 -m unittest -v tests/test_unit.py tests/test_adaptive_training.py
```

JavaScript workout-logic tests:

```bash
node --test tests/workout-logic.test.mjs
```

The top-level `test_e2e_workouts.py` file is intentionally credential-gated and skips when no Speediance credentials are configured.

---

## Running with Docker

A `docker-compose.yml` template is included for running the app in a container.

**Before starting**, edit the `volumes` path to point to the folder where you unzipped or cloned this repository:

```yaml
volumes:
  - /path/to/your/app:/app
```

- **Windows example:** `/c/Users/yourname/Downloads/SmartGymWorkoutManager`
- **Linux / Synology NAS example:** `/volume1/docker/smart-gym-app`

Then run:

```bash
docker compose up -d
```

The app will be available at `http://localhost:5001`.
