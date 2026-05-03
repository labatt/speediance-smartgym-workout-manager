# Unofficial SmartGym Workout Manager — Personal Fork

> **This is a personal fork** of the original project by [hbui3](https://github.com/hbui3/UnofficialSpeedianceWorkoutManager).
> All credit for the original work goes to him. This fork exists solely for personal use and testing of additional fixes and features.
> There is no intention to take credit for or create confusion with the original project.

---

## Notice from the Original Developer

> This project is being discontinued as Speediance is implementing security upgrades to their API infrastructure. Official alternatives for custom template management and desktop workflows are currently under development by the vendor's team.
> Thank you to everyone who contributed feedback, ideas, and support.

*— [hbui3](https://github.com/hbui3/UnofficialSpeedianceWorkoutManager)*

---

This fork may continue to function as long as the API remains accessible, but is subject to the same limitations described above. Use at your own risk.

---

## Changes & Features in This Fork

### Workout Builder Enhancements
- **Live stats bar** — shows total exercises, estimated volume, total time, and rest time as you build
- **Move to top / bottom buttons** — quickly reorder exercises without repeated dragging
- **Redesigned header** — two-row layout with stats aligned to the right for a cleaner look
- **Est. Burn chip** — displays estimated calorie burn alongside other stats
- **Target Muscles radar chart** — visual breakdown of which muscle groups your workout covers
- **Vita exercise support** — correctly handles Vita exercises (level 1–10) in the builder and when saving
- **Cardio/timed exercises** — time input and dynamic preset dropdown work correctly for row, ski, and kcal modes
- **Condensed workout cards** — all key stats shown in a single line per exercise

### Workout History
- **Full history page** — view all past workouts with date, duration, calories, and exercise details
- **Export options** — download your workout history as a file
- **Accurate timestamps** — dates display in your local timezone rather than a fixed region

### My Workouts (Home Page)
- **Workout count** — heading shows how many custom workouts you have at a glance
- **Improved layout** — reorganized and sorted for easier navigation

### Calendar
- **Day offset correction** — calendar highlights the correct day regardless of your timezone

### API Debug Console
- **Debug panel** — floating button reveals the last raw API response, useful for troubleshooting connection or data issues

### Weight Unit Handling (Imperial / Metric)
- **Accurate LBS storage** — weights entered in Imperial are stored and retrieved correctly without incorrect unit conversion being applied

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
