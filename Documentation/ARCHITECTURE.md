# nvme-cli 架構與工作區筆記

核對日期：2026-10-27（Asia/Taipei）。本機基準：`19e7e83ba`，
`meson.build` 宣告版本 3.1。這是專案內的持久筆記，搭配根目錄 `PROJECT-GUIDE.md`
使用；更換版本後應重新核對。

## 專案目的

nvme-cli 提供 NVMe 裝置管理 CLI，支援本機裝置、NVMe-oF 與廠商擴充。
本樹同時維護 CLI、libnvme、Python bindings 及可選背景服務。
主要語言為 C，Meson 使用 gnu11；Python 用於測試、產生器與 bindings。

## 呼叫與資料流

```text
src/main.c:main()
  └─ src/nvme.c:nvme_main()
      ├─ 初始化 stdio、sandbox、參數 metadata
      ├─ src/plugin.c:plugin_lookup()：解析全域選項並找出命令
      ├─ src/privsep.c：依建置與命令決定權限處理
      ├─ 讀取全域設定、設定訊號處理
      └─ plugin_call_run()
          └─ src/nvme-cmds-*.c 或 plugins/<name>/ 的 callback
              ├─ 參數解析、建立 context、開啟 transport handle
              ├─ nvme_init_* 等 helpers 建立規格命令
              ├─ libnvme_* / libnvmf_* API
              │   └─ libnvme/src/nvme/ 平台或 transport 後端 → 裝置
              └─ nvme_show_* / nvme-print 分派 → stdout / JSON / binary
```

此圖描述典型裝置命令；help、enumeration、fabrics、daemon 命令的路徑不盡相同。
外掛由建置選入並連結，以 constructor 註冊，並非執行時掃描 DLL／so。

## 目錄地圖

| 路徑 | 責任與閱讀入口 |
| --- | --- |
| `src/main.c`、`src/nvme.c` | 程式入口與生命週期 |
| `src/plugin.c`、`src/plugin.h` | 命令結構、查找、分組、help 與 callback 執行 |
| `src/nvme-cmds-*.c` | ctrl、io、discovery、fabrics、feature、register、sanitize、security 等內建命令 |
| `src/args.*`、`src/argconfig.*`、`src/global-*.c` | 選項 metadata、解析、設定、全域 context |
| `src/nvme-print*.c` | 輸出分派、人類可讀、JSON、binary 與部分解碼 |
| `plugins/` | core 功能及廠商命令；從對應 Meson 與註冊區塊進入 |
| `libnvme/src/nvme/` | 公開 API、規格型別、命令編碼、拓樸、掃描、transport、fabrics、MI |
| `libnvme/src/nvme/*-linux.c`、`*-win.c`、`*-freebsd.c` | 作業系統專用裝置與 ioctl 等後端 |
| `libnvme/src/nvme/generated/` | 產生的 accessor C／標頭 |
| `libnvme/tools/generator/` | accessor 與其他 bindings 相關產生工具與 targets |
| `libnvme/src/*.ld` | 公開 ABI 與 accessor 符號版本 |
| `libnvme/libnvme3/` | Python／SWIG bindings |
| `libnvme/src/sed/` | TCG Storage／SED 功能 |
| `src/privsep.c`、`libnvme/src/privsep/`、`libnvme/privsep/` | 降權決策、client protocol、特權 helper |
| `shared/` | LGPL 共用工具靜態庫；`shr_` 命名，不放 CLI 專屬邏輯 |
| `daemon-util/` | 背景服務共用的 logging、signals、resolve、work 工具 |
| `discoverd/` | NVMe-oF discovery、網路／FC／mDNS、連線狀態與服務協調 |
| `keysd/` | TLS 金鑰佈建及可選 KMIP helper |
| `nvmf-autoconnect/`、`etc/` | 舊 autoconnect 與安裝配置／系統整合 |
| `ccan/` | 內嵌 C 工具 |
| `tests/unit/`、`tests/cli/` | 單元測試與 CLI mock 測試 |
| `tests/fuzz/`、`scripts/fuzz/` | fuzz targets、corpus、執行與分析工具 |
| `tests/e2e/` | 明確選入、可能讀寫實體或模擬裝置的測試 |
| `libnvme/tests/`、`shared/tests/` | library 與共用工具測試 |
| `Documentation/`、`completions/` | 架構與使用文件、命令 man page、產生的 shell completion |
| `.github/workflows/` | 多平台建置、ABI、accessors、completions、checkpatch 等 CI |

## 建置與平台限制

`meson.build` 決定 feature、dependency 與平台條件；各目錄 Meson 決定來源清單。
常用設定在 `meson_options.txt`，Makefile 與 `scripts/build.sh` 是包裝入口。
3.x 預設由此樹建置 libnvme；明確停用內建 library 的配置另有已安裝 library
fallback，不能把所有配置都當成沒有外部 library 路徑。

Linux 是完整功能的主要環境；Windows 與 FreeBSD 有專屬後端。此版本
fabrics、MI、privsep、top 的平台條件在根 Meson 受 Linux 限制；sandbox
限 Linux／FreeBSD，privsep 與 sandbox 均預設停用。systemd daemon 有額外依賴。
JSON 與大量外掛取決於 json-c，實際可用範圍必須看建置摘要。

常用無硬體驗證：

```sh
meson setup .build
meson compile -C .build
meson test -C .build --suite unit --suite mock
# 視修改內容追加：
meson test -C .build --suite check
meson test -C .build --suite fuzz
```

mock 測試使用真正 CLI 搭配 `tests/cli/libmock_nvme.c` 與 Python 控制器／IPC，
不需要實體 SSD。suite 還包含 `unit`、`mock`、`e2e`、`fuzz`、`check`；
讀 `Documentation/TESTING.md` 選擇範圍，不能把全部測試都稱為 unit tests。

## 參考文件與實作差異

已依本機 CONTRIBUTING、Meson、測試文件與實作核對開發慣例。
專案工作規則已整理至根目錄 `PROJECT-GUIDE.md`。

不能照搬的舊資訊：

- 根目錄巨型 `nvme.c`、`nvme-builtin.h`／ENTRY 註冊、`util/` 路徑：
  此 checkout 已是 `src/`、分拆命令與 `shared/`。
- 舊 `nvme_*`／`nvmf_*` 公開 library 前綴：以當前 CONTRIBUTING 的
  `libnvme_*`／`libnvmf_*` 規則為準；spec helpers 仍可保留短前綴。
- 舊 accessor 位置：真實來源為 `libnvme/src/nvme/generated/`，版本檔在
  `libnvme/src/`；`update-accessors` 也涵蓋 attribute accessors。
- CONTRIBUTING 範例 `.no_device` 與舊 argc 說明：實際 `struct command`
  已有 `enum command_device device`。以 `src/plugin.h`、parser 與同類命令核對。
- CONTRIBUTING 與部分參考文件對新 ABI version section 有不同描述。
  此次沒有修改 ABI；未來變更先核對當時政策與維護者明確指示。
- 專案總覽與新檔授權說明有 GPL-only／or-later 表述差異；依檔案 SPDX 與
  當前 CONTRIBUTING 處理，不能批次統一既有授權。

## 此工作區的已知狀況

- 使用者提供的 GitHub 專案為 `https://github.com/allen4791/nvme-cli`。
- 初次檢查 `origin` 為 `https://github.com/linux-nvme/nvme-cli.git`，分支
  `master`。這是歷史紀錄；進行 Git 操作前必須重新查驗。
- 2026-10-27 依使用者授權設定 fork 推送：`origin` 改為
  `https://github.com/allen4791/nvme-cli.git`，原上游保留為 `upstream`，
  `remote.pushDefault=origin`。文件分支以本機 `19e7e83ba` 為基準；當時
  fork 的 `master` 為 `be1c96afd`，落後此基準 1021 筆提交，未更新 fork master。
- 可攜式 Git：`.local-tools/git/cmd/git.exe`，未設定系統 PATH。
- `Open-GitHub.cmd`、`GITHUB-WORKFLOW.md` 及 `.local-tools/` 為前次建立的
  本機查看流程；其中工具二進位與下載包不應提交。
- 此次閱讀時 PATH 找不到 Meson／GCC／Clang，只有 Ninja；未進行編譯或
  裝置測試。這不是原始碼無法建置的判定。
- 架構閱讀階段只建立規則與筆記；後續使用者另行授權將兩份文件提交並推送
  至 fork 新分支。本次授權不包含實體 NVMe 裝置操作。

## 後續任務的定位方式

搜尋命令名稱 → 註冊的 `struct command` → callback → 參數／handle →
libnvme 呼叫與 spec 型別 → 平台後端 → 輸出層 → mock／fuzz／文件／completion。
涉及共用 API 時再檢查 ABI、產生器、fabrics-disabled 建置與跨平台 CI。
完成架構修改後更新本筆記的相關段落，避免只沿用本次快照。
