# TravelPlan
Use AI tools to generate road books and travel guides — extremely detailed. Data comes from Xiaohongshu (RED), Trip.com (Ctrip), and China Auto Rental (Shenzhou Zuche). Output files are available in PDF, HTML, Excel, and PPT formats. Scraping scripts are pre-built / embedded.

---

## 📦 What's in this repo

| Path | What it is |
|---|---|
| [`travel-guide-builder/`](travel-guide-builder/) | A **WorkBuddy / CodeBuddy Agent Skill** that turns a reference template into a multi-sheet itinerary `.xlsx` — with a per-person budget, a blank expense sheet, a 1:1 packing list, and a map index. |
| `travel-guide-builder/scripts/` | Two runnable Python scripts (xlsx builder, Xiaohongshu asset indexer). |
| `travel-guide-builder/references/` | The nine-column filling rules + a real-world scraping playbook. |
| `travel-guide-builder/examples/` | A complete working sample: Guizhou 7D6N self-drive (10.1–10.7). |

## 🚀 Install as an Agent Skill

```bash
# user-level (available in all projects)
cp -r travel-guide-builder ~/.workbuddy/skills/

# or project-level
cp -r travel-guide-builder <your-project>/.workbuddy/skills/
```

Then just ask your agent for e.g. *"做一份贵州 7 天 6 晚自驾攻略，参考我的模板表格"* — it will pick the skill up automatically.

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
