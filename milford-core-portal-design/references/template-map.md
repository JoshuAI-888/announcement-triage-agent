# Template map

- `assets/templates/login.html`: authenticated entry screen with work email, password and Microsoft SSO patterns.
- `assets/templates/portal.html`: complete responsive internal portal with ten modules, role-specific portfolio analytics, required PM commentary, relationship mapping, and working hash navigation.
- `assets/styles/milford-system.css`: master tokens, typography, buttons, fields, tables, badges, metrics and shared utilities.
- `assets/styles/portal.css`: authenticated shell, sidebar, top bar, module grids, login layout and responsive behavior.
- `assets/styles/analytics.css`: role tabs, chart surfaces, commentary workflow, scenario matrix and relationship-map layouts.
- `assets/analytics.js`: local Chart.js configurations, relationship-network renderer and commentary interactions.
- `assets/vendor/chartjs/chart.umd.min.js`: Chart.js 4.5.0 reused from the Milford design data room.

Run from disk by opening either HTML file. Scaffold a copy with:

```bash
python3 scripts/scaffold.py portal /absolute/path/to/destination
```

Use `login` instead of `portal` for the login template.
The scaffold prints the selected file path under the generated `templates/` directory; keep the sibling asset directories together so all local links remain portable.
