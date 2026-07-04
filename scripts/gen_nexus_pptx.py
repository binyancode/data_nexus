"""Build the Data Nexus PPTX (18 slides): PNG images + example-driven speaker notes."""
import sys
from pathlib import Path

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import html_to_pptx as h  # noqa: E402

DOC = BASE.parent / "doc"
HTML = DOC / "nexus_platform_ppt.html"
PNG_DIR = DOC / "svg_nexus"
OUT = DOC / "Data Nexus 平台设计.pptx"

BG = RGBColor(0x14, 0x1E, 0x30)
TEXT = RGBColor(0xEA, 0xF0, 0xF6)
MUTED = RGBColor(0xB0, 0xBE, 0xC5)

slides_data = h.extract_slides(HTML)
prs = Presentation()
prs.slide_width = Inches(13.333)
prs.slide_height = Inches(7.5)
blank = prs.slide_layouts[6]


def textbox(slide, l, t, w, ht, text, size, color, bold=False, align=PP_ALIGN.LEFT):
    tb = slide.shapes.add_textbox(l, t, w, ht)
    tf = tb.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = text
    p.alignment = align
    p.font.size = Pt(size)
    p.font.color.rgb = color
    p.font.bold = bold
    return tb


for sd in slides_data:
    slide = prs.slides.add_slide(blank)
    bg = slide.background.fill
    bg.solid()
    bg.fore_color.rgb = BG

    if sd["is_title_slide"]:
        cover = PNG_DIR / "cover_bg.png"
        if cover.exists():
            slide.shapes.add_picture(str(cover), 0, 0,
                                     width=Inches(13.333), height=Inches(7.5))
        textbox(slide, Inches(1), Inches(2.6), Inches(11.3), Inches(1.4),
                sd["title"], 54, RGBColor(0xEA, 0xF2, 0xFF), bold=True, align=PP_ALIGN.CENTER)
        if sd["subtitle"]:
            textbox(slide, Inches(1.4), Inches(4.15), Inches(10.5), Inches(1.2),
                    sd["subtitle"], 18, RGBColor(0x9F, 0xC0, 0xE8), align=PP_ALIGN.CENTER)
    else:
        textbox(slide, Inches(0.55), Inches(0.28), Inches(12.2), Inches(0.7),
                sd["title"], 24, TEXT, bold=True)
        if sd["subtitle"]:
            textbox(slide, Inches(0.55), Inches(0.92), Inches(12.2), Inches(0.5),
                    sd["subtitle"], 13, MUTED)
        png = PNG_DIR / f"slide_{sd['index']:02d}.png"
        if png.exists():
            w = Inches(12.7)
            left = Inches((13.333 - 12.7) / 2)
            slide.shapes.add_picture(str(png), left, Inches(1.5), width=w)

    textbox(slide, Inches(11.7), Inches(7.02), Inches(1.4), Inches(0.35),
            f"{sd['index']:02d} / {len(slides_data):02d}", 10, MUTED, align=PP_ALIGN.RIGHT)


NOTES = {
    1: (
        "【第1页 · 封面】\n"
        "主标题「Data Nexus」，副标题「一张图 · 一个协议 · 一种查询 —— 联结一切数据、智能体与行动」。\n"
        "一句话：用户用大白话提问，系统自动去各种数据源（数据库、Excel/文件、知识库，甚至别的 AI 智能体）找答案、"
        "拼起来给结论，必要时还能顺手执行动作。\n"
        "全篇路线：为什么做（第2页）→ 系统蓝图（第3页）→ 逐个部件（第4-8页，含自动建本体）→ 执行细节（第10-12页）"
        "→ 端到端（第14页）→ 架构/落地/价值/定位（第13-18页）。"
    ),
    2: (
        "【第2页 · 要解决什么问题（痛点 → 目标）】\n"
        "图上：左边 6 类数据源汇聚到中间「Data Nexus」大圆；右上橙框是用户一句话提问，右下绿框是系统自动产出的结果。\n"
        "痛点：老板问「华东上季度为什么下滑？并安排复盘」。今天要人肉打开数据库查数、翻 Excel、搜文档、找人归因、"
        "手动建复盘任务——答案散在一堆系统，每接一个新源都要单独开发，AI Agent 又是另一套。\n"
        "目标：有了 Data Nexus，用户只需一句话，系统自动：① 找到能回答的源、跨源查齐；② 综合结论并标明出处；"
        "③ 需要时顺手执行（自动派复盘任务）。\n"
        "一句话：把「人肉跨系统」变成「提一句话」。"
    ),
    3: (
        "【第3页 · 系统蓝图：所有部件如何联合运作】\n"
        "全局总图，后面每页都是放大它的一块。分三层：\n"
        "▶ 上层「知识层 · 本体」（静态）：Concept（业务名词，第4页）、Binding（概念映射到真实表，第5页）。\n"
        "▶ 中层「运行引擎」（动态）：用户提问 → 编译器（自然语言 + Concept → 查询指令 SQG）→ SQG（第9页）→ "
        "调度器 Dispatcher（选源）→ 协调器 Coordinator（并行执行 + 合并 + 裁决）→ 生成器 Generator（写答案 + 血缘）→ 答案。"
        "引擎细节见第10页。\n"
        "▶ 下层「能力层 · Resolver」（静态）：数据源/Agent/动作 Resolver，详见第6、7页。\n"
        "两条虚线是「供给」：编译时向上查 Concept/Binding；执行时向下调用 Resolver。"
    ),
    4: (
        "【第4页 · Concept：业务名词长什么样】\n"
        "（放大蓝图上层的 Concept）图上：左边 concept.json 代码，右边逐字段说明。\n"
        "Concept = 业务名词：销售额=指标、地区=维度、客户=实体。只讲「是什么」，不管数据存哪。\n"
        "以「销售额」为例：· id 唯一标识。· kind 类型（实体/属性/关系/指标/维度），本例是指标。· semantics 业务含义。"
        "· type 数据类型。· bindings（★）指向哪些真实源，可多个（跨源融合的支点，见第5页）。· policy 权限。· provenance 血缘。\n"
        "要点：一切本体元素都长成同一个形状，只是 kind 不同。"
    ),
    5: (
        "【第5页 · Binding：概念怎么对接物理表】\n"
        "（放大蓝图上层的 Binding）图上：左边三层（Concept → Binding → 真实表），右边拼出来的 SQL。\n"
        "Concept 只讲业务、不含物理，靠 Binding（绑定/映射）当桥落到真实表：销售额 = SUM(fact_sales.amount)、"
        "地区 = dim_region.region_name，以及怎么 join。用户问「华东上季度销售额」，编译器靠 Binding 拼出右边那段 SQL。\n"
        "三条要点：① 换库/加源只改 Binding，Concept 不动；② 同一概念可绑多个源 = 跨源融合；③ 对接不一定是表——"
        "Agent 对接的是「提问模板」，文件对接的是路径。\n"
        "那 Concept 和 Binding 谁来建？——第8页，能自动生成。"
    ),
    6: (
        "【第6页 · Resolver：谁去执行（源 = 智能体 = 动作）】\n"
        "（放大蓝图下层）图上：最上面统一接口「interface Resolver」（三方法 capabilities() / plan() / resolve()）；"
        "下面三个框各指向接口——数据 Resolver、Agent Resolver、动作 Resolver。\n"
        "最关键的一步「抹平」：数据源、AI 智能体、执行动作，三种东西长成同一个接口。\n"
        "· 数据 Resolver：resolve() = 生成查询取数。· Agent Resolver：resolve() = 用自然语言问它，返回答案+证据。"
        "· 动作 Resolver：resolve() = 执行副作用（派任务），返回回执。\n"
        "三方法：capabilities() 报能力清单（能答哪些概念、成本、时效、信任分）；plan() 评估；resolve() 干活。\n"
        "底部核心句：调度器眼里没有「源」和「Agent」之分，只有一堆报了能力清单、竞标同一段查询的 Resolver。分类见第7页。"
    ),
    7: (
        "【第7页 · Resolver 5 类清单】\n"
        "图上：一张 4 列表格（源类型/性质/交互方式/说明），5 行：① 关系库 SQL/PG（被动·确定）② 向量库/知识库"
        "（被动·近似 RAG）③ Fabric Data Agent★（主动·黑盒，自然语言 ask()）④ REST/SaaS API（被动·外部）"
        "⑤ 动作：写回/审批/触发★（主动·有状态）。\n"
        "「性质」：被动 = 你用查询语言去取数、结果确定；主动 = 你把需求交给它、它自己去办。\n"
        "重点：主动源（第 3、5 行）是本平台差异化——把智能体和写回动作也纳入同一套 Resolver 接口。"
    ),
    8: (
        "【第8页 · Concept 和 Binding 怎么自动生成】\n"
        "第4、5页的 Concept 和 Binding 不能只靠人手工输入，那样本体永远建不起来。做法是让 Resolver 去探测源、抽样数据自动推断。\n"
        "图上：四步流程——① 探测（describe() 让源自己报出有哪些表、字段，再抽几行样例）→ ② 理解（看列名/类型/去重数/"
        "样例值/外键）→ ③ 生成候选（Concept + Binding + 置信度）→ ④ 确认（高置信自动收，低置信标红）。\n"
        "销售例子：探测到 fact_sales(amount, region_id, order_date)、dim_region(region_id, region_name) 和外键，就自动推断出："
        "销售额=指标、地区=维度；Binding 销售额=SUM(fact_sales.amount)、地区=dim_region.region_name；join 也自动填好。\n"
        "跨源合并：SQL 的「销售额」和 Agent 懂的「销售额」，系统识别是同一个，自动合并成一个概念、绑两个源 = 跨源融合。\n"
        "关键：半自动——机器生成候选，人只确认/改名剩下的；遇到含义歧义、度量可加性、敏感数据交给人（敏感数据只抽脱敏统计）。\n"
        "不同源探测方式不同：SQL 最全；文件靠列名匹配猜关联；Data Agent 是黑盒，改成直接问它「你能答哪些概念」让它自报能力清单。"
    ),
    9: (
        "【第9页 · SQG（语义查询图）：问题被翻成的统一查询指令】\n"
        "SQG = Semantic Query Graph = 语义查询图，通俗叫「查询指令」。\n"
        "图上：顶部流水线 提问→编译→SQG→规划→执行→合并；中间六个算子；底部结论。\n"
        "六个算子：SELECT 取属性；FILTER 维度约束（只看华东）；AGGREGATE 指标计算（对销售额求和）；TRAVERSE 沿关系跳转·"
        "天然跨源 join；ASK★ 把一段交给 Agent 回答；ACT★ 执行动作/写回。\n"
        "底部结论：问答=ASK、跨源 join=TRAVERSE、写回=ACT 都是同级算子，所以「分析」和「行动」用同一套引擎——既能答也能做。\n"
        "它具体长什么样、怎么被执行，见第10-12页。"
    ),
    10: (
        "【第10页 · 执行引擎：一次提问怎么跑完（总览）】\n"
        "（放大蓝图中间的引擎）图上：提问 → 编译器 → 调度器 → 三条并行车道（fetch/ask/act）→ 协调器（合并+裁决）→ 生成器（答案+血缘）。\n"
        "三段引擎：· 调度器 Dispatcher（派活）：把查询指令拆成子任务，让相关 Resolver 竞标，选中最合适的。"
        "· 协调器 Coordinator（并行执行 + 合并）：让三类 Resolver 并行同时干活，再按「概念主键」对齐拼起来；打架时按"
        "「信任×时效×精度」加权裁决。· 生成器 Generator（写答案）：用合并后的数据写出最终答案并附血缘。\n"
        "这一页是总览；接下来第11、12页用一个例子把「调度器怎么产出计划、协调器怎么执行」拆到实现级。"
    ),
    11: (
        "【第11页 · 执行细节①：查询指令(DAG) → 调度器产出执行计划】\n"
        "承接第10页，把「查询指令 → 调度器」拆到实现级，用「华东上季度毛利为什么下滑，给说明并派复盘任务」举例。\n"
        "左边：查询指令不是一段文字，而是一张 DAG（有向无环图）——5 个节点 + 依赖边。· n1 毛利数值、n2 毛利趋势、n4 佐证 "
        "无依赖，可先并行；· n3 归因(ASK) 依赖 n1、n2（要拿数字才能解释）；· n5 派任务(ACT) 依赖 n3（说明就是任务内容）。\n"
        "右边：调度器给每个节点选中一个 Resolver，并用 Binding 把节点编译成「具体调用」：· n1/n2 → 数仓：编译成 SQL。"
        "· n3 → 销售 Agent：编译成自然语言 prompt。· n4 → 知识库：编译成检索。· n5 → 工单系统：编译成 HTTP POST。\n"
        "关键：依赖别人的节点（n3、n5），它的调用里留占位符 {n1}{n2}{n3}，要等上游结果出来后运行时才回填；独立节点是立即可执行的完整语句。\n"
        "一句话：调度器 = 选源 + 把每个节点编译成真实调用（SQL/自然语言/HTTP）。"
    ),
    12: (
        "【第12页 · 执行细节②：协调器分波并行 + 回填 + 裁决】\n"
        "承接第11页：调度器出了执行计划，协调器负责真正跑完这张 DAG。它按依赖分成几波，能并行的并行：\n"
        "· 第1波（n1/n2/n4 无依赖）：同时发出。返回：n1 毛利=1200万(-15%)、n2 趋势 480/420/300、n4 命中两篇文档。\n"
        "· 第2波（n3）：把 n1、n2 的结果回填进 prompt（「毛利1200万(-15%)，趋势480/420/300，请解释」），再调销售 Agent。"
        "返回：主因=大客户Q1减采30%+原材料涨价，附引用证据。\n"
        "· 第3波（n5）：把 n3 的说明回填进任务内容，再调工单系统。返回：工单#4521已创建、派给张三、回执。\n"
        "执行完做两件事：· 合并：把 n1/n2/n3/n4 按主题（华东·毛利·上季度）拼成一份，n5 回执附上。· 裁决：若某源报的毛利"
        "和 n1（数仓，信任0.98）冲突，以数仓为准，败者数字丢弃、文字保留；裁决记入血缘，可追溯。\n"
        "一句话：协调器 = 按 DAG 分波并行 + 上游结果运行时回填 + 结果合并 + 数字冲突按信任分裁决。"
    ),
    13: (
        "【第13页 · 真实报文：查询指令 → 调度计划 → 执行结果（三段 JSON）】\n"
        "承接第11、12页的图，这一页把背后的三段真实 JSON 摊开，一眼看清「问什么 → 谁来答 → 答什么」。\n"
        "① 查询指令 SQG（编译器输出）：每个节点有 op（算子：AGGREGATE/SELECT/ASK/ACT）、concept（问哪个概念）、"
        "deps（依赖谁）。此刻 n3.prompt 里的 {n1}{n2}、n5 的 {n3} 还是占位符。\n"
        "② 调度器 plan（本页重点·橙框）：调度器给每个节点选中一个 resolver（数仓 dwh.sql、知识库 kb.vector、"
        "销售 agent.sales、工单 ticket.http），并用 Binding 编译成真实调用（SQL/检索/自然语言/HTTP）——这一步就是"
        "「把查询指令翻译成 Resolver 调用」。\n"
        "权限透传（重要）：plan 顶部 as_user 是当前用户（zhangsan@beone）。有些 resolver 自己带用户级权限控制"
        "（行级安全/数据权限），它们会在能力清单里声明「支持用户级权限」；调度器给这些节点打上 user_scoped:true，"
        "调用时把当前用户身份一并传过去——dwh.sql 按用户做行级安全过滤、agent.sales 以该用户权限运行、"
        "ticket.http 以其身份建单。注意 n4 知识库是公共文档、不带 user_scoped。好处：权限在数据源头强制，"
        "不在应用层手工拼 where，既安全又不会漏。\n"
        "③ 执行结果（协调器回填后）：占位符全变真值（毛利 1200万、趋势 480/420/300、归因带 evidence、工单 #4521），"
        "末尾 verdict 记录裁决——n1（数仓·信任 0.98）胜、弃对方数字，写进血缘可回溯。\n"
        "一句话：SQG（问什么）→ plan（谁来答·怎么调·谁在问）→ result（答什么），三段一一对应。"
    ),
    14: (
        "【第14页 · 分层架构：每层只做一件事】\n"
        "图上：五个横条从上到下（L5→L1），右侧竖条贯穿五层。\n"
        "· L5 体验层：对话·画布·渲染。· L4 意图层：把请求翻成查询指令。· L3 认知层（引擎核心）：调度器·协调器·生成器"
        "（即第10页那三段）。· L2 语义层：本体——Concept + Binding（第4、5页）+ 各源的能力清单。· L1 接入层：数据/Agent/动作 "
        "Resolver（第6、7页）。\n"
        "右侧竖条「治理内生·权限/血缘/成本」：权限和血缘随每个概念一起挂在本体上（第4页 Concept 的 policy/provenance），横跨所有层。\n"
        "落地：按层切模块，每层只依赖下一层接口；L3 认知层是研发重心。"
    ),
    15: (
        "【第15页 · 端到端例子：走一遍全流程】\n"
        "图上：顶部是用户提问，下面横向四段引擎 —— ① 编译器 → ② 调度器 → ③ 协调器 → ④ 生成器，用箭头串起来。"
        "这是把第 10–13 页收束成一张「一次提问、走完全程」的全景图，五个节点 n1–n5 全程一致。\n"
        "问题：「华东上季度毛利为什么下滑？给份说明，并把复盘任务派给区域负责人。」\n"
        "① 编译器：把问题拆成 5 节点的 DAG —— n1 毛利数值、n2 毛利趋势、n4 佐证文档、n3 归因(ASK，依赖 n1·n2)、"
        "n5 派任务(ACT，依赖 n3)。\n"
        "② 调度器：给每个节点选中 resolver 并编译成真实调用 —— n1·n2→数仓(SQL)、n4→知识库(检索)、n3→销售 Agent(NL)、"
        "n5→工单(HTTP)；透传当前用户 as_user；依赖别人的节点留 {n} 占位符。\n"
        "③ 协调器：按依赖分波执行 —— 第1波 n1·n2·n4 三源并行；第2波 n3 回填 n1·n2 后调 Agent；第3波 n5 回填 n3 后调工单；"
        "最后合并 + 裁决(数字冲突以数仓 0.98 为准)。\n"
        "④ 生成器：写出说明(大客户减采 30% + 原材料涨价) + 趋势(480/420/300) + 血缘/信任分 + 证据 2 篇，并附工单 #4521 回执。\n"
        "重点(底部)：全程没有任何「针对数仓 / 针对 Agent / 针对写回」的特殊分支，全是「SQG 算子 + Resolver 竞标 + 分波执行 + "
        "合并裁决」；加新源只写一个 Resolver，这条流程不改。\n"
        "讲解提示：这一页要和第 11、12 页对上 —— 归因(n3)和派任务(n5)不是一开始就并行，而是等上游结果回填后才执行；"
        "动作的回执是附加输出，不参与「按信任分裁决」（裁决只针对会冲突的数字）。"
    ),
    16: (
        "【第16页 · 落地路径：分阶段建】\n"
        "图上：一条时间轴，五个里程碑 P0→P4。\n"
        "· P0 骨架：本体 + Resolver 接口 + 查询指令编译器；验证一个 SQL 源能问答。· P1 联邦：加向量库 Resolver + 合并/裁决；"
        "验证跨源融合。· P2 智能体源★（最大亮点）：加 ASK 算子 + 接一个 Fabric Data Agent；验证「Agent = 源」。"
        "· P3 行动：加 ACT 算子 + 动作 Resolver；验证「分析 → 行动」打通。· P4 自演化：让 Resolver 探测源自动生成本体"
        "（即第8页那套）。\n"
        "建议：每阶段都要有可演示闭环；P0 就把三大接口（Concept/Resolver/查询指令）定死，之后只加实现、不改范式。\n"
        "风险点：本体自动生成的准确率、Agent 返回证据的结构化、跨源主键对齐。"
    ),
    17: (
        "【第17页 · 价值：这套设计带来什么】\n"
        "图上：五张卡片 ①~⑤ + 底部判据。\n"
        "① 加源零范式：接一个新系统 = 写一个 Resolver，引擎不改。② 一种查询：查数据/血缘/权限/问 Agent 全是同一种查询，"
        "不用维护多套 API。③ 分析即行动：ASK 和 ACT 同级，洞察到执行在同一引擎里打通。④ 治理内生：权限和血缘随概念一起管"
        "（第4页 policy/provenance），可追溯是默认。⑤ Agent 无缝：多智能体联邦是 Resolver 竞标机制的自然子集。\n"
        "底部判据：加任何新东西，本质只是「本体里加一个概念，或加一个 Resolver」，范式不变。"
    ),
    18: (
        "【第18页 · 三个战略定位】\n"
        "图上：三列方案 A/B/C + 两条横幅。A · 联邦语义中台：跨源统一问答 + 血缘治理；对标 Palantir、dbt；偏重、B 端。"
        "B · Agent 编排总控：把 Fabric、MCP、专家 Agent 编排起来；踩中 Agent 热点；轻、快。C · 自助分析 Copilot（★）："
        "业务人员自然语言跨源分析 + 自动可视化；是当前 PowerBI Copilot 的超集；落地最短。\n"
        "建议：C 起步（复用现有资产最多）→ 架构按 A 分层 → 内置 B 的「Agent 即源」做核心差异化。\n"
        "可复用资产：Orchestrator→调度器、ToolProvider→Resolver、FrontChannel、Renderer、Credential、API 权限体系。"
    ),
    19: (
        "【第19页 · 后续可深挖的四个方向】\n"
        "图上：2×2 四张卡片。1 · 本体存储选型：属性图 vs RDF vs 关系库模拟；P0 用 SQL 模拟起步。2 · 查询指令的完整算子代数 + "
        "编译器：把六个算子定义完整，设计 NL→查询指令的受约束生成。3 · Resolver 竞标/路由算法：用「成本-信任-时效」加权模型"
        "决定哪个源中标、冲突如何裁决。4 · 自动建本体的准确率：把结构探测 + 抽样 + LLM 推断的候选做得更准，减少人工确认。\n"
        "任选其一，可展开到接口 / 伪代码级。"
    ),
}

for i, slide in enumerate(prs.slides, start=1):
    text = NOTES.get(i, "")
    if text:
        slide.notes_slide.notes_text_frame.text = text

prs.save(str(OUT))
print("Saved:", OUT, "| slides:", len(slides_data))
