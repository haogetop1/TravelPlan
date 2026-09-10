# TravelPlan
Use AI tools to generate road books and travel guides — extremely detailed. Data comes from Xiaohongshu (RED), Trip.com (Ctrip), and China Auto Rental (Shenzhou Zuche). Output files are available in PDF, HTML, Excel, and PPT formats. Scraping scripts are pre-built / embedded.

> **🆕 Latest (2026-09-10)** — added the illustrated road-book pipeline (HTML / PDF / single-file),
> a 16:9 poster-style PPT, switched map sourcing to real Xiaohongshu maps (Amap is now only a fallback),
> fixed the PDF blank-page bug, and added `xhs-humanized-collect` as a sibling skill.
> See [CHANGELOG.md](CHANGELOG.md) for the root-cause details.

---

## 📦 What's in this repo

| Path | What it is |
|---|---|
| [`travel-guide-builder/`](travel-guide-builder/) | A **WorkBuddy / CodeBuddy Agent Skill** that turns a reference template into a multi-sheet itinerary `.xlsx` **and** a print-ready illustrated road book (HTML / PDF / PPT). |
| [`xhs-humanized-collect/`](xhs-humanized-collect/) | A **WorkBuddy / CodeBuddy Agent Skill** for human-paced Xiaohongshu (RED) collection — persistent login, randomized timing, and a hard-won pitfall list (including one that can destroy real browser data). |
| `travel-guide-builder/scripts/` | Runnable Python scripts: xlsx builder, road-book renderer, PDF printer, PPT builder, Xiaohongshu asset tooling. |
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
