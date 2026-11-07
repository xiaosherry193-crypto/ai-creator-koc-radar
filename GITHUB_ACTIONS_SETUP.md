# GitHub 每日自动抓取

这一版可以在电脑关机时运行，负责抓取公开的 X、Reddit、GitHub、YouTube 和 Instagram 搜索结果，并把每天的名单变化保存回 GitHub。

## 重要边界

- 这一版不依赖本机 Chrome。
- 这一版不读取本机的 Wednesday 或 hiCreator 登录状态。
- X 官方 API Token 不是必填；没有 Token 时会继续尝试公开搜索，但可抓到的数据会受公开搜索结果限制。
- 看不到的数据会保留为空或标记待核验，不会猜测。

## 一次性设置

1. 新建一个 GitHub 仓库，把 `ai_creator_lead_finder` 文件夹里的内容上传到仓库根目录。
2. 打开仓库的 `Actions` 页面，确认允许工作流运行。
3. YouTube 现在默认读取公开搜索页，不需要申请或填写 YouTube API 密钥。若以后你有 API 密钥，也可以作为可选加速方式加入，但不是运行条件。
4. 可选：同样新增 `X_BEARER_TOKEN`，用于补充 X 官方 API 数据。
5. 在 `Actions → AI Creator KOC Daily Crawl` 点击 `Run workflow`，先手动测试一次。

工作流每天北京时间上午 9:00 自动执行。每次运行会生成运行摘要、更新 `data/leads.json`、`data/leads.csv` 和 `data/runs.jsonl`，同时保留 30 天的下载快照。

## 当前结果

GitHub Actions 版适合先把公开名单自动跑起来。YouTube 接入后会按关键词搜索公开视频，按频道去重，并保存公开订阅数、视频播放量和作品链接；没有 API 密钥时会明确记录错误，不会用搜索摘要冒充 YouTube API 数据。
