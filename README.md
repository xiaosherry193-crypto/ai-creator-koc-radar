# X KOC 每日名单平台

这是一个给 AI / 3D 创作者做公开名单发现和每日管理的小平台。当前支持 X、Reddit、GitHub 和 YouTube 的公开信息，并保留 Wednesday 手动导入内容，按 KOC / 素人规则整理候选账号，并按相关度排序。

## 能做什么

- 平台：X、Reddit、GitHub、YouTube；YouTube 默认不需要 API 密钥，会读取公开搜索页和公开频道页。
- 人群规则：最低粉丝数 100，按 100 / 300 / 500 / 1000 / 5000 / 10000 分层。
- 内容规则：至少发布过 2 条相关内容，且相关内容播放 / 浏览量超过 100。
- 默认关键词：AI、3D AI、Game、AI Game、Roblox、Steam、ComfyUI、Tripo、Meshy、Blender、GLB、Astra、Opus、Vibe Coding、AIGC。
- 自动去重、分类、评分。
- 在浏览器中查看总览、今日新增、全部名单和每日抓取记录，并导出 `data/leads.csv`。
- 可以把 Chrome 中 X 搜索结果页里看得到的文字或主页链接复制到面板，自动抽取账号。
- 可以把 Wednesday 复制出的公开名单粘贴进“导入 Wednesday”，系统会自动去重、记录本批次和今日新增数量。
- 总览页提供“开始今日任务”：自动补充公开候选、启动 X / hiCreator 排队核验，并显示今日完成状态。
- 只读取公开页面；不登录、不绕过权限、不发私信、不点赞、不关注，不处理私人联系方式。

筛选规则保存在 `data/rules.json`，后续每日任务按这个规则去重、补充和分层。粉丝数、发帖数和播放量只有在公开页面能看到时才会填入；看不到的账号会标记为待核验，不会臆测。

## 打开方式

在这个目录运行：

```bash
python3 creator_lead_finder.py
```

然后打开：`http://127.0.0.1:8765`

打开后重点看：`总览`、`今日新增`、`全部名单`、`每日记录`。每天在总览页点击一次“开始今日任务”即可启动当日流程；Chrome 需要保持 X、Wednesday 和 hiCreator 登录，并保持 X 页面与扩展可用。

也可以用一次性模式：

```bash
python3 creator_lead_finder.py --once --keywords "AI 3D, Blender, AI video" --limit 50
```

每天运行一次：

```bash
python3 creator_lead_finder.py --daily --platforms x --limit 100
```

## 推荐用法

1. 在 X 搜索 `AI 3D`、`Blender`、`AI video`、`generative artist` 等关键词。
2. 观察评分较高、近期仍有作品的账号。
3. 再人工确认作品质量、受众和是否适合合作。
4. 通过平台本身的公开入口联系，不要批量骚扰或自动发送内容。

如果 X 的公开搜索结果没有被搜索引擎返回，推荐使用 Wednesday。Wednesday 仍需要先由你在已登录页面中完成公开结果整理，再导入本平台：

1. 在 Chrome 打开 X，搜索 `AI 3D`、`Blender` 或 `AI video creator`。
2. 在 Wednesday 里整理你要的公开创作者。
3. 复制公开名单或主页链接。
4. 粘贴到平台左侧的“导入 Wednesday”，点击“导入并去重”。

搜索结果会保存到：

- `data/leads.json`
- `data/leads.csv`
- `data/runs.jsonl`

说明：平台目前不能直接读取 Chrome 插件内部的名单；Wednesday 负责发现账号，本平台负责统一整理、去重、筛选和查看历史。不会自动私信、评论、点赞、关注，也不会绕过 X 登录或权限。

## 创作者运营与触达转化

作者名单整理完成后，按项目根目录的 `AI_创作者触达与进群转化SOP.md` 执行“识别、核验、分级、触达、跟进和进群确认”。分级规则保存在 `data/outreach_rules.json`，当前阶段以触达和进群转化为主，作者培养、活动、激励和长期运营后续另行制定。

建议执行顺序：先建立作者卡片，再按 `≥100、≥300、≥500、≥1,000、≥5,000、≥10,000` 六档记录粉丝量，同时核验代表作品、内容数据和公开联系入口；随后标记 `KOC-1/KOC-2/KOC-3/观察池` 触达等级。KOC-1 人工定制，KOC-2 人工确认后发送，KOC-3 仅在平台规则和发送权限允许时做限量自动首触达，观察池暂不主动触达。进群后当前只记录欢迎和第一次有效互动，长期运营暂不展开。
