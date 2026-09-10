# travel-guide-builder

把「参考模板 + 目的地 + 天数 + 预算档次」变成一份**能直接照着出行**的多 sheet 行程表 `.xlsx`。

```
SKILL.md                       主流程（含开工前必须锁死的 6 个决策点）
references/column-rules.md     A-I 九列逐格填充规则
references/scraping-playbook.md  携程 / 神州 / 小红书抓价实战手册（含已验证失败的路径）
scripts/build_guide_xlsx.py    读 content.json → 5 sheet xlsx，自带回读校验
scripts/make_xhs_index.py      小红书素材包 INDEX.md 生成器
examples/guizhou_content_sample.json   贵州 7 天 6 晚完整实例
```

## 产出的 5 个 sheet

| sheet | 说明 |
|---|---|
| 全部行程 | 逐日 × 九列：日期 / 大交通 / 简要行程 / 详细行程 / 机位 / 餐饮 / 酒店 / 备注（穿衣+避坑）/ 注意事项 |
| 人均预算 | 分项列价 + 平日 vs 节假日对照 + 涨幅，附口径与时效说明 |
| 费用明细 | **只写模板骨架，数值留空** |
| 物品清单 | 从用户模板 1:1 复制，不擅自增删 |
| 景点地图 | 总路线 / 大景点 / 城市景点三层，带直达搜索链接 |

## 快速开始

```bash
pip install openpyxl
python scripts/build_guide_xlsx.py examples/guizhou_content_sample.json 贵州攻略.xlsx
```

## 硬约束

- 攻略**必须给出人均总预算**，并注明计价口径
- 用户说「费用明细只保留模板」时，数值一律留空
- 租车若指定了保险档位，保险费**必须单独计入**总预算
- 价格必须标来源与抓取日期，抓不到的如实说，不用臆测数字冒充实时价
- **生成后必须回读校验**——大段中文极易产生乱码，写入时看不出来
