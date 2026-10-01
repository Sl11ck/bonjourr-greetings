# Bonjourr greetings

Greetings for the [Bonjourr](https://bonjourr.fr) start page that change with the time of day and the weekday, each with an animated Microsoft Fluent emoji. Done in pure CSS, since Bonjourr's custom CSS can't run JavaScript.

- 39 greetings, chosen by the time of day, the weekday and the minute the tab was opened. See [PREVIEW.md](PREVIEW.md).
- A tab keeps its greeting while it stays open. Refresh, or open a new tab, to get a new one.
- Bonjourr's layout is unchanged: the greeting is drawn exactly where Bonjourr's own greeting sits.
- The emoji are pre-sized for each screen scale (100% to 250%), so their edges stay smooth in Firefox.
- If something it relies on is missing, it steps aside and Bonjourr's normal greeting shows. That covers an analog clock, a 12-hour clock, a non-English interface, hidden widgets, or the stylesheet failing to load.

## Setup (once)

1. **Create the repository.** On GitHub, create a **public** repository named `bonjourr-greetings` and upload everything in this folder, including the `.github` folder. You can drag it in on the web, or push with git (`git init -b main`, `git add .`, `git commit -m init`, `git remote add origin https://github.com/Sl11ck/bonjourr-greetings.git`, `git push -u origin main`).
   - If `.github` doesn't upload, choose *Add file → Create new file*, name it `.github/workflows/build.yml`, and paste in that file's contents.
2. **Wait for the build.** Open the *Actions* tab and wait for **Build** to get a green tick. The first run takes a few minutes because it makes the emoji.
   - If the run fails at "Commit the build", go to *Settings → Actions → General → Workflow permissions*, choose *Read and write*, then *Re-run all jobs*.
3. **Copy the import line.** Open that run. Its summary shows a line like this:
   `@import url(https://cdn.jsdelivr.net/gh/Sl11ck/bonjourr-greetings@<commit>/greetings.css);`
4. **Set up the probe clock.** Bonjourr needs two world clocks, both named: your real one first, then one called `probe`. Run `worldclock-command.js` once in the Bonjourr tab's console (F12 → Console) to set this up.
5. **Paste the custom CSS.** In Bonjourr, go to *Settings → Custom style* and paste the following, using the import line from step 3 as the first line:

```css
@import url(https://cdn.jsdelivr.net/gh/Sl11ck/bonjourr-greetings@COMMIT/greetings.css);
:root{--name:"Isaac"}
#background-color{background-color:#1a1b26!important;background-image:linear-gradient(0deg,#1a1b26 0%,#24283b 100%)!important}
.clock-region,[data-index="1"]{display:none}
```

Your name stays in Bonjourr and never goes into the public repository. The last line keeps the probe clock hidden even if the stylesheet can't load.

## Changing greetings

Edit `src/config.json`; the pencil icon on GitHub works fine. After you commit, the **Build** run checks the config, rebuilds, and prints a new import line. Swap that line into Bonjourr.

Until you do, Bonjourr keeps the version you already have. Each link is pinned to one exact build, which is why browsers can cache it forever and new tabs never flicker.

- `greetings`: an id, the text (`{name}` becomes your name), and an emoji.
- `periods`: hour ranges covering 0–24. Each has 10 slots, picked by the last digit of the minute the tab was opened. Repeat an id to make that greeting more likely.
- `day_overrides`: replace some slots on one weekday within an hour range, e.g. "Happy Monday".
- `static_instead_of_animated`: list emoji here, e.g. `["🫡", "🫣"]`, to use the static 3D design instead of the animation.
- `emoji_scales` and `emoji_quality`: emoji file sizes and AVIF quality. The defaults are fine.

If the config has a mistake, such as an unknown id or a gap in the hours, the run stops with a plain message and nothing changes.

To add a new emoji, give it a source in `src/build.py`:

- `MS_FOLDER` for an animated one, using its folder name in [microsoft/fluentui-emoji-animated](https://github.com/microsoft/fluentui-emoji-animated/tree/main/assets);
- `EP_SLUG` for the static 3D Fluent design on Emojipedia.

## Build locally (optional)

```sh
pip install -r src/requirements.txt
python src/build.py          # rebuild greetings.css + PREVIEW.md, encode any missing emoji
python src/build.py --force  # re-download and re-encode every emoji
```

## How it works

Bonjourr's custom CSS can't read the time. A second, hidden world clock (the "probe") puts the time and weekday on the page as text, and the CSS reads it from there.

1. A tiny generated font gives each character an exact width. The box then measures 4px per hour, 4px per weekday code and 4px per minute digit; the minute digit is set vertically, so it becomes a height.
2. Container queries on those sizes pick the period, apply any weekday overrides, and choose the slot.
3. The greeting is drawn in an anchored `::after` placed exactly over Bonjourr's own greeting.
4. A `content` transition lasting about 30 years keeps the first value, so the greeting never changes while the tab is open.

## Emoji and licences

| Emoji | Source | How |
|---|---|---|
| 24 animated | [Microsoft Fluent Emoji animated](https://github.com/microsoft/fluentui-emoji-animated) (MIT) | Resized with Lanczos to each screen scale, stored as animated AVIF in `emoji/` |
| 🫡 🫣 | Microsoft Teams animations on Emojipedia | Linked, not re-hosted, because there's no open licence. Firefox draws these a little softer. |
| 📣 🫖 🍕 🧳 📑 💼 🥡 🍜 📆 ✨ 🫩 🫪 | Microsoft 3D Fluent (Windows 11 26H2) on Emojipedia | Linked, not re-hosted. Static 512px images, which browsers shrink cleanly. |

Code: MIT. Microsoft emoji: © Microsoft, MIT (see `emoji/LICENSE-microsoft-fluentui-emoji.txt`).
