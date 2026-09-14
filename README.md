# opencode for fnOS

把 [opencode](https://github.com/anomalyco/opencode)（开源 AI 编程代理）打包成飞牛 fnOS 可安装的 `.fpk` 应用，非 root 运行，数据持久化在共享目录。

- 应用入口：飞牛桌面「opencode」→ iframe 内嵌 opencode Web UI（端口 `14096`）
- 控制台：飞牛桌面「opencode 控制台」→ 启停 / 重启 / 日志 / 重置密码 / 备份 / 在线升级
- 架构：`x86`（默认 `x64-baseline` 二进制，兼容无 AVX2 的 NAS CPU）

## 目录结构

```
.
├── manifest                  # 应用元信息（appname/version/platform/service_port ...）
├── ICON.PNG / ICON_256.PNG   # 应用图标（由脚本生成）
├── config/
│   ├── privilege             # run-as: package（非 root）
│   └── resource              # data-share：用户可见的数据目录
├── cmd/                      # 生命周期脚本（逻辑集中在 common）
├── app/
│   ├── opencode              # 二进制（构建前置入，未入库）
│   ├── ui/
│   │   ├── config            # 两个桌面入口（本体 + 控制台）
│   │   ├── index.cgi         # 控制台静态文件服务
│   │   ├── api.cgi           # 控制台后端 API
│   │   └── images/           # 入口图标
│   └── www/index.html        # 控制台页面
├── wizard/                   # 安装 / 升级 / 卸载向导
├── scripts/                  # 图标生成 / 拉取二进制 / 打包（本地）
├── .github/workflows/        # GitHub Actions：自动追上游并出包
└── LICENSE
```

## 构建

需要 Node、PowerShell（Windows）。构建脚本会自动下载 `fnpack 1.2.3`。

```powershell
# 1. 准备图标（首次）
powershell -ExecutionPolicy Bypass -File scripts\make-icons.ps1

# 2. 准备 opencode 二进制（约 176MB）
powershell -ExecutionPolicy Bypass -File scripts\fetch-opencode.ps1
#   如网络受限，可自行下载 opencode-linux-x64-baseline.tar.gz 并解压出 opencode 放到 app/opencode

# 3. 打包
powershell -ExecutionPolicy Bypass -File scripts\build.ps1
#  产物：dist\com.opencode.web_v<version>.fpk
```

也可以直接跳到第 3 步，`build.ps1` 会在缺件时自动调用前两步。

## 安装到飞牛

1. 应用中心 → 设置 → 手动安装应用 → 选择 `dist/*.fpk`
2. 安装向导中设置登录用户名、访问密码、工作目录（可留空）与日志级别
3. 安装完成后点击桌面「opencode」图标即可使用

## 运行机制

| 路径 | 用途 |
|---|---|
| `/var/apps/com.opencode.web/target/opencode` | 二进制 |
| `/var/apps/com.opencode.web/etc/opencode.env` | 密码 / 日志级别（持久，升级保留） |
| `/var/apps/com.opencode.web/var/` | 运行日志与 PID |
| `/var/apps/com.opencode.web/shares/com.opencode.web/` | 数据目录（`HOME`/XDG，用户可在文件管理器访问） |

服务启动命令等价于：

```bash
cd <数据目录>
HOME=<数据目录> OPENCODE_SERVER_PASSWORD=*** BROWSER=true \
  opencode web --hostname 0.0.0.0 --port 14096
```

## 控制台说明

「opencode 控制台」分三个标签页：

- **日志**：服务状态（端口 / PID / 用户名 / 工作目录 / Node.js）、启停与重启、`var/opencode.log` 内容与清空。
- **设置**：修改登录用户名、访问密码、工作目录与日志级别。用户名与密码对应 opencode 的 HTTP Basic 认证（`OPENCODE_SERVER_USERNAME` / `OPENCODE_SERVER_PASSWORD`）；保存后服务会**自动重启**使配置生效。
- **升级与备份**：从 GitHub Releases 拉取与当前架构匹配的最新二进制（原子替换后自动重启，x86 无 AVX2 时自动选 `x64-baseline`）；以及打包数据目录为 `.tar.gz` 下载。

工作目录通过 `opencode web --dir <路径>` 指定（旧版本为 `--cwd`，脚本会自动探测）。留空则使用应用数据目录；指向 NAS 其他目录前，请先在飞牛应用设置里把该目录授权给本应用。

## 注意事项

- **升级本应用**（覆盖安装）会保留 `etc/` 与 `shares/`，数据不丢；卸载向导可选择是否删除数据目录。
- **安全**：opencode 具备文件读写与命令执行能力，且入口对所有用户可见；请务必设置强密码，不要把 14096 端口直接暴露到公网。
- **`.cgi` 执行权限**：若真机上控制台报 502/无法执行，SSH 到飞牛执行
  `sudo chmod +x /var/apps/com.opencode.web/target/ui/index.cgi /var/apps/com.opencode.web/target/ui/api.cgi`。
- 若 `iframe` 方式打开本体出现资源 404（子路径问题），可改用子路径网关方案（参考 `fngateway.py` 思路）。

## 修改默认值

- 端口：同步修改 `manifest` 的 `service_port`、`app/ui/config` 的 `port`、`cmd/common` 与 `app/ui/api.cgi` 里的 `PORT`。
- 应用标识：修改 `manifest` 的 `appname` 与 `config/resource`、`app/ui/config`、`cmd/common`、`app/ui/*.cgi` 中的对应值。
- 上游维护者：`manifest` 的 `distributor` / `distributor_url`。

## 可选：多架构与运行时依赖

### 支持 arm64

1. `manifest` 的 `platform` 改为 `arm`；
2. 用 `powershell -File scripts\fetch-opencode.ps1 -Target arm64` 取 ARM 二进制；
3. `app/ui/api.cgi` 的 `arch_target()` 已识别 `aarch64/arm64`，无需改动。

> 二进制分架构，**不能**用 `platform = all`；如需 x86 + arm 同时支持，要分别出两个 fpk。

### 依赖 Node.js（用于 MCP Server / Node 技能）

本包默认不依赖任何运行时。若需要 Node.js，在 `manifest` 增加一行：

```ini
install_dep_apps = nodejs_v24
```

安装时飞牛会先安装该应用。控制台的「状态」区会显示 Node.js 是否已安装
（接口：`api.cgi?action=check_deps`）。

> `nodejs_v24` 必须与应用中心里的实际 `appname` 一致，否则安装会因找不到依赖而失败。

## 发布与迭代（GitHub Actions）

`.github/workflows/build-release.yml` 会自动跟踪 opencode 上游并出包：

- **自动**：每天 04:00（北京时间）拉取 opencode 最新 release，若与 `manifest.version` 不同则构建；
- **手动**：Actions → *Build fnOS package* → *Run workflow*，可填 `version`（指定版本）与 `force`（强制重建）；
- 构建流程：下载 `opencode-linux-x64-baseline` 二进制 → 下载 `fnpack 1.2.3` → 改 `manifest` 版本/changelog → `fnpack build` → 建 Release `v<版本>` 并附带 `.fpk`。

**版本号策略**：`manifest.version` 跟随 opencode 上游版本（如 `1.15.6`）；仅打包自身改动时用修订号（如 `1.15.6-r2`）。

**首次发布**

```bash
git init && git add -A && git commit -m "feat: opencode fnOS 应用包"
git branch -M main
git remote add origin https://github.com/<你的用户名>/fn-opencode.git
git push -u origin main
```

推送后在仓库 Settings → Actions 允许运行工作流即可；手动触发一次出首个 Release。

> 二进制 `app/opencode`（约 176MB）与 `dist/`、`tools/` 已在 `.gitignore` 中，**不会进入 git**；发布物只走 Releases。

## 版权与免责声明

- 本仓库仅为 **非官方第三方打包**，与 opencode 官方（anomalyco）无隶属关系；
- opencode 本体版权归其上游所有，遵循其自身许可，本仓库不改动其代码，仅在安装时下载/分发其二进制；
- 本仓库的打包脚本与配置采用 MIT 许可（见 `LICENSE`）；
- 应用图标取自 opencode 官方资源，版权归上游所有，仅用于标识该应用；
- 使用前请自行评估安全与合规风险。

## 许可

本打包仓库仅供个人使用；opencode 本体遵循其上游许可。
