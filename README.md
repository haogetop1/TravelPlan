# TravelPlan
Use AI tools to generate road books and travel guides — extremely detailed. Data comes from Xiaohongshu (RED), Trip.com (Ctrip), and China Auto Rental (Shenzhou Zuche). Output files: Excel workbook, illustrated road-book HTML (single-file export too) and two PPT decks. Scraping scripts are pre-built / embedded.

> **🆕 Latest (2026-09-12)** — **PDF is no longer generated automatically**: deliver the HTML and let
> the user print "Save as PDF" themselves (A4 / portrait / 1 page per sheet / ☑ background graphics),
> which removes a whole class of renderer drift. Maps now follow an explicit **four-tier fallback**
> (① Xiaohongshu spot guide map, verified → ② Tianditu → ③ Amap static-map API → ④ other sources),
> with a new `map_sources.py` that keeps provenance and captions in sync. Tier ③ needs **your own
> Amap Web Service key** — see the section below.
> See [CHANGELOG.md](CHANGELOG.md) for the root-cause details.

---

## 📦 What's in this repo

| Path | What it is |
|---|---|
| [`travel-guide-builder/`](travel-guide-builder/) | A **WorkBuddy / CodeBuddy Agent Skill** that turns a reference template into a multi-sheet itinerary `.xlsx` **and** an illustrated road book (HTML + PPT). The PDF is **not** produced by the skill — the user prints it from the HTML. |
| [`xhs-humanized-collect/`](xhs-humanized-collect/) | A **WorkBuddy / CodeBuddy Agent Skill** for human-paced Xiaohongshu (RED) collection — persistent login, randomized timing, and a hard-won pitfall list (including one that can destroy real browser data). |
| `travel-guide-builder/scripts/` | Runnable Python scripts: xlsx builder, road-book renderer, PPT builder, Xiaohongshu asset tooling, **map-source registry** (`map_sources.py`). **No PDF script ships here** — it was removed on purpose; the user prints the HTML via "Save as PDF". |
| `travel-guide-builder/references/` | The nine-column filling rules, a real-world scraping playbook, and the road-book chapter. |
| `travel-guide-builder/examples/` | A complete working sample: Guizhou 7D6N self-drive (10.1–10.7). |
| [`CHANGELOG.md`](CHANGELOG.md) | What changed, and — more usefully — *why*. |

## 🚀 Install as an Agent Skill

```bash
# user-level (available in all projects)
cp -r travel-guide-builder ~/.workbuddy/skills/
cp -r xhs-humanized-collect ~/.workbuddy/skills/

# or project-level
cp -r travel-guide-builder xhs-humanized-collect <your-project>/.workbuddy/skills/
```

Then just ask your agent for e.g. *"做一份贵州 7 天 6 晚自驾攻略，参考我的模板表格"* — it will pick the skill up automatically.
`travel-guide-builder` depends on `xhs-humanized-collect` for Xiaohongshu sourcing, so **install both**.

## 🛠 Use the scripts directly

```bash
pip install -r requirements.txt

# 1) build the itinerary workbook from a content.json
python travel-guide-builder/scripts/build_guide_xlsx.py \
    travel-guide-builder/examples/guizhou_content_sample.json \
    out.xlsx

# 2) generate an index for scraped Xiaohongshu assets
python travel-guide-builder/scripts/make_xhs_index.py --dir xhs_data
```

`build_guide_xlsx.py` writes five sheets and then **reads the file back** to check for empty
cells and mojibake — LLM-generated long Chinese text does corrupt silently, so never skip that step.

Copy `examples/guizhou_content_sample.json` as your starting `content.json` and replace the
content; `budget` / `fee_template` / `packing` / `maps` are all optional.

## 🗝️ Set up: your own Amap (Gaode) Web Service key

Maps in the road book are resolved by priority — **① Xiaohongshu spot guide map → ② Tianditu
→ ③ Amap static-map API → ④ other fallback**. **Only tier ③ needs a key**, so everything still
works without one; the key just buys you marker pins, zero UI chrome and `scale=2` sharpness.
Tier ① is preferred because a creator's hand-drawn guide carries route order, viewpoints and
mileages that no map API gives you — but it must be **verified** to actually depict that spot
(see `references/scraping-playbook.md`, section 六).

**This repo ships no key. Get your own (free tier):**

1. Register / sign in at **<https://console.amap.com>** (Amap Open Platform 高德开放平台).
2. **应用管理 → 我的应用 → 创建新应用** — any name, e.g. `AI-TravelPlan`.
3. Open the app → **添加Key** → set **服务平台 = `Web服务` (Web Service)**.
   ⚠️ Do **not** pick `Web端(JS API)`, iOS or Android — those key types fail on
   `/v3/staticmap` with a useless `UNKNOWN_ERROR 20003`. This is the #1 setup mistake.
4. Copy the 32-character key string.
5. Binding / quota: leaving it unbound is fine for personal use (that's what "no IP restriction"
   means in the console); set an IP whitelist only if you share it.
6. Hand it to your script through an **environment variable** — never hard-code it:

   ```bash
   export AMAP_WEB_KEY=<your-key>
   ```

   Write collectors to read `AMAP_WEB_KEY` and fail loudly when it is missing, so the key never
   ends up in a tracked file.

**Two API gotchas worth knowing before you debug** (details in the playbook): `size` uses an
asterisk (`size=1024*600`, not `1024x600`), and a marker `label` accepts **one character only**
(`宁` / `A` work, `西宁市区` errors). Both surface as the same unhelpful `20003`.
Calls are also QPS-limited — space them ≥3s; if everything suddenly fails, it is throttling,
not your parameters: wait 2–3 minutes and retry **one minimal request** to confirm.

## 📊 Where the data comes from

| Source | Status | Notes |
|---|---|---|
| Xiaohongshu (RED) | ✅ works | Needs one QR-code login; reuse the `xhs-humanized-collect` skill. |
| Ctrip flights | ✅ works | Must launch native Chrome + connect over CDP; plain Playwright gets `whaleguard block`. |
| Ctrip hotels | ⚠️ flaky | The city dropdown's `cityId` is hard to click through — have a fallback ready. |
| Shenzhou Zuche (car rental) | ❌ not scrapable | All web endpoints are dead/empty shells. Use the published rate card instead and label it as such. |

See [`references/scraping-playbook.md`](travel-guide-builder/references/scraping-playbook.md) for the
full record — including the five approaches that **don't** work, so you don't burn tokens rediscovering them.

## 🔒 Security

**No tokens, cookies or personal data belong in this repo.** Before pushing:

- Credentials are passed via env vars / credential helpers, never written into tracked files.
- `.gitignore` blocks browser profiles, login-state databases, scraped image folders, and common secret file patterns.
- If a secret ever lands in a commit, rotate it first — deleting the commit is not enough.

## 📄 License

MIT — see [LICENSE](LICENSE).
