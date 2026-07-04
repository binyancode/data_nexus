# Data Nexus — 工作交接备忘（HANDOFF）

> 拷贝到新工作区后先读这份。它记录了 Nexus 这套 PPT/文档的**文件清单、构建流程、踩坑点、幻灯片结构、写作约定和当前状态**，让你（或另一个 AI）能无缝接着干。

---

## 1. 要一起拷贝的文件清单

| 路径 | 作用 | 必需 |
|---|---|---|
| `doc/design/nexus_platform_ppt.html` | **唯一 deck 源**（19 页，dark theme `#141E30`），每页一个 `div.slide`（h2 标题 + `.phase-subtitle` + `<svg>`） | ✅ 核心 |
| `doc/design/cover_bg.html` | 封面背景 SVG（知识图谱节点/发光/网格/HUD），单独渲染成 `cover_bg.png` | ✅ |
| `doc/design/svg_nexus/` | 渲染出的 PNG：`slide_02.png … slide_19.png` + `cover_bg.png` | ✅ 构建产物 |
| `test/gen_nexus_pptx.py` | **构建脚本**：读 HTML → 拼 PNG → 生成 `doc/Data Nexus 平台设计.pptx` + 讲稿 NOTES | ✅ 核心 |
| `doc/Data Nexus 平台设计.pptx` | 最终 PPT（19 页） | 产物 |
| `doc/design/data_nexus_design.md` | **实现级设计文档**（照它写代码） | ✅ |
| `tools/html_to_pptx.py` | 被 `gen_nexus_pptx.py` import，提供 `extract_slides(html)` 解析器 | ✅ 依赖 |

> 注意：`gen_nexus_pptx.py` 里 `BASE` 和 `sys.path` 用的是**当前工作区绝对路径**。拷到新工作区后，**改 `gen_nexus_pptx.py` 顶部的 `BASE`** 为新路径即可（其余相对路径自动跟随）。

---

## 2. 构建环境与命令

- **Python**：全局 `C:\Program Files\Python311\python.exe`（**不是** `.venv`）。依赖：`python -m pip install python-pptx`（+ `bs4 lxml` 供 `html_to_pptx`）。
  - ⚠️ `install_python_packages` 工具可能装到别的解释器；导入失败就在终端 `python -m pip install <pkg>`。
- **构建 PPT**（改完 HTML/PNG/NOTES 后）：
  ```powershell
  & "C:\Program Files\Python311\python.exe" test\gen_nexus_pptx.py
  # 输出应打印：slides: 19
  ```
- **PowerPoint 不会自动刷新** —— 每次重建后必须**关闭再重新打开** pptx 才看得到更新（这点反复踩坑）。

---

## 3. SVG → PNG 渲染流程（关键，务必照做）

**不要**把 SVG 直接嵌进 pptx（PowerPoint 缩放不可靠）。流程是 SVG → PNG → `add_picture`。

1. 在浏览器打开 deck HTML：`open_browser_page(forceNew:true, url:"file:///.../nexus_platform_ppt.html")`。
   - 页面在轮次之间会关闭 → 每次渲染前重新 `open_browser_page(forceNew:true)`。
2. 用 `run_playwright_code` 遍历页面 DOM 里的 `<svg>` 截图（**沙箱里 `require`/`fs` 未定义，只能用 page DOM + `screenshot({path})`**）：
   ```js
   const dir = 'c:/.../doc/design/svg_nexus';
   const svgs = await page.$$('svg');
   for (let i = 0; i < svgs.length; i++) {
     await svgs[i].evaluate(e => { e.setAttribute('width','3200'); e.setAttribute('height','1436');
       e.style.width='3200px'; e.style.height='1436px'; e.style.background='#141E30'; });
     const n = String(i + 2).padStart(2, '0');   // slide_02 起（封面无 svg）
     await svgs[i].screenshot({ path: `${dir}/slide_${n}.png` });
   }
   ```
   - 内容页 viewBox = `0 0 1600 718`（比例 2.228，对应 12.7in×5.7in 放置框）。3200×1436 = 高清。
   - 封面背景单独渲染 `cover_bg.html` 的 `#bg` svg → `cover_bg.png`（2560×1440）。
3. 渲染后 `view_image` 抽查改动页确认无误。

---

## 4. 幻灯片结构（19 页，页码=DOM 顺序）

| # | 标题（h2） | 备注 |
|---|---|---|
| 1 | 封面 Data Nexus | 用 `cover_bg.png` 满铺 |
| 2 | 二、痛点 → 目标 | |
| 3 | 三、系统蓝图 | 三层：知识层/运行引擎/能力层 |
| 4 | 四、Concept | |
| 5 | 五、Binding | |
| 6 | 六、Resolver（统一接口 capabilities/plan/resolve） | |
| 7 | 七、Resolver 5 类清单 | |
| 8 | 八、自动生成 Concept/Binding | describe/抽样 |
| 9 | 九、SQG 语义查询图 | 六算子 SELECT/FILTER/AGGREGATE/TRAVERSE/ASK★/ACT★ |
| 10 | 十、执行引擎总览 | 编译器→调度器→协调器→生成器 |
| 11 | 十、执行细节① DAG→调度器执行计划 | ⚠️ h2 中文数字与页码有偏移，见下 |
| 12 | 十一、执行细节② 协调器分波并行+回填+裁决 | |
| 13 | 十二、真实报文：三段 JSON（SQG→plan→result） | 含 `as_user`/`user_scoped` 权限透传 |
| 14 | 十三、分层架构 L1–L5 + 治理内生 | |
| 15 | 十四、端到端例子：走一遍全流程 | 横向四段引擎故事板（已对齐执行细节①②） |
| 16 | 十五、落地路径 P0–P4 | |
| 17 | 十六、价值 | |
| 18 | 十七、三个战略定位 A/B/C | |
| 19 | 十八、后续可深挖四方向 | |

> ⚠️ **h2 中文序号 ≠ 物理页码**：插入执行细节两页(11、12)和 JSON 页(13)后，`执行引擎总览`是第10页但 h2 仍是「十」，其后 h2 序号比页码小 2（如第14页 h2=「十三」）。改动时以**物理 DOM 顺序**为准，NOTES dict 的 key 也是物理页码。

---

## 5. 增删幻灯片时的固定动作（**极易漏**）

插入或删除任何一页后，必须**四步全做**：
1. 在 HTML 相应位置插入/删除 `div.slide`。
2. **重排后续所有页的 h2 中文序号**（多用 `multi_replace_string_in_file`）。
3. **重渲染全部 PNG**（`slide_02..slide_NN.png`）——不能只渲染改动页，因为后面页号全变了。
4. **改 `gen_nexus_pptx.py` 的 NOTES dict**：新增/顺移 key，并修正讲稿里所有「见第 N 页」交叉引用。

---

## 6. `gen_nexus_pptx.py` 结构

- `BASE` = 工作区根（**换机器要改**）；`sys.path.insert(tools)` 后 `import html_to_pptx as h`。
- `h.extract_slides(HTML)` 返回每页 dict：`is_title_slide / title / subtitle / index`。
- 幻灯片 13.333×7.5in，`slide_layouts[6]` 空白；深色背景 `#141E30`。
- 封面：`cover_bg.png` 满铺 + 白色标题 54pt + 蓝副标题；内容页：标题 24pt + 副标题 13pt + `add_picture(slide_XX.png, width=Inches(12.7))`（**只给 width，保持比例**）。
- `NOTES = {页码: "多行讲稿"}`，末尾 `slide.notes_slide.notes_text_frame.text = NOTES[i]` 写入演讲者备注。

---

## 7. 写作/设计约定（用户反复强调）

- **大白话，不要术语堆砌**：能用中文常识词就别造词。避免"抽象晦涩"。
- **销售数据例子贯穿全篇**：华东/上季度/毛利、`fact_sales`、`dim_region`、大客户减采、原材料涨价、派复盘工单。**禁止**厨师/餐厅之类比喻。
- **逻辑连贯、无断层**：每页承接上一页；相关页之间用「承接第N页」「见第N页」串起来。
- **术语首次出现要展开**：如「SQG（Semantic Query Graph，语义查询图）」。
- **改完必须 view_image 抽查**渲染效果再收工。

---

## 8. 技术踩坑（已验证）

- **SVG 行首空格会被吃掉**（Chromium 截图渲染），`xml:space="preserve"` 不可靠 → JSON 缩进**必须用绝对 x 坐标按层级偏移**（每级 +14px），不要靠前导空格。见第13页 JSON 三列实现。
- **Python 源里的中文弯引号 " "** 会导致 SyntaxError（被规范化成 ASCII " 提前结束字符串）→ 字符串内部一律用**角括号「」『』**，绝不用 ASCII/弯双引号。
- **PowerPoint 批注**：python-pptx 无 API，手工注入现代批注需 `pc:sldMkLst` 锚点否则文件损坏 → **已放弃批注，全用演讲者备注**（`notes_text_frame`），永远可见、零损坏。
- **cairosvg 在 Windows 不可用**（缺 libcairo）→ 只能走无头浏览器截图。
- **PowerShell**：`[Content_Types].xml` 要 `-LiteralPath`（方括号是通配符）；非 ascii 路径「百济神州」正常。
- **中文路径 print** 可能 cp1252 崩 → 打印 ascii 状态即可。

---

## 9. 核心概念模型（一句话版，别改跑偏）

- **Concept 概念** = 业务名词（销售额=指标、地区=维度、客户=实体）；字段 id/kind/semantics/type/bindings/policy/provenance。
- **Binding 绑定** = 概念→物理映射（销售额=`SUM(fact_sales.amount)`）；换库只改 Binding；一概念可绑多源=跨源融合。
- **Resolver 解析器** = 数据源/Agent/动作的**统一接口**：`capabilities()` 报能力清单、`plan()` 评估+编译、`resolve()` 干活；另有 `describe()`/`sample()` 供自动建本体。5 类：SQL库/向量库/Data Agent★/REST API/动作★。
- **SQG 语义查询图** = 一张 DAG，节点=算子(SELECT/FILTER/AGGREGATE/TRAVERSE/ASK★/ACT★)、边=依赖。
- **运行引擎**：提问 → **编译器**(NL→SQG) → **调度器 Dispatcher**(选源竞标+用 Binding 编译成真实调用+透传 `as_user`) → **协调器 Coordinator**(拓扑分波并行+回填占位符+合并+按信任分裁决) → **生成器 Generator**(答案+血缘+回执)。
- **权限透传**：Resolver 若 `capabilities.user_scoped=true`，调度器给该节点打 `user_scoped`，执行时把当前用户 `as_user` 传给它，由源头做行级安全过滤（应用层不拼 where）。
- **组件命名（已定稿）**：调度器=Dispatcher、协调器=Coordinator、生成器=Generator、能力清单=capabilities、结构探测=describe、抽样=sample。

（完整数据结构/接口/JSON 样例见 `doc/design/data_nexus_design.md`。）

---

## 10. 当前状态 & 可能的下一步

- **状态**：deck 19 页完成并渲染；`data_nexus_design.md` 实现文档完成；端到端页已重画对齐执行细节①②；JSON 页三段(SQG→plan→result)含权限透传、缩进已修好。
- **落地路线**：P0 骨架(本体+Resolver 接口+SQG 编译器) → P1 联邦(向量库+裁决) → P2 智能体源★ → P3 行动(ACT) → P4 自动建本体。P0 就把三大接口定死。
- **复用现有代码**：`Orchestrator`→Dispatcher、`ToolProvider`→Resolver、`ToolManifest`→Capabilities、`FrontChannel`→交互/流式、Renderer→L5、`credential.py`→连接凭据、`api_definitions/api_permissions`→治理、`prompt_templates`→Generator 模板、`copilot_runs/steps`→血缘。
- **可能的下一步**：把 `data_nexus_design.md` 的 P0 接口落成 Python 骨架（Concept/Binding/Resolver 抽象类 + SQG dataclass + 一个 SQL Resolver + 极简编译器/调度器/协调器），验证「一个 SQL 源能问答」。
