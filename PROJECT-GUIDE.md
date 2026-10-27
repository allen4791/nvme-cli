# nvme-cli 專案工作指南

本檔記錄此工作區的專案規則。開始任務時先讀本檔與
[架構筆記](Documentation/ARCHITECTURE.md)，再依任務閱讀實作與相關文件。
使用者當次指示與適用的上層指示優先；本檔不授予硬體操作或遠端寫入權限。

## 閱讀順序與資料可信度

1. 先確認 Git 分支、HEAD、工作樹與 remotes，保留既有使用者修改。
2. 讀 `README.md`、`CONTRIBUTING.md`、`meson.build`、`meson_options.txt`。
3. 依功能讀 `src/nvme-cmds-*.c` 或 `plugins/<name>/`，追到 libnvme 與輸出層。
4. 對照測試、man page、平台條件與對應 CI；不要只憑檔名推測行為。
5. 規格欄位、位元、offset、長度及狀態碼需要 NVMe 規格或可信韌體定義佐證。
   不確定時說明缺少什麼，不臆造規格或測試期望值。

以目前 checkout 的原始碼、建置設定與 CONTRIBUTING 為準。部分參考文件
尚未跟上重構；不能直接套用其舊目錄、舊 ENTRY 巨集或舊 API 前綴。

## 架構邊界

- 此樹是 nvme-cli 3.x，`libnvme/` 是整合原始碼，不是外部 Git submodule。
- 入口是 `src/main.c` → `src/nvme.c:nvme_main()`；分派位於 `src/plugin.c`。
- 內建命令分散在 `src/nvme-cmds-*.c`，以 `struct command`、命令陣列與
  `plugin_add_group()` 註冊。具名外掛另外呼叫一次 `register_extension()`。
  新檔案需加入對應 Meson sources；依現有程式碼選用 constructor 巨集。
- 命令參數與裝置開啟沿用 `src/args.*`、`src/argconfig.*` 等現有介面；先看
  同類命令，勿照舊文件硬套 `NVME_ARGS` 或舊 callback 參數假設。
- 解碼與輸出沿用 `src/nvme-print*.c` 的分派，維持正常、JSON、binary 行為，
  修復解析錯誤時保留有效資料的 JSON 欄位、型別與結構。
- 共用 NVMe 公開 API 用 `libnvme_`，fabrics 專用 API 用 `libnvmf_`。
  規格資料結構與命令編碼可用 `nvme_`／`nvmf_`；不要混淆這兩類命名。
- `shared/` 對外名稱用 `shr_`，只放跨元件且無 NVMe／CLI 專屬依賴的工具。
  優先重用現有 helper，不增加第二套相同功能。
- Linux、Windows、FreeBSD 有各自後端。維持 fabrics 可停用的建置邊界，
  不將 Linux 專用標頭或功能無條件放進可攜式程式碼。

## 程式碼與相容性

- 遵循現有 Linux kernel 風格：Tab 縮排、通常 80 欄、簡單控制流程與早期回傳。
  維持鄰近程式碼的參數拼法；避免無關重排或大範圍重新命名。
- 重用 cleanup／字串／路徑／transport helper；配置路徑使用 `SYSCONFDIR`
  等建置值，libnvme 的新環境變數沿用 `LIBNVME_` 命名空間。
- 所有裝置／fabrics 回傳資料均視為不可信：檢查長度、數量、index、乘法溢位
  與 shift；注意 little endian、未對齊存取與保留欄位。重用現有安全讀取工具。
- 區分負 errno 與 NVMe completion status，沿用既有錯誤處理及退出碼。
- 保持公開 ABI；勿刪除或改動既有匯出符號。新增符號需檢查
  `libnvme/src/*.ld`，依當前 CONTRIBUTING 的版本段政策處理。
  若維護者指定政策與文件不同，先列出符號及差異，再依已授權範圍解決。
- 新來源檔依元件採正確 SPDX：CLI／plugins 按 CONTRIBUTING 使用
  `GPL-2.0-or-later`；`libnvme/` 與 `shared/` 使用 `LGPL-2.1-or-later`。
  既有檔案保留自己的授權，不依專案總覽一律改寫。

## 產生檔案

- 勿手改 `libnvme/src/nvme/generated/`。修改 `private.h`、
  `private-fabrics.h` 的 accessor 欄位或註記後，執行
  `meson compile -C .build update-accessors`；屬性 accessor 的來源另含
  `attr_accessors_specs.py`。以 `libnvme/tools/generator/meson.build` 為準。
- `.ld` 匯出版本檔須人工審核，產生器警告不代表已處理 ABI。
  產生結果與對應來源變更一起審查，勿混入無關重新產生的差異。
- 改變命令、外掛或參數後，在 Linux 完整外掛建置執行
  `meson compile -C .build update-completions`。不要用 Windows 精簡建置覆蓋
  三種 shell 的完整 completion。同步對應 `Documentation/nvme-*.txt`。

## 建置與驗證

- 基本流程：`meson setup .build` → `meson compile -C .build`。
- 一般無硬體驗證：`meson test -C .build --suite unit --suite mock`。
  依變更選取 `check`、`fuzz`、libnvme 與外掛相關測試；先查實際 suite 名稱。
- 新的裝置讀取命令依 CONTRIBUTING 加 CLI mock 測試，檢查正常與 JSON 值，
  使用規格／實際資料的非零欄位。修復測試應在錯誤實作失敗、修復後通過。
- 純讀取並輸出的命令適合加入 `tests/fuzz/fuzz-device.c`。既有命令 index
  不可換序，只在尾端新增；模型檢查同步 PCI IDs 與 mock seeds。
- 解碼及記憶體修復應以 ASan/UBSan 驗證；Clang 建置需一致的 C/C++ toolchain
  及 `-Db_lundef=false`。fuzz 發現的問題保留可重現回歸輸入。
- 可攜式變更對照 Windows MSYS2 UCRT64／CLANGARM64 CI，注意 `--werror`；
  Windows 無法涵蓋 Linux fabrics、MI、systemd 與所有外掛。
- 使用專案 checkpatch 流程與 `scripts/checkpatch-filter.pl`；釐清已知誤報，
  不為躲避工具誤報而破壞程式語意。
- 如缺少編譯器、Meson、平台或硬體，具體回報未執行項目，不宣稱測試通過。

## 操作範圍

- 閱讀、編輯及無硬體測試可依任務進行。實體裝置的 format、sanitize、write、
  namespace 變更、韌體下載／啟用及 e2e 測試須有明確目標與使用者授權。
- 不從 CONTRIBUTING 範例直接執行 `reset --hard`、force push 或清除工作樹。
  不把 `.local-tools/` 的 Git 執行檔、下載包或憑證加入提交。
- 此工作區使用者專案為 `allen4791/nvme-cli`；初次檢查時 origin 是
  `linux-nvme/nvme-cli`。每次遠端操作前重查，不自行假設 fork／upstream。
- 提交、推送與 GitHub 寫入依使用者既有授權執行，不由閱讀任務推定授權。
  若有提交，採 `<subsystem>: <summary>` 與正確 `Signed-off-by`，不得捏造身分。
- 新增檔案、分支、文件標題與 commit 訊息採一般專案用語，避免工具或助理相關命名。
- 架構或規則變動時同步更新本檔與架構筆記，記錄來源及核對的 commit。
