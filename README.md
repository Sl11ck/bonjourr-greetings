# Bonjourr greetings

Greetings for the [Bonjourr](https://bonjourr.fr) start page that change with the time of day and the weekday, each with a Microsoft Fluent emoji (animated where possible). Done in pure CSS, since Bonjourr's custom CSS can't run JavaScript.

- Every greeting lives in one table: [`greetings.csv`](greetings.csv). It sets when each greeting can show and how likely it is.
- The build finds each emoji's image by itself, following the precedence you set.
- A tab keeps its greeting while it stays open. Refresh, or open a new tab, to get a new one.
- Bonjourr's layout is unchanged: the greeting is drawn exactly where Bonjourr's own greeting sits.
- Re-hosted emoji are pre-sized for each screen scale (100% to 250%), so their edges stay smooth in Firefox.
- If something it relies on is missing, it steps aside and Bonjourr's normal greeting shows. That covers an analog clock, a 12-hour clock, a non-English interface, hidden widgets, or the stylesheet failing to load.
- [PREVIEW.md](PREVIEW.md) shows every greeting, its emoji, and its chances at each time.

## Editing greetings

Edit `greetings.csv`. The pencil icon on GitHub works, as does any text editor or spreadsheet app (save as **CSV UTF-8**). Commit, and the **Build** run checks the table, finds any new emoji, rebuilds, and prints a new import line. Swap that line into Bonjourr.

One row = one greeting at certain times:

| Column | What it means | Examples |
|---|---|---|
| `greeting` | The text. `{name}` becomes your name. Wrap it in quotes if it contains a comma. Rows starting with `#` are comments. | `"Good morning, {name}"` |
| `emoji` | Optional. One emoji; the build finds its image. | `🥱` |
| `days` | Which days. Ranges wrap around the week. | `*`, `Mon`, `Mon-Fri`, `weekdays`, `weekend`, `"Sat,Sun"` |
| `hours` | Which hours, start to end; the end hour itself is not included. Ranges can wrap past midnight, and you can list several. | `*`, `05-12`, `21-05`, `"05-12 17-21"` |
| `weight` | How likely, compared with the other greetings allowed at that hour. `2` is twice as likely as `1`; `0` turns a row off; blank counts as `1`. | `2`, `0.5` |
| `style` | Optional. Overrides the emoji style order for this row. | `3d`, `2d`, `system`, `"3d 2d"` |

- **Chances:** for every weekday and hour, the weights of all the rows that apply are turned into 60 slots, one per minute. A tab shows the slot for the minute it was opened. So a weight that makes up 1/4 of an hour's total shows 15 minutes in every 60.
- **Same greeting, different chances:** add one row per time block, as `Coffee and Crunch time?` does.
- **Ranges past midnight:** a range like `21-02` stays with the night it starts on. `Fri 21-02` covers Friday 21:00 to Saturday 02:00.
- **Mistakes stop the run:** an unknown day, an hour nobody covers, or a missing column stops the run with a plain message, and nothing changes. A weight too small to ever win a minute gives a warning.

## Emoji: styles and sources

Set in `src/config.json`:

```json
"emoji_styles": ["3d-animated", "3d", "2d", "system"],
"emoji_sources": {
  "3d-animated": ["microsoft", "emojipedia"],
  "3d":          ["emojipedia", "microsoft"],
  "2d":          ["emojipedia", "microsoft"]
}
```

- **`emoji_styles`** is the order styles are tried in. Each emoji gets the first style that has an image. `system` means the plain emoji character in your system font (Segoe UI Emoji on Windows), and it always works.
- **`emoji_sources`** is, for each style, the order in which sources are asked:

| Source | 3d-animated | 3d | 2d | How it's used |
|---|---|---|---|---|
| `microsoft` | [fluentui-emoji-animated](https://github.com/microsoft/fluentui-emoji-animated) | [fluentui-emoji](https://github.com/microsoft/fluentui-emoji) 3D | fluentui-emoji Color (SVG) | MIT-licensed, so it's downloaded, resized to every screen scale and committed to `emoji/`. Always smooth. |
| `emojipedia` | Microsoft Teams animations | Microsoft 3D Fluent (newest Windows 11 release) | Microsoft (Windows 11 Segoe UI Emoji) | Newest designs, linked to (no open licence, so not re-hosted). Firefox draws linked animations a little softer. |

- **Lookup results are saved** in `src/emoji-lock.json`, so builds are repeatable and fast.
- **Precedence changes re-check everything:** changing `emoji_styles` or `emoji_sources` makes the next build look every emoji up again.
- **To check for newer designs:** go to *Actions → Build → Run workflow*, tick *Look up every emoji again*, and run it.

## Setup (once)

1. **Create the repository and upload this folder.** Make a **public** repository (e.g. `bonjourr-greetings`) and push this folder, including `.github`.
2. **Wait for the build.** Open the *Actions* tab and wait for **Build** to get a green tick.
   - If it fails at "Commit the build", go to *Settings → Actions → General → Workflow permissions*, choose *Read and write*, then re-run it.
3. **Set up the probe clock.** Bonjourr needs two named world clocks: your real one first, then `probe`. Run `worldclock-command.js` once in the Bonjourr tab's console (F12 → Console) to set this up.
4. **Paste the custom CSS.** In Bonjourr, go to *Settings → Custom style* and paste the following, with the first line replaced by the import line from the run summary:

```css
@import url(https://cdn.jsdelivr.net/gh/Sl11ck/bonjourr-greetings@COMMIT/greetings.css);
:root{--name:"Isaac"}
#background-color{background-color:#1a1b26!important;background-image:linear-gradient(0deg,#1a1b26 0%,#24283b 100%)!important}
.clock-region,[data-index="1"]{display:none}
```

- **Your name stays private:** it lives only in Bonjourr, never in the public repository.
- **Fallback:** the last line keeps the probe clock hidden even if the stylesheet can't load.
- **Why the link is pinned:** each import line points at one exact build, so browsers cache it forever and new tabs never flicker. Until you swap in a new line, Bonjourr keeps the version it has.

## Build locally (optional)

```sh
pip install -r src/requirements.txt
python src/build.py              # normal build
python src/build.py --refresh    # look up every emoji again
python src/build.py --force      # also re-download and re-encode every image
```

## How it works

Bonjourr's custom CSS can't read the time. A second, hidden world clock (the "probe") puts the time and weekday on the page as text, and the CSS reads it from there.

1. A tiny generated font gives each character an exact width. The box then measures 1px per hour and 1px per weekday code; the minute is set vertically, so it becomes a height of 1px per minute.
2. Container queries on those sizes pick the weekday and hour, then the minute's slot.
3. The greeting is drawn in an anchored `::after` placed exactly over Bonjourr's own greeting.
4. A `content` transition lasting about 30 years keeps the first value, so the greeting never changes while the tab is open.

## Licences

- **Code:** MIT.
- **Images in `emoji/`:** © Microsoft, MIT (see `emoji/LICENSE-microsoft-fluentui-emoji.txt`).
- **Emojipedia images:** linked to, not part of this repository.
